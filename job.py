#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Job Management (Crash-safe) - adds state persistence, lock files, and recovery
"""

import re
import os
import json
import time
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict

from state_store import StateStore


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
    retries: int = 0

    @property
    def weight(self) -> int:
        return 2 if self.job_type == JobType.OPT else 1

    def to_dict(self) -> Dict:
        d = asdict(self)
        # Serialize Paths to strings
        for k in ['inp_path', 'xyz_path', 'work_dir']:
            if d.get(k) is not None:
                d[k] = str(d[k])
        return d

    @staticmethod
    def from_dict(d: Dict):
        return ORCAJob(
            inp_path=Path(d['inp_path']),
            xyz_path=Path(d['xyz_path']),
            job_type=d['job_type'],
            job_id=d.get('job_id'),
            status=d.get('status', JobStatus.WAITING),
            work_dir=Path(d['work_dir']) if d.get('work_dir') else None,
            start_time=d.get('start_time'),
            end_time=d.get('end_time'),
            error_message=d.get('error_message'),
            retries=int(d.get('retries', 0))
        )


class ORCAExecutor:
    def __init__(self, orca_path: str):
        self.orca_path = orca_path

    def run(self, job: ORCAJob, work_dir: Path) -> bool:
        job.work_dir = work_dir
        job.start_time = time.time()
        job.status = JobStatus.RUNNING

        # Create lock file to mark running
        lock_path = work_dir / '.lock'
        lock_path.write_text('running', encoding='utf-8')

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
        finally:
            # Remove lock if exists
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass

    def _parse_output(self, out_path: Path) -> (bool, Optional[str]):
        content = out_path.read_text(encoding='utf-8', errors='ignore')
        if 'ORCA TERMINATED NORMALLY' in content:
            return True, None
        patterns = [
            r'ERROR', r'Unknown key', r'UNKNOWN KEY', r'SCF NOT CONVERGED',
            r'CONVERGENCE NOT REACHED', r'OPTIMIZATION FAILED', r'ABORTING THE RUN'
        ]
        for pat in patterns:
            if re.search(pat, content, flags=re.IGNORECASE):
                return False, f"Detected error pattern: {pat}"
        return False, 'No normal termination marker found'

    def extract_final_xyz(self, out_path: Path) -> Optional[str]:
        try:
            text = out_path.read_text(encoding='utf-8', errors='ignore')
            blocks = list(re.finditer(r'CARTESIAN COORDINATES \(ANGSTROEM\)([\s\S]*?)\n\s*\n', text))
            if not blocks:
                return None
            last = blocks[-1].group(1)
            lines = [ln for ln in last.strip().splitlines() if ln.strip()]
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
        self.max_retries = int(config['orca'].get('max_retries', 2))
        self.executor = ORCAExecutor(config['orca']['orca_path'])
        self.working_dir = Path(config['paths']['working_dir'])
        self.products_dir = Path(config['paths']['products_dir'])
        self.waiting_dir = Path(config['paths']['waiting_dir'])
        self.state_dir = Path('folders/state')
        self.state = StateStore(self.state_dir)
        self._run = False
        self._lock = threading.Lock()

        for p in [self.working_dir, self.products_dir, self.waiting_dir, self.state_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def add_job(self, job: ORCAJob):
        if job.job_id is None:
            job.job_id = f"{job.inp_path.stem}_{job.job_type}_{int(time.time()*1000)}"
        print(f"[QUEUE] {job.job_type} -> {job.inp_path.name}")
        self.state.enqueue(job.to_dict())
        self.job_queue.put(job)

    def start(self):
        self._run = True
        self._recover_on_start()
        for i in range(self.max_parallel):
            t = threading.Thread(target=self._worker, name=f"ORCA-{i+1}", daemon=True)
            t.start()
        print(f"[WORKERS] {self.max_parallel} workers up")

    def stop(self):
        self._run = False

    def get_weighted_task_count(self) -> int:
        total = 0
        for j in list(self.job_queue.queue):
            total += j.weight
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
                # move state: queue -> running
                self.state.dequeue(job.job_id)
                rj = job.to_dict(); rj['work_dir'] = str(work_dir)
                self.state.add_running(rj)

                print(f"[EXEC] {job.job_type} {work_dir.name}")
                ok = self.executor.run(job, work_dir)

                with self._lock:
                    self.running.pop(work_dir.name, None)
                    self.completed.append(job)

                # running -> completed or retry
                self.state.remove_running(job.job_id)
                if ok:
                    self.state.append_completed(job.to_dict())
                else:
                    if job.retries < self.max_retries:
                        job.retries += 1
                        print(f"[RETRY] {job.job_id} ({job.retries}/{self.max_retries})")
                        self.add_job(job)
                    else:
                        from notifier import NotificationSystem
                        NotificationSystem.send_error(f"Job failed after retries: {job.job_id}\n{job.error_message}")
                        self.state.append_completed(job.to_dict())

                self._archive(work_dir, job)

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
        # solvent/extras from config
        solvent_model = self.config['orca'].get('solvent_model', 'none').strip().lower()
        solvent_name = self.config['orca'].get('solvent_name', 'water').strip()
        extra_keywords = self.config['orca'].get('extra_keywords', '').strip()
        solvent_kw = ''
        if solvent_model != 'none' and solvent_model.upper() in ['CPCM','SMD','COSMO']:
            solvent_kw = f" {solvent_model.upper()}(Solvent={solvent_name.capitalize()})"
        first = f"! {method} {basis} Freq{solvent_kw}"
        if extra_keywords:
            first += f" {extra_keywords}"
        lines = xyz_block.strip().splitlines()
        coords = "\n".join(lines)
        return (
            f"{first}\n\n"
            f"%pal nprocs {nprocs} end\n"
            f"%maxcore {maxcore}\n\n"
            f"* xyz {charge} {multiplicity}\n"
            f"{coords}\n"
            f"*\n"
        )

    def _recover_on_start(self):
        print("[RECOVER] Starting recovery...")
        # 1) Re-queue queued jobs from state
        queued = [ORCAJob.from_dict(j) for j in self.state.load_queue()]
        for j in queued:
            print(f"[RECOVER] queued -> requeue {j.job_id}")
            self.job_queue.put(j)
        # 2) Handle running jobs
        running = [ORCAJob.from_dict(j) for j in self.state.load_running()]
        for j in running:
            wd = Path(j.work_dir) if j.work_dir else None
            if wd and (wd / f"{j.inp_path.stem}.out").exists():
                ok, _ = ORCAExecutor(self.config['orca']['orca_path'])._parse_output(wd / f"{j.inp_path.stem}.out")
                # archive into products if not yet
                target = self.products_dir / wd.name
                if not target.exists() and wd.exists():
                    target.mkdir(parents=True, exist_ok=True)
                    for f in wd.iterdir():
                        shutil.move(str(f), str(target / f.name))
                    wd.rmdir()
                # finalize state
                self.state.remove_running(j.job_id)
                if ok:
                    print(f"[RECOVER] running(ok) -> completed {j.job_id}")
                    self.state.append_completed(j.to_dict())
                else:
                    print(f"[RECOVER] running(failed) -> requeue {j.job_id}")
                    j.status = JobStatus.WAITING
                    self.state.enqueue(j.to_dict())
                    self.job_queue.put(j)
            else:
                # No output -> incomplete, requeue
                print(f"[RECOVER] running(incomplete) -> requeue {j.job_id}")
                j.status = JobStatus.WAITING
                self.state.enqueue(j.to_dict())
                self.job_queue.put(j)
                self.state.remove_running(j.job_id)
        # 3) Scan waiting dir for orphan inputs
        for inp in self.waiting_dir.glob('*.inp'):
            xyz = self.waiting_dir / (inp.stem.replace('_freq','') + '.xyz')
            job_type = JobType.FREQ if inp.stem.endswith('_freq') else JobType.OPT
            job = ORCAJob(inp_path=inp, xyz_path=xyz if xyz.exists() else Path(''), job_type=job_type)
            print(f"[RECOVER] waiting -> enqueue {inp.name}")
            self.add_job(job)
        print("[RECOVER] Done")
