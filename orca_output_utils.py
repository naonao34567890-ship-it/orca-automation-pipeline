#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility helpers for ORCA outputs: resolve primary output file and parse termination.
"""

from pathlib import Path
from typing import Optional, Tuple
import re


def resolve_primary_output(work_dir: Path, stem: str) -> Optional[Path]:
    """Resolve ORCA primary textual output among common candidates.
    Order:
      1) {stem}.out
      2) {stem}_orca.log
      3) {stem}.log
      4) any *.out or *_orca.log in work_dir (first)
    """
    candidates = [
        work_dir / f"{stem}.out",
        work_dir / f"{stem}_orca.log",
        work_dir / f"{stem}.log",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback scan
    outs = list(work_dir.glob('*.out')) + list(work_dir.glob('*_orca.log')) + list(work_dir.glob('*.log'))
    return outs[0] if outs else None


def parse_normal_termination(text: str) -> Tuple[bool, Optional[str]]:
    if 'ORCA TERMINATED NORMALLY' in text:
        return True, None
    patterns = [
        r'ERROR', r'Unknown key', r'UNKNOWN KEY', r'SCF NOT CONVERGED',
        r'CONVERGENCE NOT REACHED', r'OPTIMIZATION FAILED', r'ABORTING THE RUN'
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return False, f"Detected error pattern: {pat}"
    return False, 'No normal termination marker found'
