#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper functions for unique filenames and directories to avoid collisions.
"""
from pathlib import Path
import uuid


def unique_path(base: Path) -> Path:
    """Return a unique path by appending _1, _2, ... if needed."""
    p = base
    i = 1
    while p.exists():
        if base.suffix:
            p = base.with_name(f"{base.stem}_{i}{base.suffix}")
        else:
            p = base.with_name(f"{base.name}_{i}")
        i += 1
    return p


def unique_job_id(stem: str, job_type: str) -> str:
    """Create a unique job id using microtime + 6-char uuid fragment."""
    return f"{stem}_{job_type}_{uuid.uuid4().hex[:6]}"
