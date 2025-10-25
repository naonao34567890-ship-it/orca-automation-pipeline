#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe file reading utilities for ORCA outputs that may be updated during execution.
"""

import time
from pathlib import Path
from typing import Optional, Tuple


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
    
    # All attempts failed
    print(f"[WARNING] Failed to read {path.name} after {max_attempts} attempts: {last_exception}")
    return None


def is_orca_definitely_complete(text: str) -> Tuple[bool, bool, Optional[str]]:
    """Analyze ORCA output text for completion status.
    
    Returns:
        (is_complete, is_error, error_reason)
        
    Logic:
    - is_complete=True, is_error=False: Normal termination detected
    - is_complete=True, is_error=True: Error detected (definitive failure) 
    - is_complete=False, is_error=False: Incomplete/interrupted (should requeue)
    """
    # First check for normal termination
    if 'ORCA TERMINATED NORMALLY' in text:
        return True, False, None
    
    # Check for definitive error patterns
    error_patterns = [
        r'ERROR', r'Unknown key', r'UNKNOWN KEY', r'SCF NOT CONVERGED',
        r'CONVERGENCE NOT REACHED', r'OPTIMIZATION FAILED', r'ABORTING THE RUN',
        r'FATAL ERROR', r'TERMINATING', r'ABNORMAL TERMINATION'
    ]
    
    for pattern in error_patterns:
        import re
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True, True, f"Detected error pattern: {pattern}"
    
    # No termination marker and no error pattern = incomplete/interrupted
    return False, False, "No termination marker found (likely interrupted)"
