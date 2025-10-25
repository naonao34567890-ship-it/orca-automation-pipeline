#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORCA Automation Pipeline Setup Script
22nd Century Programer Bot

Run this script to:
1. Create required directory structure
2. Install Python dependencies
3. Validate configuration
4. Test notification systems
"""

import os
import sys
import subprocess
from pathlib import Path


def create_directories():
    """Create required folder structure"""
    print("[SETUP] Creating directory structure...")
    
    dirs = [
        'folders',
        'folders/input',
        'folders/waiting',
        'folders/working', 
        'folders/products'
    ]
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {dir_path}/")
    
    print("[SETUP] Directory structure created successfully!")


def install_dependencies():
    """Install required Python packages"""
    print("[SETUP] Installing Python dependencies...")
    
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("[SETUP] Dependencies installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install dependencies: {e}")
        return False
    
    return True


def validate_config():
    """Validate configuration file"""
    print("[SETUP] Validating configuration...")
    
    if not Path('config.txt').exists():
        print("[ERROR] config.txt not found!")
        return False
    
    import configparser
    config = configparser.ConfigParser()
    
    try:
        config.read('config.txt')
        
        # Check required sections
        required_sections = ['paths', 'orca', 'notification', 'gmail']
        for section in required_sections:
            if section not in config:
                print(f"[ERROR] Missing section: [{section}]")
                return False
            print(f"  ✓ [{section}]")
        
        # Check ORCA path
        orca_path = config['orca']['orca_path']
        if not Path(orca_path).exists():
            print(f"[WARNING] ORCA executable not found: {orca_path}")
            print("          Please update the path in config.txt")
        else:
            print(f"  ✓ ORCA found: {orca_path}")
        
        print("[SETUP] Configuration validation completed!")
        return True
        
    except Exception as e:
        print(f"[ERROR] Configuration validation failed: {e}")
        return False


def test_notifications():
    """Test notification systems"""
    print("[SETUP] Testing notification systems...")
    
    # Test Windows sound
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK)
        print("  ✓ Windows sound system available")
    except ImportError:
        print("  ⚠ Windows sound system not available (non-Windows OS?)")
    except Exception as e:
        print(f"  ⚠ Windows sound test failed: {e}")
    
    # Test plyer notifications
    try:
        from plyer import notification
        notification.notify(
            title="ORCA Pipeline Setup",
            message="Notification system test successful!",
            timeout=3
        )
        print("  ✓ Desktop notifications available")
    except ImportError:
        print("  ⚠ Desktop notifications not available (install plyer)")
    except Exception as e:
        print(f"  ⚠ Desktop notification test failed: {e}")
    
    print("[SETUP] Notification test completed!")


def main():
    """Main setup routine"""
    print("=" * 60)
    print("ORCA Automation Pipeline Setup")
    print("22nd Century Programer Bot Edition")
    print("=" * 60)
    
    # Step 1: Create directories
    create_directories()
    print()
    
    # Step 2: Install dependencies
    if not install_dependencies():
        print("[SETUP] Setup failed due to dependency installation issues.")
        return 1
    print()
    
    # Step 3: Validate configuration
    if not validate_config():
        print("[SETUP] Setup completed with configuration warnings.")
        print("        Please review and update config.txt before running.")
    print()
    
    # Step 4: Test notifications
    test_notifications()
    print()
    
    print("=" * 60)
    print("Setup completed successfully!")
    print("")
    print("Next steps:")
    print("1. Update config.txt with your ORCA path and Gmail settings")
    print("2. Run: python main.py")
    print("3. Drop XYZ files into folders/input/ to start processing")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())