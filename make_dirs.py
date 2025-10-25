#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bootstrap script to create empty directory structure required by the pipeline.
This can be run safely multiple times.
"""

from pathlib import Path

DIRS = [
    'folders',
    'folders/input',
    'folders/waiting',
    'folders/working',
    'folders/products'
]

def main():
    for d in DIRS:
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"[OK] {d}/")

if __name__ == '__main__':
    main()
