#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Central logging setup for ORCA Automation Pipeline.
- Rotating file logs
- Console logs
- Per-run log directory under folders/logs/
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time


def get_logger(name: str = "orca") -> logging.Logger:
    logs_root = Path('folders/logs')
    logs_root.mkdir(parents=True, exist_ok=True)
    # Per-day rolling file
    log_file = logs_root / 'pipeline.log'

    logger = logging.getLogger(name)
    if getattr(logger, "_orca_configured", False):
        return logger

    logger.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

    # Rotating file handler (5 MB x 5 files)
    fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger._orca_configured = True

    logger.info('Logging initialized')
    return logger
