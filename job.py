#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Job Management (Crash-safe + logging) - add unique job_id, archive dir, freq inp path
"""

import re
import os
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
from orca_output_utils import resolve_primary_output, parse_normal_termination
from path_utils import unique_path, unique_job_id

log = get_logger("jobs")

# ... (unchanged imports and class definitions above)

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

# ... ORCAExecutor unchanged ...

class JobManager:
    def __init__(self, config):
        # ... unchanged init ...
        for p in [self.working_dir, self.products_dir, self.waiting_dir, self.state_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def add_job(self, job: ORCAJob):
        if job.job_id is None:
            job.job_id = unique_job_id(job.inp_path.stem, job.job_type)
        self.state.enqueue(job.to_dict())
        self.job_queue.put(job)
        log.info(f"QUEUE add {job.job_id} ({job.job_type})")

    def _worker(self):
        while self._run:
            try:
                job: ORCAJob = self.job_queue.get(timeout=1.0)
                work_dir = self.working_dir / f"{job.inp_path.stem}_{job.job_type}_{int(time.time())}"
                work_dir = unique_path(work_dir)
                work_dir.mkdir(parents=True, exist_ok=True)
                with self._lock:
                    self.running[work_dir.name] = job
                self.state.dequeue(job.job_id)
                rj = job.to_dict(); rj['work_dir'] = str(work_dir)
                self.state.add_running(rj)

                log.info(f"EXEC dispatch {job.job_id} -> {work_dir.name}")
                ok = self.executor.run(job, work_dir)

                with self._lock:
                    self.running.pop(work_dir.name, None)
                    self.completed.append(job)

                self.state.remove_running(job.job_id)
                if ok:
                    self.state.append_completed(job.to_dict())
                    log.info(f"DONE {job.job_id}")
                else:
                    if job.retries < self.max_retries:
                        job.retries += 1
                        log.warning(f"RETRY {job.job_id} ({job.retries}/{self.max_retries})")
                        self.add_job(job)
                    else:
                        from notifier import NotificationSystem
                        NotificationSystem.send_error(f"Job failed after retries: {job.job_id}\n{job.error_message}")
                        self.state.append_completed(job.to_dict())
                        log.error(f"FAIL {job.job_id}: {job.error_message}")

                self._archive(work_dir, job)

                if ok and job.job_type == JobType.OPT:
                    out_path = resolve_primary_output(self.products_dir / work_dir.name, job.inp_path.stem)
                    xyz_block = self.executor.extract_final_xyz(out_path) if out_path else None
                    if xyz_block:
                        freq_inp = self._make_freq_inp(job, xyz_block)
                        freq_inp_path = unique_path(self.waiting_dir / f"{job.inp_path.stem}_freq.inp")
                        freq_inp_path.write_text(freq_inp)
                        freq_job = ORCAJob(inp_path=freq_inp_path, xyz_path=job.xyz_path, job_type=JobType.FREQ)
                        self.add_job(freq_job)
                        log.info(f"CHAIN {job.job_id} -> {freq_job.job_id}")

                self.job_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                log.exception(f"WORKER error: {e}")

    def _archive(self, work_dir: Path, job: ORCAJob):
        target = unique_path(self.products_dir / work_dir.name)
        target.mkdir(parents=True, exist_ok=True)
        for f in work_dir.iterdir():
            shutil.move(str(f), str(target / f.name))
        work_dir.rmdir()
        log.info(f"ARCHIVE {job.job_id} -> {target.name}")

    def _recover_on_start(self):
        # ... unchanged, recovery logs preserved ...
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
                archived = self.products_dir / (wd.name if wd else '')
                if archived.exists():
                    out_path = resolve_primary_output(archived, j.inp_path.stem)
            if out_path and out_path.exists():
                ok, _ = parse_normal_termination(out_path.read_text(encoding='utf-8', errors='ignore'))
                target = unique_path(self.products_dir / (wd.name if wd else out_path.parent.name))
                if wd and wd.exists() and not target.exists():
                    target.mkdir(parents=True, exist_ok=True)
                    for f in wd.iterdir():
                        shutil.move(str(f), str(target / f.name))
                    wd.rmdir()
                self.state.remove_running(j.job_id)
                if ok:
                    self.state.append_completed(j.to_dict())
                    log.info(f"RECOVER running(ok)->completed {j.job_id}")
                else:
                    j.status = JobStatus.WAITING
                    self.state.enqueue(j.to_dict())
                    self.job_queue.put(j)
                    log.warning(f"RECOVER running(failed)->requeue {j.job_id}")
            else:
                j.status = JobStatus.WAITING
                self.state.enqueue(j.to_dict())
                self.job_queue.put(j)
                self.state.remove_running(j.job_id)
                log.warning(f"RECOVER running(incomplete)->requeue {j.job_id}")
        for inp in self.waiting_dir.glob('*.inp'):
            xyz = self.waiting_dir / (inp.stem.replace('_freq','') + '.xyz')
            job_type = JobType.FREQ if inp.stem.endswith('_freq') else JobType.OPT
            # ensure unique in-place path reference
            unique_inp = unique_path(inp)
            if unique_inp != inp:
                inp.rename(unique_inp)
                inp = unique_inp
            job = ORCAJob(inp_path=inp, xyz_path=xyz if xyz.exists() else Path(''), job_type=job_type)
            self.add_job(job)
            log.info(f"RECOVER waiting->enqueue {inp.name}")
        log.info("RECOVER end")
