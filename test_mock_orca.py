#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock ORCA Testing Script - Test pipeline without actual ORCA installation
Usage: python test_mock_orca.py
"""

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
import threading

# Mock ORCA executable script content
MOCK_ORCA_SCRIPT = '''#!/usr/bin/env python3
import sys
import time
from pathlib import Path

input_file = sys.argv[1]
basename = Path(input_file).stem

# Simulate ORCA calculation with delayed output
time.sleep(1)

# Create realistic ORCA output
output_content = f"""
                                         * O   R   C   A *

                           --- An Ab Initio, DFT and Semiempirical electronic structure package ---

Input file: {input_file}

****************************
* Geometry Optimization     *
****************************

----------------------
GEOMETRY OPTIMIZATION
----------------------

CYCLE    1
Total Energy:  -40.12345678

CYCLE    2  
Total Energy:  -40.12346789

CYCLE    3
Total Energy:  -40.12346820

***********************HURRAY********************
                    ***        THE OPTIMIZATION HAS CONVERGED     ***
                    ******************************************

FINAL SINGLE POINT ENERGY        -40.12346820891

CARTESIAN COORDINATES (ANGSTROEM)
C      0.000000    0.000000    0.000000
H      1.089000    0.000000    0.000000
H     -0.363000    1.027000    0.000000
H     -0.363000   -0.513500    0.889165
H     -0.363000   -0.513500   -0.889165

ORCA TERMINATED NORMALLY
"""

# Write output file
with open(f"{basename}.out", "w") as f:
    f.write(output_content)

# Create mock binary files
with open(f"{basename}.gbw", "wb") as f:
    f.write(b"Mock GBW binary data\\x00\\x01\\x02")

sys.exit(0)
'''

MOCK_ORCA_2MKL_SCRIPT = '''#!/usr/bin/env python3
import sys
from pathlib import Path

basename = sys.argv[1]
molden_content = f"""
[Molden Format]
[Title]
Mock Molden file generated for {Path(basename).name}

[Atoms] AU
C  1  6  0.000000  0.000000  0.000000
H  2  1  2.060000  0.000000  0.000000
H  3  1 -0.686000  1.942000  0.000000
H  4  1 -0.686000 -0.971000  1.681000
H  5  1 -0.686000 -0.971000 -1.681000

[GTO]
...
"""

with open(f"{basename}.molden.input", "w") as f:
    f.write(molden_content)

sys.exit(0)
'''

def setup_mock_orca():
    """Create mock ORCA executables for testing."""
    print("Setting up mock ORCA environment...")
    
    # Create mock executables
    mock_orca = Path('mock_orca.py')
    mock_orca_2mkl = Path('mock_orca_2mkl.py')
    
    with open(mock_orca, 'w') as f:
        f.write(MOCK_ORCA_SCRIPT)
    
    with open(mock_orca_2mkl, 'w') as f:
        f.write(MOCK_ORCA_2MKL_SCRIPT)
    
    os.chmod(mock_orca, 0o755)
    os.chmod(mock_orca_2mkl, 0o755)
    
    # Create test config
    config_content = f"""
[paths]
input_dir = folders/input
waiting_dir = folders/waiting
working_dir = folders/working
products_dir = folders/products

[orca]
orca_path = {Path.cwd() / 'mock_orca.py'}
orca_2mkl_path = {Path.cwd() / 'mock_orca_2mkl.py'}
generate_molden = true
method = B3LYP
basis_set = def2-SVP
charge = 0
multiplicity = 1
nprocs = 2
maxcore = 1024
max_parallel_jobs = 2
max_retries = 1

# Solvent settings  
solvent_model = CPCM
solvent_name = Chloroform
extra_keywords = 

[gmail]
user = test@example.com
app_password = testpassword123
recipient = test@example.com

[notification]
threshold = 5
debounce_seconds = 3
"""
    
    with open('config_test.txt', 'w') as f:
        f.write(config_content)
    
    print("✅ Mock ORCA environment ready")

def create_test_molecules():
    """Create test XYZ files."""
    Path('folders/input').mkdir(parents=True, exist_ok=True)
    
    molecules = {
        'methane': """
5
Methane test molecule
C   0.000000   0.000000   0.000000
H   1.089000   0.000000   0.000000
H  -0.363000   1.027000   0.000000
H  -0.363000  -0.513500   0.889165
H  -0.363000  -0.513500  -0.889165
""",
        'water': """
3
Water test molecule
O   0.000000   0.000000   0.000000
H   0.757000   0.586000   0.000000
H  -0.757000   0.586000   0.000000
""",
        'ammonia': """
