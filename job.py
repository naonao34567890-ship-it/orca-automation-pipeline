#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Job Management (Complete) - 22nd Century Programer Bot
- ORCAExecutor with subprocess
- Output parsing (normal termination, error patterns)
- opt -> freq chaining with geometry extraction
- Working/products directory management
"""

import re
import time
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict


class JobType:
    OPT = 'opt'
    FREQ = 'freq'

class JobStatus:
    WAITING = 'waiting'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'


@dataclass
class ORCAJob:
    inp_path: Path
    xyz_path: Path
    job_type: str
    job_id: Optional[str] = None
    status: str = JobStatus.WAITING
    work_dir: Optional[Path] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error_message: Optional[str] = None

    @property
    def weight(self) -> int:
        return 2 if self.job_type == JobType.OPT else 1


class ORCAExecutor:
    def __init__(self, orca_path: str):
        self.orca_path = orca_path

    def run(self, job: ORCAJob, work_dir: Path) -> bool:
        job.work_dir = work_dir
        job.start_time = time.time()
        job.status = JobStatus.RUNNING

        # Copy input files
        shutil.copy2(job.inp_path, work_dir)
        if job.xyz_path.exists():
            shutil.copy2(job.xyz_path, work_dir)

        cmd = [self.orca_path, job.inp_path.name]
        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=False
            )
            job.end_time = time.time()

            out_file = work_dir / f"{job.inp_path.stem}.out"
            if not out_file.exists():
                job.status = JobStatus.ERROR
                job.error_message = f"Output file not found: {out_file.name}\nSTDERR: {proc.stderr}"
                return False

            ok, err = self._parse_output(out_file)
            if ok:
                job.status = JobStatus.COMPLETED
                return True
            else:
                job.status = JobStatus.ERROR
                job.error_message = err or 'Unknown ORCA error'
                return False

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error_message = f"Execution exception: {e}"
            job.end_time = time.time()
            return False

    def _parse_output(self, out_path: Path) -> (bool, Optional[str]):
        content = out_path.read_text(encoding='utf-8', errors='ignore')
        if 'ORCA TERMINATED NORMALLY' in content:
            return True, None
        # Common error patterns
        patterns = [
            r'ERROR', r'Unknown key', r'UNKNOWN KEY', r'SCF NOT CONVERGED',
            r'CONVERGENCE NOT REACHED', r'OPTIMIZATION FAILED', r'ABORTING THE RUN'
        ]
        for pat in patterns:
            if re.search(pat, content, flags=re.IGNORECASE):
                return False, f"Detected error pattern: {pat}"
        return False, 'No normal termination marker found'

    def extract_final_xyz(self, out_path: Path) -> Optional[str]:
        """Extract final optimized coordinates as XYZ block"""
        try:
            text = out_path.read_text(encoding='utf-8', errors='ignore')
            # Heuristic: look for 'CARTESIAN COORDINATES (ANGSTROEM)' last block
            blocks = list(re.finditer(r'CARTESIAN COORDINATES \(ANGSTROEM\)([\s\S]*?)\n\s*\n', text))
            if not blocks:
                return None
            last = blocks[-1].group(1)
            lines = [ln for ln in last.strip().splitlines() if ln.strip()]
            # Filter header lines until atomic lines start (start with element symbol)
            coords = []
            for ln in lines:
                parts = ln.split()
                if len(parts) >= 4 and parts[0].isalpha():
                    try:
                        float(parts[-1])
                        coords.append(f"{parts[0]} {parts[-3]} {parts[-2]} {parts[-1]}")
                    except ValueError:
                        continue
            if not coords:
                return None
            return "\n".join(coords)
        except Exception:
            return None


class JobManager:
    def __init__(self, config):
        self.config = config
        self.job_queue = queue.Queue()
        self.running = {}
        self.completed = []
        self.max_parallel = int(config['orca']['max_parallel_jobs'])
        self.executor = ORCAExecutor(config['orca']['orca_path'])
        self.working_dir = Path(config['paths']['working_dir'])
        self.products_dir = Path(config['paths']['products_dir'])
        self.waiting_dir = Path(config['paths']['waiting_dir'])
        self._run = False
        self._lock = threading.Lock()

        # Ensure directories exist
        for p in [self.working_dir, self.products_dir, self.waiting_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def add_job(self, job: ORCAJob):
        print(f"[QUEUE] {job.job_type} -> {job.inp_path.name}")
        self.job_queue.put(job)

    def start(self):
        self._run = True
        for i in range(self.max_parallel):
            t = threading.Thread(target=self._worker, name=f"ORCA-{i+1}", daemon=True)
            t.start()
        print(f"[WORKERS] {self.max_parallel} workers up")

    def stop(self):
        self._run = False

    def get_weighted_task_count(self) -> int:
        total = 0
        # queued
        for j in list(self.job_queue.queue):
            total += j.weight
        # running
        with self._lock:
            for j in self.running.values():
                total += j.weight
        return total

    def _worker(self):
        while self._run:
            try:
                job: ORCAJob = self.job_queue.get(timeout=1.0)
                work_dir = self.working_dir / f"{job.inp_path.stem}_{job.job_type}_{int(time.time())}"
                work_dir.mkdir(parents=True, exist_ok=True)
                with self._lock:
                    self.running[work_dir.name] = job
                print(f"[EXEC] {job.job_type} {work_dir.name}")

                ok = self.executor.run(job, work_dir)

                with self._lock:
                    self.running.pop(work_dir.name, None)
                    self.completed.append(job)

                # Archive
                self._archive(work_dir, job)

                # Chain opt -> freq
                if ok and job.job_type == JobType.OPT:
                    out_path = self.products_dir / work_dir.name / f"{job.inp_path.stem}.out"
                    xyz_block = self.executor.extract_final_xyz(out_path)
                    if xyz_block:
                        freq_inp = self._make_freq_inp(job, xyz_block)
                        freq_inp_path = self.waiting_dir / f"{job.inp_path.stem}_freq.inp"
                        freq_inp_path.write_text(freq_inp)
                        freq_job = ORCAJob(inp_path=freq_inp_path, xyz_path=job.xyz_path, job_type=JobType.FREQ)
                        self.add_job(freq_job)

                self.job_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[WORKER ERROR] {e}")

    def _archive(self, work_dir: Path, job: ORCAJob):
        target = self.products_dir / work_dir.name
        target.mkdir(parents=True, exist_ok=True)
        for f in work_dir.iterdir():
            shutil.move(str(f), str(target / f.name))
        work_dir.rmdir()
        print(f"[ARCHIVE] -> {target}")

    def _make_freq_inp(self, opt_job: ORCAJob, xyz_block: str) -> str:
        method = self.config['orca']['method']
        basis = self.config['orca']['basis_set']
        charge = int(self.config['orca']['charge'])
        multiplicity = int(self.config['orca']['multiplicity'])
        nprocs = self.config['orca']['nprocs']
        maxcore = self.config['orca']['maxcore']
        lines = xyz_block.strip().splitlines()
        natoms = len(lines)
        coords = "\n".join(lines)
        return (
            f"! {method} {basis} Freq\n\n"
            f"%pal nprocs {nprocs} end\n"
            f"%maxcore {maxcore}\n\n"
            f"* xyz {charge} {multiplicity}\n"
            f"{coords}\n"
            f"*\n"
        )
