#!/usr/bin/env python3
"""
Comprehensive test suite for CopyForge application.
Tests all core features: file operations, hashing, verification, transfers, reports.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
import time

# Add repo to path
sys.path.insert(0, str(Path(__file__).parent))

from engine import TransferEngine, SUPPORTED_ALGORITHMS, compute_hash
from models import TransferJob, FileItem, FileStatus, JobStatus
from report import generate_html_report, generate_csv_report, save_report

# Test configuration
TEST_DIR = Path(tempfile.gettempdir()) / "copyforge_test"
NETWORK_SHARE = Path("\\\\10.0.2.2\\Shared\\Documents\\Projects")

def setup():
    """Create test directories and files."""
    print("\n" + "="*70)
    print("COPYFORGE COMPREHENSIVE TEST SUITE")
    print("="*70)
    
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    
    src = TEST_DIR / "source"
    src.mkdir(exist_ok=True)
    
    # Create test files of various sizes
    files_created = []
    
    # Small file (100 KB)
    small = src / "small_test.bin"
    small.write_bytes(b"x" * (100 * 1024))
    files_created.append(("small_test.bin", 100))
    
    # Medium file (5 MB)
    medium = src / "medium_test.bin"
    medium.write_bytes(b"y" * (5 * 1024 * 1024))
    files_created.append(("medium_test.bin", 5120))
    
    # Large file (50 MB)
    large = src / "large_test.bin"
    large.write_bytes(b"z" * (50 * 1024 * 1024))
    files_created.append(("large_test.bin", 51200))
    
    # Nested directory structure
    nested = src / "subdir" / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "nested_file.txt").write_text("Nested file content")
    files_created.append(("nested_file.txt", 0))
    
    print("\n✓ Test environment created:")
    print(f"  Source: {src}")
    for fname, size_kb in files_created:
        print(f"    - {fname} ({size_kb} KB)" if size_kb else f"    - {fname}")
    
    return src

def test_hash_algorithms(src: Path):
    """Test all supported hash algorithms."""
    print("\n" + "-"*70)
    print("TEST 1: Hash Algorithms")
    print("-"*70)
    
    test_file = src / "medium_test.bin"
    results = {}
    
    for algo in SUPPORTED_ALGORITHMS:
        start = time.time()
        hash_val = compute_hash(test_file, algo)
        elapsed = time.time() - start
        results[algo] = (hash_val, elapsed)
        status = "✓" if hash_val else "✗"
        print(f"{status} {algo:10} → {hash_val[:16]}... ({elapsed:.2f}s)")
    
    return all(results.values())

def test_local_transfer(src: Path):
    """Test local file transfer with hashing."""
    print("\n" + "-"*70)
    print("TEST 2: Local Transfer (Source → Local Target)")
    print("-"*70)
    
    dst = TEST_DIR / "local_target"
    dst.mkdir(exist_ok=True)
    
    job = TransferJob(source_path=src, target_path=dst)
    job.label = "Local Transfer Test"
    job.hash_algorithm = "blake3"
    job.verify_after_copy = True
    job.include_subdirs = True
    
    engine = TransferEngine()
    
    # Track events
    events = {
        'scan_done': False,
        'file_done': 0,
        'job_done': False,
        'files': []
    }
    
    def on_scan_done(j):
        events['scan_done'] = True
        print(f"✓ Scan complete: {len(j.files)} files found")
    
    def on_file_done(fi, j):
        events['file_done'] += 1
        status = "✓" if fi.status == FileStatus.VERIFIED else "?" if fi.status == FileStatus.OK else "✗"
        print(f"  {status} {fi.source.name:30} → {fi.status.name:10} ({fi.bytes_copied} bytes)")
        events['files'].append((fi.source.name, fi.status))
    
    def on_job_done(j):
        events['job_done'] = True
        print(f"✓ Transfer complete: {j.ok_files} OK, {j.verified_files} verified, {j.failed_files} failed")
    
    engine.on_scan_done = on_scan_done
    engine.on_file_done = on_file_done
    engine.on_job_done = on_job_done
    
    print(f"Starting transfer...")
    engine.start(job)
    
    # Wait for completion
    timeout = 60
    start = time.time()
    while engine.is_running() and time.time() - start < timeout:
        time.sleep(0.1)
    
    if time.time() - start >= timeout:
        print("✗ Transfer timed out after 60 seconds")
        return False
    
    success = events['scan_done'] and events['job_done'] and job.status == JobStatus.COMPLETED
    print(f"\nResult: {'PASS' if success else 'FAIL'}")
    return success

def test_network_transfer(src: Path):
    """Test network share transfer."""
    print("\n" + "-"*70)
    print("TEST 3: Network Transfer (Source → Network Share)")
    print("-"*70)
    
    if not NETWORK_SHARE.exists():
        print(f"⊘ Network share not accessible: {NETWORK_SHARE}")
        return None
    
    # Create target in network share
    dst = NETWORK_SHARE / f"test_{int(time.time())}"
    dst.mkdir(exist_ok=True, parents=True)
    
    job = TransferJob(source_path=src, target_path=dst)
    job.label = "Network Transfer Test"
    job.hash_algorithm = "sha256"
    job.verify_after_copy = True
    job.include_subdirs = True
    
    engine = TransferEngine()
    
    events = {'done': False, 'ok': 0, 'failed': 0}
    
    def on_job_done(j):
        events['done'] = True
        events['ok'] = j.ok_files
        events['failed'] = j.failed_files
        print(f"✓ Transfer complete: {j.ok_files} OK, {j.failed_files} failed")
    
    engine.on_job_done = on_job_done
    
    print(f"Transferring to {dst}...")
    engine.start(job)
    
    timeout = 120
    start = time.time()
    while engine.is_running() and time.time() - start < timeout:
        time.sleep(0.2)
    
    if time.time() - start >= timeout:
        print("✗ Transfer timed out")
        return False
    
    success = events['done'] and events['ok'] > 0
    print(f"Result: {'PASS' if success else 'FAIL'}")
    
    # Cleanup
    try:
        shutil.rmtree(dst)
    except:
        pass
    
    return success

def test_pause_resume(src: Path):
    """Test pause and resume functionality."""
    print("\n" + "-"*70)
    print("TEST 4: Pause & Resume")
    print("-"*70)
    
    dst = TEST_DIR / "pause_test"
    dst.mkdir(exist_ok=True)
    
    job = TransferJob(source_path=src, target_path=dst)
    job.label = "Pause/Resume Test"
    job.include_subdirs = True
    
    engine = TransferEngine()
    
    paused_at = {'file_count': 0}
    events = {'paused': False, 'resumed': False, 'done': False}
    
    def on_file_done(fi, j):
        paused_at['file_count'] += 1
        if paused_at['file_count'] == 1:
            engine.pause()
            events['paused'] = True
            print(f"⏸ Paused after 1st file")
    
    def on_job_done(j):
        events['done'] = True
        print(f"✓ Transfer complete: {j.ok_files} files")
    
    engine.on_file_done = on_file_done
    engine.on_job_done = on_job_done
    
    print("Starting transfer (will pause after 1st file)...")
    engine.start(job)
    
    # Wait for pause
    time.sleep(0.5)
    while engine.is_running() and not events['paused']:
        time.sleep(0.1)
    
    if events['paused']:
        print("✓ Paused successfully")
        time.sleep(0.5)
        engine.resume()
        events['resumed'] = True
        print("✓ Resumed transfer")
    
    # Wait for completion
    timeout = 60
    start = time.time()
    while engine.is_running() and time.time() - start < timeout:
        time.sleep(0.1)
    
    success = events['paused'] and events['resumed'] and events['done']
    print(f"Result: {'PASS' if success else 'FAIL'}")
    return success

def test_report_generation(src: Path):
    """Test HTML and CSV report generation."""
    print("\n" + "-"*70)
    print("TEST 5: Report Generation")
    print("-"*70)
    
    dst = TEST_DIR / "report_test"
    dst.mkdir(exist_ok=True)
    
    job = TransferJob(source_path=src, target_path=dst)
    job.label = "Report Test"
    job.hash_algorithm = "blake3"
    job.verify_after_copy = True
    job.include_subdirs = True
    
    engine = TransferEngine()
    
    events = {'done': False}
    
    def on_job_done(j):
        events['done'] = True
    
    engine.on_job_done = on_job_done
    
    print("Running transfer for report generation...")
    engine.start(job)
    
    timeout = 60
    start = time.time()
    while engine.is_running() and time.time() - start < timeout:
        time.sleep(0.1)
    
    if not events['done']:
        print("✗ Transfer failed")
        return False
    
    # Generate reports
    html_report = generate_html_report(job)
    csv_report = generate_csv_report(job)
    
    html_ok = len(html_report) > 0 and "<html" in html_report.lower()
    csv_ok = len(csv_report) > 0 and "file" in csv_report.lower()
    
    print(f"✓ HTML report: {len(html_report)} chars" if html_ok else "✗ HTML report failed")
    print(f"✓ CSV report: {len(csv_report)} chars" if csv_ok else "✗ CSV report failed")
    
    # Test file save
    html_path = TEST_DIR / "report.html"
    csv_path = TEST_DIR / "report.csv"
    
    try:
        save_report(job, html_path, fmt='html')
        save_report(job, csv_path, fmt='csv')
        html_saved = html_path.exists() and html_path.stat().st_size > 0
        csv_saved = csv_path.exists() and csv_path.stat().st_size > 0
        
        print(f"✓ HTML saved: {html_path.stat().st_size} bytes" if html_saved else "✗ HTML save failed")
        print(f"✓ CSV saved: {csv_path.stat().st_size} bytes" if csv_saved else "✗ CSV save failed")
        
        return html_ok and csv_ok and html_saved and csv_saved
    except Exception as e:
        print(f"✗ Report save failed: {e}")
        return False

def cleanup():
    """Remove test files."""
    print("\n" + "-"*70)
    print("CLEANUP")
    print("-"*70)
    try:
        shutil.rmtree(TEST_DIR)
        print("✓ Test directory removed")
    except Exception as e:
        print(f"⊘ Could not remove test directory: {e}")

def main():
    """Run all tests."""
    src = setup()
    
    results = {
        'Hash Algorithms': test_hash_algorithms(src),
        'Local Transfer': test_local_transfer(src),
        'Network Transfer': test_network_transfer(src),
        'Pause & Resume': test_pause_resume(src),
        'Report Generation': test_report_generation(src),
    }
    
    cleanup()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    for test_name, result in results.items():
        status = "✓ PASS" if result else ("⊘ SKIP" if result is None else "✗ FAIL")
        print(f"{status:10} {test_name}")
    
    passed = sum(1 for r in results.values() if r is True)
    total = sum(1 for r in results.values() if r is not None)
    print(f"\nResult: {passed}/{total} tests passed")
    print("="*70)
    
    return 0 if passed == total else 1

if __name__ == '__main__':
    sys.exit(main())
