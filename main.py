#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Automation Pipeline - Main Controller (solvent & extra keywords)
"""

import time
import configparser
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from job import ORCAJob, JobManager
from notifier import NotificationSystem


class XYZHandler(FileSystemEventHandler):
    def __init__(self, job_manager, config):
        self.job_manager = job_manager
        self.config = config
        self.input_dir = Path(config['paths']['input_dir'])
        self.waiting_dir = Path(config['paths']['waiting_dir'])

    def on_created(self, event):
        if not event.is_dir and event.src_path.endswith('.xyz'):
            xyz_path = Path(event.src_path)
            print(f"[DETECT] New XYZ file: {xyz_path.name}")
            try:
                inp_content = self._generate_inp_from_xyz(xyz_path)
                inp_path = xyz_path.with_suffix('.inp')
                inp_path.write_text(inp_content, encoding='utf-8')
                self._move_to_waiting(xyz_path, inp_path)
                job = ORCAJob(
                    inp_path=self.waiting_dir / inp_path.name,
                    xyz_path=self.waiting_dir / xyz_path.name,
                    job_type='opt'
                )
                self.job_manager.add_job(job)
            except Exception as e:
                print(f"[ERROR] Failed to process {xyz_path.name}: {e}")
                NotificationSystem.send_error(f"INP generation failed: {xyz_path.name}\nError: {e}")

    def _generate_inp_from_xyz(self, xyz_path: Path) -> str:
        lines = xyz_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        num_atoms = int(lines[0].strip())
        coords = []
        for i in range(2, 2 + num_atoms):
            parts = lines[i].split()
            element = parts[0]
            x, y, z = map(float, parts[1:4])
            coords.append(f"{element:>2} {x:>12.6f} {y:>12.6f} {z:>12.6f}")

        method = self.config['orca']['method']
        basis = self.config['orca']['basis_set']
        charge = int(self.config['orca']['charge'])
        multiplicity = int(self.config['orca']['multiplicity'])
        nprocs = self.config['orca']['nprocs']
        maxcore = self.config['orca']['maxcore']

        # Solvent & extra keywords
        solvent_model = self.config['orca'].get('solvent_model', 'none').strip().lower()
        solvent_name = self.config['orca'].get('solvent_name', 'water').strip()
        extra_keywords = self.config['orca'].get('extra_keywords', '').strip()

        solvent_kw = ''
        if solvent_model != 'none':
            if solvent_model.upper() in ['CPCM', 'SMD', 'COSMO']:
                # ORCA syntax example: CPCM(Solvent=Water)
                cap = solvent_name.capitalize()
                solvent_kw = f" {solvent_model.upper()}(Solvent={cap})"

        first_line = f"! {method} {basis} Opt{solvent_kw}"
        if extra_keywords:
            first_line += f" {extra_keywords}"

        inp = [first_line, '', f"%pal nprocs {nprocs} end", f"%maxcore {maxcore}", '', f"* xyz {charge} {multiplicity}"]
        inp.extend(coords)
        inp.append('*')
        return "\n".join(inp) + "\n"

    def _move_to_waiting(self, xyz_path: Path, inp_path: Path):
        import shutil
        self.waiting_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(xyz_path), str(self.waiting_dir / xyz_path.name))
        shutil.move(str(inp_path), str(self.waiting_dir / inp_path.name))
        print(f"[MOVE] -> waiting: {xyz_path.name}, {inp_path.name}")


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
        for d in ['folders/input', 'folders/waiting', 'folders/working', 'folders/products']:
            Path(d).mkdir(parents=True, exist_ok=True)
            print(f"[SETUP] {d}")

    def start(self):
        print("[START] ORCA Automation Pipeline")
        input_dir = self.config['paths']['input_dir']
        self.observer.schedule(self.xyz_handler, input_dir, recursive=False)
        self.observer.start()
        self.job_manager.start()
        self.notification_system.start_monitoring(self.job_manager)
        print(f"[MONITOR] {input_dir}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\n[STOP] Shutting down...")
        self.observer.stop(); self.observer.join()
        self.job_manager.stop(); self.notification_system.stop()
        print("[EXIT] Done")


if __name__ == '__main__':
    import time
    ORCAPipeline().start()
