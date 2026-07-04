#!/usr/bin/env python3
"""Build CopyForge executable with PyInstaller."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

def build_exe():
    """Build the CopyForge executable."""
    print("="*70)
    print("CopyForge EXE Builder")
    print("="*70)
    
    # Paths
    project_dir = Path(__file__).parent
    dist_dir = project_dir / "dist"
    build_dir = project_dir / "build"
    spec_file = project_dir / "copyforge.spec"
    
    print(f"\nProject directory: {project_dir}")
    print(f"Output directory: {dist_dir}")
    
    # Clean previous builds
    print("\nCleaning previous builds...")
    for d in [dist_dir, build_dir]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  ✓ Removed {d.name}/")
    
    # Build with PyInstaller
    print("\nBuilding executable with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        str(spec_file),
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✓ Build successful!")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed!")
        print(e.stderr)
        return False
    
    # Verify output
    exe_path = dist_dir / "CopyForge" / "CopyForge.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024*1024)
        print(f"\n✓ Executable created: {exe_path}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"\nExecutable location:")
        print(f"  {exe_path}")
        print(f"\nTo run:")
        print(f"  cd {dist_dir / 'CopyForge'}")
        print(f"  CopyForge.exe")
        return True
    else:
        print(f"✗ Executable not found at {exe_path}")
        return False

if __name__ == "__main__":
    success = build_exe()
    exit(0 if success else 1)
