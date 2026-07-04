#!/usr/bin/env python3
"""Build CopyForge executable with PyInstaller."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _to_windows_version_tuple(version_text: str) -> tuple[int, int, int, int]:
    """Convert semantic-ish version text into a 4-part Windows version tuple."""
    cleaned = version_text.strip().lstrip("v")
    main = cleaned.split("-", 1)[0].split("+", 1)[0]
    parts = [p for p in main.split(".") if p.isdigit()]
    numbers = [int(p) for p in parts[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def _resolve_build_version(project_dir: Path) -> str:
    """Resolve build version from env, then git tag, then fallback."""
    env_version = (os.environ.get("COPYFORGE_VERSION") or "").strip()
    if env_version:
        return env_version

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        tag = result.stdout.strip()
        if tag:
            return tag
    except Exception:
        pass

    return "1.0.0"


def _write_version_resource(version_file: Path, product_version: str) -> None:
    """Write a PyInstaller-compatible Windows version resource file."""
    v1, v2, v3, v4 = _to_windows_version_tuple(product_version)
    version_file.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v1}, {v2}, {v3}, {v4}),
    prodvers=({v1}, {v2}, {v3}, {v4}),
    mask=0x3F,
    flags=0x0,
    OS=0x4,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'CopyForge'),
        StringStruct('FileDescription', 'CopyForge file copy utility'),
        StringStruct('FileVersion', '{v1}.{v2}.{v3}.{v4}'),
        StringStruct('InternalName', 'CopyForge'),
        StringStruct('LegalCopyright', 'Copyright (c) 2026 CopyForge'),
        StringStruct('OriginalFilename', 'CopyForge.exe'),
        StringStruct('ProductName', 'CopyForge'),
        StringStruct('ProductVersion', '{v1}.{v2}.{v3}.{v4}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    version_file.write_text(content, encoding="utf-8")


def _ensure_icon(project_dir: Path) -> Path:
    """Generate app icon if missing and return icon path."""
    icon_path = project_dir / "assets" / "copyforge.ico"
    if icon_path.exists():
        return icon_path

    generator = project_dir / "tools" / "generate_icon.py"
    subprocess.run([sys.executable, str(generator)], cwd=project_dir, check=True)
    if not icon_path.exists():
        raise FileNotFoundError(f"Expected generated icon at {icon_path}")
    return icon_path

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
    version_file = project_dir / "assets" / "version_info.txt"
    product_version = _resolve_build_version(project_dir)
    
    print(f"\nProject directory: {project_dir}")
    print(f"Output directory: {dist_dir}")
    print(f"Build version: {product_version}")

    try:
        icon_path = _ensure_icon(project_dir)
        _write_version_resource(version_file, product_version)
        print(f"Using icon: {icon_path}")
        print(f"Wrote version metadata: {version_file}")
    except Exception as e:
        print(f"✗ Asset preparation failed: {e}")
        return False
    
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
