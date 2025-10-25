#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe file reading utilities for ORCA outputs with recoverable vs fatal error classification.
"""

import time
from pathlib import Path
from typing import Optional, Tuple
import re


def safe_read_text(path: Path, max_attempts: int = 5, backoff_start: float = 0.1) -> Optional[str]:
    """Safely read text file with exponential backoff for file lock conflicts."""
    last_exception = None
    backoff = backoff_start
    
    for attempt in range(max_attempts):
        try:
            return path.read_text(encoding='utf-8', errors='ignore')
        except (PermissionError, OSError) as e:
            last_exception = e
            if attempt < max_attempts - 1:
                time.sleep(backoff)
                backoff *= 2
            continue
    
    print(f"[WARNING] Failed to read {path.name} after {max_attempts} attempts: {last_exception}")
    return None


def is_orca_definitely_complete(text: str) -> Tuple[bool, bool, bool, Optional[str]]:
    """Analyze ORCA output text for completion status with error classification.
    
    Returns:
        (is_complete, is_recoverable_error, is_fatal_error, error_reason)
        
    Logic:
    - is_complete=True, others=False: Normal termination detected
    - is_complete=True, is_fatal_error=True: Fatal error (stop pipeline)
    - is_complete=True, is_recoverable_error=True: Recoverable error (continue pipeline)
    - is_complete=False: Incomplete/interrupted (should requeue)
    """
    # First check for normal termination
    if 'ORCA TERMINATED NORMALLY' in text:
        return True, False, False, None
    
    # Fatal errors - require immediate pipeline stop and config fix
    fatal_patterns = [
        r'Unknown basis set', r'Unknown method', r'Unknown functional',
        r'Unknown key', r'Syntax error', r'Cannot find executable', 
        r'License error', r'Out of memory', r'Disk full', r'Permission denied',
        r'ABORTING THE RUN', r'FATAL ERROR'
    ]
    
    for pattern in fatal_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True, False, True, f"Fatal error: {pattern}"
    
    # Recoverable errors - system-specific issues, continue pipeline
    recoverable_patterns = [
        r'SCF NOT CONVERGED', r'CONVERGENCE NOT REACHED', r'OPTIMIZATION FAILED',
        r'GEOMETRY OPTIMIZATION FAILED', r'SYMMETRY PROBLEMS', r'ENERGY TOO HIGH',
        r'NEGATIVE FREQUENCIES', r'MAXIMUM NUMBER OF CYCLES REACHED',
        r'SCF CONVERGENCE FAILURE'
    ]
    
    for pattern in recoverable_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True, True, False, f"Recoverable error: {pattern}"
    
    # Generic ERROR that's not clearly classified - treat as recoverable by default
    if re.search(r'ERROR', text, flags=re.IGNORECASE):
        return True, True, False, "Generic error (assumed recoverable)"
    
    # No termination marker and no error pattern = incomplete/interrupted
    return False, False, False, "No termination marker found (likely interrupted)"
