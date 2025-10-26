#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Energy trajectory analysis and plotting for ORCA calculations.
"""

import re
from pathlib import Path
from typing import List, Tuple, Optional
import matplotlib.pyplot as plt
import matplotlib
# Use Agg backend for headless operation
matplotlib.use('Agg')


def extract_energy_trajectory(output_text: str) -> List[Tuple[int, float]]:
    """Extract energy values from ORCA output during optimization.
    
    Returns:
        List of (cycle, energy) tuples
    """
    trajectory = []
    
    # Look for energy patterns in optimization cycles
    patterns = [
        # Standard SCF energy pattern
        r'FINAL SINGLE POINT ENERGY\s+([+-]?\d+\.\d+)',
        # Energy in optimization cycles
        r'Total Energy\s*:\s*([+-]?\d+\.\d+)\s*Eh',
        # Alternative energy reporting
        r'E\(0\)\s*=\s*([+-]?\d+\.\d+)',
    ]
    
    # Try to find cycle information and corresponding energies
    cycle_matches = list(re.finditer(r'\*{4,}.*CYCLE\s+(\d+).*\*{4,}', output_text, re.IGNORECASE))
    energy_matches = []
    
    for pattern in patterns:
        energy_matches.extend(re.finditer(pattern, output_text))
    
    # If we have cycle markers, try to match energies to cycles
    if cycle_matches and energy_matches:
        for i, cycle_match in enumerate(cycle_matches):
            cycle_num = int(cycle_match.group(1))
            cycle_pos = cycle_match.end()
            
            # Find the next energy after this cycle marker
            next_cycle_pos = cycle_matches[i+1].start() if i+1 < len(cycle_matches) else len(output_text)
            
            for energy_match in energy_matches:
                if cycle_pos <= energy_match.start() < next_cycle_pos:
                    energy = float(energy_match.group(1))
                    trajectory.append((cycle_num, energy))
                    break
    
    # Fallback: just collect all energies with sequential numbering
    if not trajectory:
        for i, match in enumerate(energy_matches):
            energy = float(match.group(1))
            trajectory.append((i+1, energy))
    
    # Remove duplicates and sort by cycle
    trajectory = list(dict.fromkeys(trajectory))  # Remove duplicates while preserving order
    trajectory.sort(key=lambda x: x[0])
    
    return trajectory


def plot_energy_trajectory(trajectory: List[Tuple[int, float]], 
                          output_path: Path, 
                          molecule_name: str, 
                          job_type: str) -> bool:
    """Plot energy trajectory and save as PNG.
    
    Returns:
        True if plot was created successfully
    """
    if not trajectory:
        return False
    
    try:
        cycles, energies = zip(*trajectory)
        
        plt.figure(figsize=(10, 6))
        plt.plot(cycles, energies, 'b-o', linewidth=2, markersize=4)
        plt.xlabel('Optimization Cycle')
        plt.ylabel('Energy (Hartree)')
        plt.title(f'Energy Trajectory - {molecule_name} ({job_type.upper()})')
        plt.grid(True, alpha=0.3)
        
        # Add annotations for first and last points
        if len(trajectory) > 1:
            plt.annotate(f'Initial: {energies[0]:.6f}', 
                        xy=(cycles[0], energies[0]), 
                        xytext=(10, 10), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
            
            plt.annotate(f'Final: {energies[-1]:.6f}', 
                        xy=(cycles[-1], energies[-1]), 
                        xytext=(-10, -20), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()  # Important: close figure to free memory
        
        return True
        
    except Exception as e:
        print(f"[WARNING] Failed to create energy plot: {e}")
        return False


def create_energy_plot_from_output(output_path: Path, 
                                  plot_save_path: Path, 
                                  molecule_name: str, 
                                  job_type: str) -> bool:
    """Create energy trajectory plot from ORCA output file.
    
    Returns:
        True if plot was created successfully
    """
    try:
        text = output_path.read_text(encoding='utf-8', errors='ignore')
        trajectory = extract_energy_trajectory(text)
        
        if not trajectory:
            return False
            
        return plot_energy_trajectory(trajectory, plot_save_path, molecule_name, job_type)
        
    except Exception as e:
        print(f"[WARNING] Failed to create energy plot from {output_path.name}: {e}")
        return False
