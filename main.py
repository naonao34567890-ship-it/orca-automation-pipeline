#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Automation Pipeline - Main Controller with robust XYZ parsing, fatal stop, and watchdog API fix
"""

import time
import configparser
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from job import ORCAJob, JobManager
from notifier import NotificationSystem
from logging_setup import get_logger
from path_utils import unique_path

logger = get_logger("pipeline")


class XYZHandler(FileSystemEventHandler):
    def __init__(self, job_manager, config):
        self.job_manager = job_manager
        self.config = config
        self.input_dir = Path(config['paths']['input_dir'])
        self.waiting_dir = Path(config['paths']['waiting_dir'])

    def on_created(self, event):
        # Fix for different watchdog API versions
        if hasattr(event, 'is_directory'):
            is_dir = event.is_directory
        else:
            is_dir = getattr(event, 'is_dir', False)
            
        if not is_dir and event.src_path.endswith('.xyz'):
            xyz_path = Path(event.src_path)
            logger.info(f"DETECT New XYZ: {xyz_path.name}")
            try:
                inp_content = self._generate_inp_from_xyz(xyz_path)
                tmp_inp = xyz_path.with_suffix('.inp')
                tmp_inp.write_text(inp_content, encoding='utf-8')
                self._move_to_waiting_unique(xyz_path, tmp_inp)
                final_inp = self.waiting_dir / tmp_inp.name
                job = ORCAJob(
                    inp_path=final_inp,
                    xyz_path=self.waiting_dir / xyz_path.name,
                    job_type='opt'
                )
                self.job_manager.add_job(job)
                logger.info(f"QUEUE Added opt job for {final_inp.name}")
            except Exception as e:
                logger.exception(f"Failed to process {xyz_path.name}: {e}")
                NotificationSystem.send_error(f"INP generation failed: {xyz_path.name}\nError: {e}")

    def _generate_inp_from_xyz(self, xyz_path: Path) -> str:
        lines = xyz_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        if len(lines) < 2:
            raise ValueError(f"Invalid XYZ file: {xyz_path.name} (too few lines)")
        try:
            num_atoms = int(lines[0].strip())
        except Exception:
            raise ValueError(f"Invalid XYZ header: {xyz_path.name} (first line must be atom count)")
        if len(lines) < 2 + num_atoms:
            raise ValueError(f"Invalid XYZ file: {xyz_path.name} (missing coordinate lines)")

        coords = []
        for i in range(2, 2 + num_atoms):
            parts = lines[i].split()
            if len(parts) < 4:
                raise ValueError(f"Invalid coordinate format at line {i+1} in {xyz_path.name}")
            element = parts[0]
            try:
                x, y, z = map(float, parts[1:4])
            except ValueError as ex:
                raise ValueError(f"Invalid coordinate values at line {i+1} in {xyz_path.name}: {ex}")
            coords.append(f"{element:>2} {x:>12.6f} {y:>12.6f} {z:>12.6f}")

        method = self.config['orca']['method']
        basis = self.config['orca']['basis_set']
        charge = int(self.config['orca']['charge'])
        multiplicity = int(self.config['orca']['multiplicity'])
        nprocs = self.config['orca']['nprocs']
        maxcore = self.config['orca']['maxcore']

        solvent_model = self.config['orca'].get('solvent_model', 'none').strip().lower()
        solvent_name = self.config['orca'].get('solvent_name', 'water').strip()
        extra_keywords = self.config['orca'].get('extra_keywords', '').strip()

        solvent_kw = ''
        if solvent_model != 'none' and solvent_model.upper() in ['CPCM','SMD','COSMO']:
            # Correct ORCA syntax
            solvent_kw = f" {solvent_model.upper()}({solvent_name.capitalize()})"

        first_line = f"! {method} {basis} Opt{solvent_kw}"
        if extra_keywords:
            first_line += f" {extra_keywords}"

        inp = [first_line, '', f"%pal nprocs {nprocs} end", f"%maxcore {maxcore}", '', f"* xyz {charge} {multiplicity}"]
        inp.extend(coords)
        inp.append('*')
        return "\n".join(inp) + "\n"

    def _move_to_waiting_unique(self, xyz_path: Path, inp_path: Path):
        import shutil
        self.waiting_dir.mkdir(parents=True, exist_ok=True)
        dst_xyz = unique_path(self.waiting_dir / xyz_path.name)
        dst_inp = unique_path(self.waiting_dir / inp_path.name)
        shutil.move(str(xyz_path), str(dst_xyz))
        shutil.move(str(inp_path), str(dst_inp))
        xyz_path = dst_xyz
        inp_path = dst_inp
        logger.info(f"MOVE -> waiting: {dst_xyz.name}, {dst_inp.name}")


class ORCAPipeline:
    def __init__(self, config_path='config.txt'):
        self.config = self._load_config(config_path)
        self._setup_directories()
        self.job_manager = JobManager(self.config)
        self.notification_system = NotificationSystem(self.config)
        self.observer = Observer()
        self.xyz_handler = XYZHandler(self.job_manager, self.config)

    def _load_config(self, config_path):
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding='utf-8')
        return cfg

    def _setup_directories(self):
        for d in ['folders/input', 'folders/waiting', 'folders/working', 'folders/products', 'folders/logs']:
            Path(d).mkdir(parents=True, exist_ok=True)
            logger.info(f"SETUP {d}")

    def start(self):
        logger.info("START ORCA Automation Pipeline")
        input_dir = self.config['paths']['input_dir']
        self.observer.schedule(self.xyz_handler, input_dir, recursive=False)
        self.observer.start()
        self.job_manager.start()
        self.notification_system.start_monitoring(self.job_manager)
        logger.info(f"MONITOR {input_dir}")
        
        try:
            while True:
                # Check for fatal errors and stop pipeline if needed
                if self.job_manager.has_fatal_error():
                    logger.error("FATAL ERROR detected - stopping pipeline")
                    self.stop()
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KEYBOARD INTERRUPT received")
            self.stop()

    def stop(self):
        logger.info("STOP Shutting down...")
        self.observer.stop(); self.observer.join()
        self.job_manager.stop(); self.notification_system.stop()
        logger.info("EXIT Done")


if __name__ == '__main__':
    ORCAPipeline().start()
