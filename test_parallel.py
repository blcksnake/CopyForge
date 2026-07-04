#!/usr/bin/env python3
"""Test parallel/concurrent file transfers."""
import shutil
import tempfile
import time
from pathlib import Path

from engine import TransferEngine
from models import TransferJob


def test_parallel_transfers():
    """Test concurrent file transfers with different worker counts."""
    print("\n" + "="*70)
    print("COPYFORGE PARALLEL TRANSFER TEST")
    print("="*70)
    
    # Setup test directories
    tmp_dir = Path(tempfile.gettempdir()) / "copyforge_parallel_test"
    tmp_dir.mkdir(exist_ok=True)
    src_dir = tmp_dir / "source"
    src_dir.mkdir(exist_ok=True)
    
    # Create 8 test files of different sizes
    print(f"\nCreating test files in {src_dir}...")
    file_sizes = [1*1024*1024, 2*1024*1024, 1*1024*1024, 2*1024*1024,
                  500*1024, 500*1024, 3*1024*1024, 1*1024*1024]  # 11 MB total
    
    for i, size in enumerate(file_sizes):
        file_path = src_dir / f"file_{i:02d}.bin"
        with open(file_path, "wb") as f:
            f.write(b"\x00" * size)
        print(f"  ✓ file_{i:02d}.bin ({size//(1024*1024)} MB)")
    
    # Test 1: Sequential (1 worker)
    print("\n" + "-"*70)
    print("TEST 1: Sequential Transfer (1 worker)")
    print("-"*70)
    dst_1 = tmp_dir / "output_1worker"
    dst_1.mkdir(exist_ok=True)
    
    job_1 = TransferJob(
        source_path=src_dir,
        target_path=dst_1,
        label="1-Worker Sequential",
        num_workers=1,
    )
    
    engine_1 = TransferEngine(num_workers=1)
    
    completed_files = []
    def on_file_done_1(fi, job):
        completed_files.append(fi.source.name)
        print(f"  ✓ {fi.source.name:20} {fi.status.value}")
    
    engine_1.on_file_done = on_file_done_1
    
    start = time.time()
    engine_1.start(job_1)
    while engine_1.is_running():
        time.sleep(0.1)
    elapsed_1 = time.time() - start
    
    print(f"Completed: {len(completed_files)} files in {elapsed_1:.2f}s")
    
    # Test 2: Parallel (4 workers)
    print("\n" + "-"*70)
    print("TEST 2: Parallel Transfer (4 workers)")
    print("-"*70)
    dst_4 = tmp_dir / "output_4workers"
    dst_4.mkdir(exist_ok=True)
    
    job_4 = TransferJob(
        source_path=src_dir,
        target_path=dst_4,
        label="4-Worker Parallel",
        num_workers=4,
    )
    
    engine_4 = TransferEngine(num_workers=4)
    
    completed_files_4 = []
    transfer_order = []
    
    def on_file_start_4(fi, job):
        transfer_order.append((time.time(), fi.source.name, "START"))
    
    def on_file_done_4(fi, job):
        completed_files_4.append(fi.source.name)
        transfer_order.append((time.time(), fi.source.name, "DONE"))
        print(f"  ✓ {fi.source.name:20} {fi.status.value}")
    
    engine_4.on_file_start = on_file_start_4
    engine_4.on_file_done = on_file_done_4
    
    start = time.time()
    engine_4.start(job_4)
    while engine_4.is_running():
        time.sleep(0.1)
    elapsed_4 = time.time() - start
    
    print(f"Completed: {len(completed_files_4)} files in {elapsed_4:.2f}s")
    
    # Test 3: Pause/Resume with parallel transfers
    print("\n" + "-"*70)
    print("TEST 3: Pause/Resume with Parallel Transfers (2 workers)")
    print("-"*70)
    dst_pause = tmp_dir / "output_pause"
    dst_pause.mkdir(exist_ok=True)
    
    job_pause = TransferJob(
        source_path=src_dir,
        target_path=dst_pause,
        label="Pause Test",
        num_workers=2,
    )
    
    engine_pause = TransferEngine(num_workers=2)
    
    paused_files = []
    resumed = [False]
    
    def on_file_done_pause(fi, job):
        print(f"  ✓ {fi.source.name:20} {fi.status.value}")
        if len(paused_files) == 2 and not resumed[0]:
            print("  ⏸ Pausing after 2 files...")
            engine_pause.pause()
            paused_files.append(None)  # Marker for pause
        elif len(paused_files) == 3:
            print("  ▶ Resuming transfer...")
            engine_pause.resume()
            resumed[0] = True
    
    engine_pause.on_file_done = on_file_done_pause
    
    start = time.time()
    engine_pause.start(job_pause)
    
    # Let it run for a bit, then resume
    while engine_pause.is_running():
        time.sleep(0.1)
    elapsed_pause = time.time() - start
    
    completed_pause = sum(1 for f in paused_files if f is not None)
    print(f"Completed: {completed_pause} files in {elapsed_pause:.2f}s (with pause)")
    
    # Analysis
    print("\n" + "="*70)
    print("ANALYSIS")
    print("="*70)
    print(f"Sequential (1 worker):  {elapsed_1:.2f}s")
    print(f"Parallel (4 workers):   {elapsed_4:.2f}s")
    speedup = elapsed_1 / elapsed_4 if elapsed_4 > 0 else 0
    print(f"Speedup:                {speedup:.2f}x")
    print(f"Pause/Resume:           {elapsed_pause:.2f}s")
    
    # Check concurrent execution in parallel test
    print(f"\nTransfer Order (4-worker test):")
    active_transfers = {}
    max_concurrent = 0
    for ts, name, event in transfer_order[:16]:  # First 8 pairs
        if event == "START":
            active_transfers[name] = ts
            max_concurrent = max(max_concurrent, len(active_transfers))
            print(f"  ▶ {name:20} START   (active: {len(active_transfers)})")
        else:  # DONE
            if name in active_transfers:
                duration = ts - active_transfers[name]
                del active_transfers[name]
                print(f"  ✓ {name:20} DONE    ({duration:.2f}s)")
    
    print(f"\nMax concurrent transfers: {max_concurrent} (configured: 4)")
    
    # Cleanup
    print(f"\nCleaning up {tmp_dir}...")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    
    print("\n" + "="*70)
    print("✓ PARALLEL TRANSFER TEST COMPLETE")
    print("="*70)
    
    # Verify results
    success = (
        len(completed_files) == 8 and
        len(completed_files_4) == 8 and
        speedup > 1.0 and
        max_concurrent <= 4
    )
    
    return success


if __name__ == "__main__":
    success = test_parallel_transfers()
    exit(0 if success else 1)
