#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Automation Pipeline - Main Controller
22nd Century Programer Bot

Features:
- Real-time XYZ file monitoring with watchdog
- Automatic INP generation with ORCA compliance
- 5-job parallel execution with threading
- Weighted task notification system
- Gmail/Sound/Popup unified notifications
"""

import os
import sys
import time
import queue
import threading
import configparser
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from job import ORCAJob, JobManager
from notifier import NotificationSystem


class XYZHandler(FileSystemEventHandler):
    """File watcher for XYZ files in input folder"""
    
    def __init__(self, job_manager, config):
        self.job_manager = job_manager
        self.config = config
        self.input_dir = Path(config['paths']['input_dir'])
        self.waiting_dir = Path(config['paths']['waiting_dir'])
        
    def on_created(self, event):
        """Handle new XYZ file detection"""
        if not event.is_dir and event.src_path.endswith('.xyz'):
            xyz_path = Path(event.src_path)
            print(f"[DETECT] New XYZ file: {xyz_path.name}")
            
            # Generate INP from XYZ
            try:
                inp_content = self._generate_inp_from_xyz(xyz_path)
                inp_path = xyz_path.with_suffix('.inp')
                
                # Write INP file
                with open(inp_path, 'w') as f:
                    f.write(inp_content)
                
                # Move both files to waiting directory
                self._move_to_waiting(xyz_path, inp_path)
                
                # Add optimization job to queue
                job = ORCAJob(
                    inp_path=self.waiting_dir / inp_path.name,
                    xyz_path=self.waiting_dir / xyz_path.name,
                    job_type='opt'
                )
                self.job_manager.add_job(job)
                
            except Exception as e:
                print(f"[ERROR] Failed to process {xyz_path.name}: {e}")
                NotificationSystem.send_error(f"INP generation failed: {xyz_path.name}\nError: {e}")
    
    def _generate_inp_from_xyz(self, xyz_path):
        """Generate ORCA INP content from XYZ file"""
        # Read XYZ coordinates
        with open(xyz_path, 'r') as f:
            lines = f.readlines()
        
        # Parse XYZ format
        num_atoms = int(lines[0].strip())
        comment = lines[1].strip()
        coords = []
        
        for i in range(2, 2 + num_atoms):
            parts = lines[i].strip().split()
            element = parts[0]
            x, y, z = map(float, parts[1:4])
            coords.append(f"{element:>2} {x:>12.6f} {y:>12.6f} {z:>12.6f}")
        
        # Generate INP content
        method = self.config['orca']['method']
        basis = self.config['orca']['basis_set']
        charge = int(self.config['orca']['charge'])
        multiplicity = int(self.config['orca']['multiplicity'])
        
        inp_content = f"""! {method} {basis} Opt

%pal nprocs {self.config['orca']['nprocs']} end
%maxcore {self.config['orca']['maxcore']}

* xyz {charge} {multiplicity}
"""
        
        for coord_line in coords:
            inp_content += coord_line + "\n"
        
        inp_content += "*\n"
        return inp_content
    
    def _move_to_waiting(self, xyz_path, inp_path):
        """Move XYZ and INP files to waiting directory"""
        import shutil
        
        # Ensure waiting directory exists
        self.waiting_dir.mkdir(parents=True, exist_ok=True)
        
        # Move files
        shutil.move(str(xyz_path), str(self.waiting_dir / xyz_path.name))
        shutil.move(str(inp_path), str(self.waiting_dir / inp_path.name))
        
        print(f"[MOVE] Files moved to waiting: {xyz_path.name}, {inp_path.name}")


class ORCAPipeline:
    """Main ORCA automation pipeline controller"""
    
    def __init__(self, config_path='config.txt'):
        self.config = self._load_config(config_path)
        self._setup_directories()
        
        # Initialize components
        self.job_manager = JobManager(self.config)
        self.notification_system = NotificationSystem(self.config)
        
        # Setup file watcher
        self.observer = Observer()
        self.xyz_handler = XYZHandler(self.job_manager, self.config)
        
    def _load_config(self, config_path):
        """Load configuration from file"""
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        return config
    
    def _setup_directories(self):
        """Create required directory structure"""
        dirs = [
            'folders/input',
            'folders/waiting', 
            'folders/working',
            'folders/products'
        ]
        
        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            print(f"[SETUP] Directory ready: {dir_path}")
    
    def start(self):
        """Start the automation pipeline"""
        print("[START] ORCA Automation Pipeline - 22nd Century Mode")
        print("=" * 50)
        
        # Start file monitoring
        input_dir = self.config['paths']['input_dir']
        self.observer.schedule(self.xyz_handler, input_dir, recursive=False)
        self.observer.start()
        
        # Start job manager
        self.job_manager.start()
        
        # Start notification monitoring
        self.notification_system.start_monitoring(self.job_manager)
        
        print(f"[MONITOR] Watching for XYZ files in: {input_dir}")
        print(f"[PARALLEL] Maximum concurrent ORCA jobs: {self.config['orca']['max_parallel_jobs']}")
        print("[READY] Pipeline is running. Press Ctrl+C to stop.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop the automation pipeline"""
        print("\n[STOP] Shutting down pipeline...")
        
        self.observer.stop()
        self.observer.join()
        
        self.job_manager.stop()
        self.notification_system.stop()
        
        print("[EXIT] Pipeline stopped successfully.")


if __name__ == "__main__":
    pipeline = ORCAPipeline()
    pipeline.start()