4
Ammonia test molecule  
N   0.000000   0.000000   0.000000
H   0.937000   0.000000   0.000000
H  -0.469000   0.812000   0.000000
H  -0.469000  -0.406000   0.703000
"""
    }
    
    for name, content in molecules.items():
        with open(f'folders/input/{name}.xyz', 'w') as f:
            f.write(content.strip())
    
    print(f"✅ Created {len(molecules)} test molecules")

def run_pipeline_test():
    """Run pipeline with mock ORCA for testing."""
    print("Starting pipeline test...")
    
    # Start pipeline in background
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path.cwd())
    
    process = subprocess.Popen(
        [sys.executable, 'main.py', '-c', 'config_test.txt'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    def monitor_output():
        for line in iter(process.stdout.readline, ''):
            print(f"[PIPELINE] {line.rstrip()}")
    
    monitor_thread = threading.Thread(target=monitor_output, daemon=True)
    monitor_thread.start()
    
    # Let pipeline process files
    print("Waiting for pipeline processing...")
    time.sleep(15)
    
    # Add additional test file during runtime
    with open('folders/input/benzene.xyz', 'w') as f:
        f.write("""
12
Benzene test molecule
C   0.000000   1.393000   0.000000
C   1.206000   0.696000   0.000000
C   1.206000  -0.696000   0.000000
C   0.000000  -1.393000   0.000000
C  -1.206000  -0.696000   0.000000
C  -1.206000   0.696000   0.000000
H   0.000000   2.478000   0.000000
H   2.146000   1.239000   0.000000
H   2.146000  -1.239000   0.000000
H   0.000000  -2.478000   0.000000
H  -2.146000  -1.239000   0.000000
H  -2.146000   1.239000   0.000000
""")
    
    print("Added benzene during runtime...")
    time.sleep(10)
    
    # Terminate pipeline
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    
    return analyze_results()

def analyze_results():
    """Analyze test results and provide report."""
    print("\n" + "="*50)
    print("MOCK ORCA PIPELINE TEST RESULTS")
    print("="*50)
    
    # Check directory structure
    folders = ['input', 'waiting', 'working', 'products', 'logs']
    for folder in folders:
        path = Path(f'folders/{folder}')
        status = "✅" if path.exists() else "❌"
        print(f"{status} folders/{folder}: {'EXISTS' if path.exists() else 'MISSING'}")
    
    # Count files
    inp_files = list(Path('folders').rglob('*.inp'))
    out_files = list(Path('folders').rglob('*.out'))
    png_files = list(Path('folders').rglob('*energy.png'))
    molden_files = list(Path('folders').rglob('*.molden.input'))
    
    print(f"\n📁 File Analysis:")
    print(f"  INP files: {len(inp_files)}")
    print(f"  OUT files: {len(out_files)}")
    print(f"  Energy plots: {len(png_files)}")
    print(f"  Molden files: {len(molden_files)}")
    
    # Check INP syntax
    print(f"\n🔍 INP File Analysis:")
    for inp in inp_files[:3]:  # Check first 3
        content = inp.read_text()
        if 'CPCM(Chloroform)' in content:
            print(f"  ✅ {inp.name}: Correct ORCA syntax")
        else:
            print(f"  ❌ {inp.name}: Incorrect syntax")
            print(f"    Content: {content.splitlines()[0]}")
    
    # Check products structure
    product_dirs = list(Path('folders/products').rglob('*success*'))
    failed_dirs = list(Path('folders/products').rglob('*failed*'))
    fatal_dirs = list(Path('folders/products').rglob('*fatal*'))
    
    print(f"\n🏁 Results Summary:")
    print(f"  Successful jobs: {len(product_dirs)}")
    print(f"  Failed jobs: {len(failed_dirs)}")
    print(f"  Fatal errors: {len(fatal_dirs)}")
    
    # Show logs
    log_file = Path('folders/logs/pipeline.log')
    if log_file.exists():
        print(f"\n📋 Recent Logs:")
        lines = log_file.read_text().splitlines()[-10:]
        for line in lines:
            print(f"  {line}")
    
    # Overall assessment
    success = (
        len(inp_files) >= 2 and
        len(out_files) >= 1 and
        len(product_dirs) >= 1
    )
    
    print(f"\n{'='*50}")
    if success:
        print("✅ MOCK TEST: PASSED")
        print("Pipeline successfully processed test molecules!")
    else:
        print("❌ MOCK TEST: FAILED")
        print("Pipeline did not process files correctly.")
    
    return success

def cleanup():
    """Clean up test files."""
    paths_to_remove = [
        'folders', 'mock_orca.py', 'mock_orca_2mkl.py', 'config_test.txt'
    ]
    
    for path in paths_to_remove:
        p = Path(path)
        if p.exists():
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
    
    print("🧹 Cleanup completed")

if __name__ == '__main__':
    print("🗺 ORCA Pipeline Mock Testing")
    print("This script tests the pipeline without requiring ORCA installation.\n")
    
    try:
        setup_mock_orca()
        create_test_molecules()
        success = run_pipeline_test()
        
        if success:
            print("\n🎉 Pipeline is working correctly!")
            print("You can now use it with real ORCA by updating config.txt")
        else:
            print("\n😨 Pipeline test failed. Check the logs above for issues.")
        
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
    finally:
        response = input("\nCleanup test files? [y/N]: ")
        if response.lower() in ['y', 'yes']:
            cleanup()
        else:
            print("🗂 Test files preserved for inspection")
