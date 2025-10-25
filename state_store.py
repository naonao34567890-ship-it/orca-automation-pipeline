#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StateStore - crash-safe persistent job state for ORCA pipeline
Stores queue, running, and completed job states in JSON with atomic writes.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any


def _atomic_write(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return default


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.queue_path = root / 'queue.json'
        self.running_path = root / 'running.json'
        self.completed_path = root / 'completed.json'
        root.mkdir(parents=True, exist_ok=True)
        # initialize if missing
        for p, d in [
            (self.queue_path, []),
            (self.running_path, []),
            (self.completed_path, []),
        ]:
            if not p.exists():
                _atomic_write(p, d)

    # Queue operations
    def load_queue(self) -> List[Dict[str, Any]]:
        return _read_json(self.queue_path, [])

    def save_queue(self, items: List[Dict[str, Any]]):
        _atomic_write(self.queue_path, items)

    def enqueue(self, job: Dict[str, Any]):
        q = self.load_queue()
        # de-duplicate by job_id
        if all(j.get('job_id') != job.get('job_id') for j in q):
            q.append(job)
            self.save_queue(q)

    def dequeue(self, job_id: str):
        q = self.load_queue()
        q = [j for j in q if j.get('job_id') != job_id]
        self.save_queue(q)

    # Running operations
    def load_running(self) -> List[Dict[str, Any]]:
        return _read_json(self.running_path, [])

    def add_running(self, job: Dict[str, Any]):
        r = self.load_running()
        if all(j.get('job_id') != job.get('job_id') for j in r):
            r.append(job)
            _atomic_write(self.running_path, r)

    def remove_running(self, job_id: str):
        r = self.load_running()
        r = [j for j in r if j.get('job_id') != job_id]
        _atomic_write(self.running_path, r)

    # Completed operations
    def load_completed(self) -> List[Dict[str, Any]]:
        return _read_json(self.completed_path, [])

    def append_completed(self, job: Dict[str, Any]):
        c = self.load_completed()
        c.append(job)
        _atomic_write(self.completed_path, c)
