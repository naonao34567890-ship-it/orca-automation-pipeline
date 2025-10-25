#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility helpers for ORCA outputs: resolve primary output file and parse termination.
Updated with safe reading for concurrent .log file access.
"""

from pathlib import Path
from typing import Optional, Tuple
import re
from safe_file_utils import safe_read_text, is_orca_definitely_complete


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
    """Parse ORCA output text for completion/error status.
    
    Returns:
        (success, error_message)
        success=True: Normal termination
        success=False: Error or incomplete
    """
    is_complete, is_error, error_reason = is_orca_definitely_complete(text)
    
    if is_complete and not is_error:
        return True, None
    elif is_complete and is_error:
        return False, error_reason
    else:
        # Incomplete - should be requeued, not marked as permanent failure
        return False, f"Incomplete/interrupted: {error_reason}"


def safe_parse_orca_output(out_path: Path) -> Tuple[bool, Optional[str]]:
    """Safely read and parse ORCA output with retry logic.
    
    Returns:
        (success, error_message) 
    """
    text = safe_read_text(out_path)
    if text is None:
        return False, f"Could not read output file: {out_path.name}"
    
    return parse_normal_termination(text)