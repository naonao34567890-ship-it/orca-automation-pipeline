#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Job Management with recoverable/fatal error handling, energy plots, and system grouping
"""

import time
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict

from state_store import StateStore
from logging_setup import get_logger
from orca_output_utils import resolve_primary_output, safe_parse_orca_output
from path_utils import unique_path, unique_job_id
from energy_plot_utils import create_energy_plot_from_output

log = get_logger("jobs")


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

    def run(self, job: ORCAJob, work_dir: Path) -> tuple[bool, bool, bool]:  # (success, is_recoverable, is_fatal)
        job.work_dir = work_dir
        job.start_time = time.time()
        job.status = JobStatus.RUNNING

        lock_path = work_dir / '.lock'
        lock_path.write_text('running', encoding='utf-8')

        shutil.copy2(job.inp_path, work_dir)
        if job.xyz_path.exists():
            shutil.copy2(job.xyz_path, work_dir)

        cmd = [self.orca_path, job.inp_path.name]
        log.info(f"EXEC start {job.job_id} in {work_dir.name}: {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                check=False
            )
            job.end_time = time.time()

            out_path = resolve_primary_output(work_dir, job.inp_path.stem)
            if not out_path or not out_path.exists():
                job.status = JobStatus.ERROR
                job.error_message = f"Primary output not found (searched .out/_orca.log/.log). STDERR: {proc.stderr[:500]}"
                log.error(f"EXEC fail {job.job_id}: {job.error_message}")
                return False, False, True  # No output = fatal

            success, is_recoverable, is_fatal, err = safe_parse_orca_output(out_path)
            if success:
                job.status = JobStatus.COMPLETED
                log.info(f"EXEC ok {job.job_id} output={out_path.name} duration={job.end_time-job.start_time:.1f}s")
                return True, False, False
            elif is_fatal:
                job.status = JobStatus.ERROR
                job.error_message = err or 'Fatal ORCA error'
                log.error(f"EXEC fatal {job.job_id}: {job.error_message} (output={out_path.name})")
                return False, False, True
            elif is_recoverable:
                job.status = JobStatus.ERROR
                job.error_message = err or 'Recoverable ORCA error'
                log.warning(f"EXEC recoverable {job.job_id}: {job.error_message} (output={out_path.name})")
                return False, True, False
            else:
                # Incomplete
                job.status = JobStatus.ERROR
                job.error_message = err or 'Incomplete execution'
                log.warning(f"EXEC incomplete {job.job_id}: {job.error_message}")
                return False, False, False

        except Exception as e:
            job.status = JobStatus.ERROR
            job.error_message = f"Execution exception: {e}"
            job.end_time = time.time()
            log.exception(f"EXEC exception {job.job_id}: {e}")
            return False, False, True  # Exception = fatal
        finally:
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass

    def extract_final_xyz(self, out_path: Path) -> Optional[str]:
        try:
            text = out_path.read_text(encoding='utf-8', errors='ignore')
            import re
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
        self._fatal_error_occurred = False

        for p in [self.working_dir, self.products_dir, self.waiting_dir, self.state_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def add_job(self, job: ORCAJob):
        if job.job_id is None:
            job.job_id = unique_job_id(job.inp_path.stem, job.job_type)
        self.state.enqueue(job.to_dict())
        self.job_queue.put(job)
        log.info(f"QUEUE add {job.job_id} ({job.job_type})")

    def start(self):
        self._run = True
        self._recover_on_start()
        for i in range(self.max_parallel):
            t = threading.Thread(target=self._worker, name=f"ORCA-{i+1}", daemon=True)
            t.start()
        log.info(f"WORKERS started: {self.max_parallel}")

    def stop(self):
        self._run = False
        log.info("WORKERS stop requested")

    def has_fatal_error(self) -> bool:
        return self._fatal_error_occurred

    def get_weighted_task_count(self) -> int:
        total = 0
        for j in list(self.job_queue.queue):
            total += j.weight
        with self._lock:
            for j in self.running.values():
                total += j.weight
        return total

    def _molecule_name(self, stem: str) -> str:
        if stem.endswith('_opt'):
            return stem[:-4]
        if stem.endswith('_freq'):
            return stem[:-5]
        return stem

    def _archive(self, work_dir: Path, job: ORCAJob, success: bool, is_recoverable: bool, is_fatal: bool):
        stem = job.inp_path.stem
        mol = self._molecule_name(stem)
        
        # Determine folder name based on result
        if success:
            job_folder = f"{job.job_type}_success_{int(time.time())}"
        elif is_fatal:
            job_folder = f"{job.job_type}_fatal_{int(time.time())}"
        else:
            job_folder = f"{job.job_type}_failed_{int(time.time())}"
        
        base_target = self.products_dir / mol / job_folder
        target = unique_path(base_target)
        target.mkdir(parents=True, exist_ok=True)
        
        for f in work_dir.iterdir():
            shutil.move(str(f), str(target / f.name))
        work_dir.rmdir()
        log.info(f"ARCHIVE {job.job_id} -> {target.relative_to(self.products_dir)}")

        # Generate additional outputs for successful and recoverable failures
        if success or is_recoverable:
            self._generate_auxiliary_outputs(target, mol, job.job_type)

    def _generate_auxiliary_outputs(self, target_dir: Path, molecule_name: str, job_type: str):
        # Generate Molden if enabled
        try:
            gen_molden = self.config['orca'].getboolean('generate_molden', fallback=True)
        except Exception:
            gen_molden = True
        
        if gen_molden:
            gbws = list(target_dir.glob('*.gbw'))
            if gbws:
                orca_2mkl = self.config['orca'].get('orca_2mkl_path', 'orca_2mkl')
                base = gbws[0].with_suffix('')
                cmd = [orca_2mkl, str(base), '-molden']
                try:
                    subprocess.run(cmd, cwd=target_dir, check=False, capture_output=True)
                    log.info(f"MOLDEN generated for {gbws[0].name}")
                except Exception as e:
                    log.warning(f"MOLDEN generation failed: {e}")
        
        # Generate energy trajectory plot
        out_path = resolve_primary_output(target_dir, molecule_name)
        if out_path:
            plot_path = target_dir / f"{molecule_name}_{job_type}_energy.png"
            try:
                if create_energy_plot_from_output(out_path, plot_path, molecule_name, job_type):
                    log.info(f"ENERGY PLOT generated: {plot_path.name}")
                else:
                    log.info(f"ENERGY PLOT skipped (no data): {molecule_name}_{job_type}")
            except Exception as e:
                log.warning(f"ENERGY PLOT generation failed: {e}")

    def _worker(self):
        while self._run and not self._fatal_error_occurred:
            try:
                job: ORCAJob = self.job_queue.get(timeout=1.0)
                work_dir = unique_path(self.working_dir / f"{job.inp_path.stem}_{job.job_type}_{int(time.time())}")
                work_dir.mkdir(parents=True, exist_ok=True)
                
                with self._lock:
                    self.running[work_dir.name] = job
                self.state.dequeue(job.job_id)
                rj = job.to_dict(); rj['work_dir'] = str(work_dir)
                self.state.add_running(rj)

                log.info(f"EXEC dispatch {job.job_id} -> {work_dir.name}")
                success, is_recoverable, is_fatal = self.executor.run(job, work_dir)

                with self._lock:
                    self.running.pop(work_dir.name, None)
                    self.completed.append(job)

                self.state.remove_running(job.job_id)
                
                if is_fatal:
                    # Fatal error - stop pipeline
                    self._fatal_error_occurred = True
                    from notifier import NotificationSystem
                    NotificationSystem.send_error(f"FATAL ERROR - Pipeline stopped: {job.job_id}\n{job.error_message}")
                    log.error(f"FATAL {job.job_id}: {job.error_message} - STOPPING PIPELINE")
                    self.state.append_completed(job.to_dict())
                    self._archive(work_dir, job, False, False, True)
                    return  # Exit worker thread
                
                elif success:
                    self.state.append_completed(job.to_dict())
                    log.info(f"SUCCESS {job.job_id}")
                    self._archive(work_dir, job, True, False, False)
                    
                    # Chain opt -> freq if successful
                    if job.job_type == JobType.OPT:
                        self._chain_frequency_calculation(job)
                
                elif is_recoverable:
                    # Recoverable error - archive as failed but continue pipeline
                    self.state.append_completed(job.to_dict())
                    log.warning(f"RECOVERABLE_FAIL {job.job_id}: {job.error_message}")
                    self._archive(work_dir, job, False, True, False)
                
                else:
                    # Incomplete - retry if possible
                    if job.retries < self.max_retries:
                        job.retries += 1
                        log.warning(f"RETRY {job.job_id} ({job.retries}/{self.max_retries})")
                        self.add_job(job)
                        self._archive(work_dir, job, False, False, False)  # Archive attempt
                    else:
                        # Max retries reached - treat as recoverable failure
                        self.state.append_completed(job.to_dict())
                        log.warning(f"MAX_RETRY_FAIL {job.job_id}: {job.error_message}")
                        self._archive(work_dir, job, False, True, False)

                self.job_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                log.exception(f"WORKER error: {e}")

    def _chain_frequency_calculation(self, opt_job: ORCAJob):
        """Chain frequency calculation after successful optimization."""
        try:
            mol = self._molecule_name(opt_job.inp_path.stem)
            mol_dir = self.products_dir / mol
            if mol_dir.exists():
                subdirs = [d for d in mol_dir.iterdir() if d.is_dir() and 'success' in d.name and 'opt' in d.name]
                if subdirs:
                    latest_opt = max(subdirs, key=lambda d: d.stat().st_mtime)
                    out_path = resolve_primary_output(latest_opt, mol)
                    if out_path:
                        xyz_block = self.executor.extract_final_xyz(out_path)
                        if xyz_block:
                            freq_inp_path = unique_path(self.waiting_dir / f"{mol}_freq.inp")
                            freq_inp_path.write_text(self._make_freq_inp(opt_job, xyz_block))
                            freq_job = ORCAJob(inp_path=freq_inp_path, xyz_path=opt_job.xyz_path, job_type=JobType.FREQ)
                            self.add_job(freq_job)
                            log.info(f"CHAIN {opt_job.job_id} -> {freq_job.job_id}")
        except Exception as e:
            log.warning(f"CHAIN failed for {opt_job.job_id}: {e}")

    def _make_freq_inp(self, opt_job: ORCAJob, xyz_block: str) -> str:
        method = self.config['orca']['method']
        basis = self.config['orca']['basis_set']
        charge = int(self.config['orca']['charge'])
        multiplicity = int(self.config['orca']['multiplicity'])
        nprocs = self.config['orca']['nprocs']
        maxcore = self.config['orca']['maxcore']
        solvent_model = self.config['orca'].get('solvent_model', 'none').strip().lower()
        solvent_name = self.config['orca'].get('solvent_name', 'water').strip()
        extra_keywords = self.config['orca'].get('extra_keywords', '').strip()
        solvent_kw = ''
        if solvent_model != 'none' and solvent_model.upper() in ['CPCM','SMD','COSMO']:
            solvent_kw = f" {solvent_model.upper()}(Solvent={solvent_name.capitalize()})"
        first = f"! {method} {basis} Freq{solvent_kw}"
        if extra_keywords:
            first += f" {extra_keywords}"
        return (
            f"{first}\n\n"
            f"%pal nprocs {nprocs} end\n"
            f"%maxcore {maxcore}\n\n"
            f"* xyz {charge} {multiplicity}\n"
            f"{xyz_block}\n"
            f"*\n"
        )

    def _recover_on_start(self):
        log.info("RECOVER begin")
        queued = [ORCAJob.from_dict(j) for j in self.state.load_queue()]
        for j in queued:
            self.job_queue.put(j)
            log.info(f"RECOVER queue->requeue {j.job_id}")
        
        running = [ORCAJob.from_dict(j) for j in self.state.load_running()]
        for j in running:
            wd = Path(j.work_dir) if j.work_dir else None
            out_path = None
            if wd and wd.exists():
                out_path = resolve_primary_output(wd, j.inp_path.stem)
            if not out_path:
                mol = self._molecule_name(j.inp_path.stem)
                mol_dir = self.products_dir / mol
                if mol_dir.exists():
                    subdirs = [d for d in mol_dir.iterdir() if d.is_dir()]
                    if subdirs:
                        last_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
                        out_path = resolve_primary_output(last_dir, j.inp_path.stem)
            
            if out_path and out_path.exists():
                success, is_recoverable, is_fatal, err = safe_parse_orca_output(out_path)
                self.state.remove_running(j.job_id)
                if success:
                    self.state.append_completed(j.to_dict())
                    log.info(f"RECOVER running(ok)->completed {j.job_id}")
                elif is_fatal:
                    self.state.append_completed(j.to_dict())
                    log.error(f"RECOVER running(fatal)->completed {j.job_id}")
                else:
                    j.status = JobStatus.WAITING
                    self.state.enqueue(j.to_dict())
                    self.job_queue.put(j)
                    log.warning(f"RECOVER running({err or 'incomplete'})->requeue {j.job_id}")
            else:
                j.status = JobStatus.WAITING
                self.state.enqueue(j.to_dict())
                self.job_queue.put(j)
                self.state.remove_running(j.job_id)
                log.warning(f"RECOVER running(incomplete)->requeue {j.job_id}")
        
        for inp in self.waiting_dir.glob('*.inp'):
            xyz = self.waiting_dir / (inp.stem.replace('_freq','') + '.xyz')
            job_type = JobType.FREQ if inp.stem.endswith('_freq') else JobType.OPT
            unique_inp = unique_path(inp)
            if unique_inp != inp:
                inp.rename(unique_inp)
                inp = unique_inp
            job = ORCAJob(inp_path=inp, xyz_path=xyz if xyz.exists() else Path(''), job_type=job_type)
            self.add_job(job)
            log.info(f"RECOVER waiting->enqueue {inp.name}")
        log.info("RECOVER end")
