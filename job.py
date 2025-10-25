import os
import time
import queue
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class JobType(Enum):
    OPT = "opt"
    FREQ = "freq"


class JobStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running" 
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ORCAJob:
    inp_path: Path
    xyz_path: Path
    job_type: str
    job_id: Optional[str] = None
    status: JobStatus = JobStatus.WAITING
    
    def __post_init__(self):
        if self.job_id is None:
            timestamp = int(time.time() * 1000)
            self.job_id = f"{self.inp_path.stem}_{self.job_type}_{timestamp}"
    
    @property
    def weight(self) -> int:
        return 2 if self.job_type == "opt" else 1


class JobManager:
    def __init__(self, config):
        self.config = config
        self.job_queue = queue.Queue()
        self.running_jobs = {}
        self.completed_jobs = []
        self.max_parallel = int(config['orca']['max_parallel_jobs'])
        self._running = False
        self._lock = threading.Lock()
        
    def add_job(self, job):
        print(f"[QUEUE] Added {job.job_type} job: {job.job_id}")
        self.job_queue.put(job)
    
    def start(self):
        self._running = True
        for i in range(self.max_parallel):
            worker = threading.Thread(
                target=self._worker_loop,
                daemon=True
            )
            worker.start()
        print(f"[WORKERS] Started {self.max_parallel} workers")
    
    def stop(self):
        self._running = False
    
    def get_weighted_task_count(self):
        total = 0
        for job in list(self.job_queue.queue):
            total += job.weight
        return total
    
    def _worker_loop(self):
        while self._running:
            try:
                job = self.job_queue.get(timeout=1.0)
                print(f"[EXEC] Processing {job.job_type}: {job.job_id}")
                time.sleep(5)  # Simulate execution
                self.job_queue.task_done()
            except queue.Empty:
                continue
