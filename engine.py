"""
Transfer engine for CopyForge.

Handles:
- Chunked file copy with simultaneous hash computation (single read pass)
- Post-copy verification (second read pass on destination)
- Automatic retry with exponential back-off
- Pause / cancel via threading.Event
- Windows long-path support (\\\\?\\ prefix)
- Progress callbacks dispatched at ~10 Hz
- Concurrent file transfers with thread pool
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

from models import FileItem, FileStatus, TransferJob, JobStatus

# ── Optional fast hash back-ends ─────────────────────────────────────────────
try:
    import blake3 as _blake3
    HAS_BLAKE3 = True
except ImportError:
    HAS_BLAKE3 = False

SUPPORTED_ALGORITHMS = ["BLAKE3", "SHA256", "SHA512", "SHA1", "MD5"]
if not HAS_BLAKE3:
    SUPPORTED_ALGORITHMS[0] = "SHA256"   # fallback default

DEFAULT_CHUNK = 1 * 1024 * 1024   # 1 MB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _win_path(p: Path) -> str:
    """Return a Windows extended-length path string to bypass MAX_PATH.
    Uses absolute() rather than resolve() to avoid network round-trips.
    """
    s = str(p.absolute())
    if len(s) > 260 and os.name == "nt":
        if s.startswith("\\\\"):
            return "\\\\?\\UNC\\" + s[2:]
        return "\\\\?\\" + s
    return s


class _SkipError(Exception):
    """Raised inside copy_with_hash when skip_event fires."""


def _make_hasher(algorithm: str):
    alg = algorithm.upper()
    if alg == "BLAKE3" and HAS_BLAKE3:
        return _blake3.blake3()
    if alg in ("MD5", "SHA1", "SHA256", "SHA512"):
        return hashlib.new(alg.lower())
    # Safe fallback
    return hashlib.sha256()


def compute_hash(
    path: Path,
    algorithm: str,
    chunk_size: int = DEFAULT_CHUNK,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Hash a file without copying it. Returns hex digest."""
    h = _make_hasher(algorithm)
    total = 0
    with open(_win_path(path), "rb") as f:
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Cancelled")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
            if progress_cb:
                progress_cb(total)
    return h.hexdigest()


def copy_with_hash(
    src: Path,
    dst: Path,
    algorithm: str,
    chunk_size: int = DEFAULT_CHUNK,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    skip_event: Optional[threading.Event] = None,
) -> tuple[str, float]:
    """
    Copy *src* → *dst* while simultaneously computing the source hash.
    Returns (src_hex_digest, elapsed_seconds).
    Preserves file timestamps and attributes.
    Raises InterruptedError on cancel, _SkipError on skip.
    """
    h = _make_hasher(algorithm)
    # Use os.makedirs with the win_path string to support long UNC paths.
    os.makedirs(_win_path(dst.parent), exist_ok=True)

    start = time.perf_counter()
    written = 0

    with open(_win_path(src), "rb") as fsrc, open(_win_path(dst), "wb") as fdst:
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Cancelled")
            if skip_event and skip_event.is_set():
                raise _SkipError("Skipped by user")
            chunk = fsrc.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            fdst.write(chunk)
            written += len(chunk)
            if progress_cb:
                progress_cb(written)

    try:
        shutil.copystat(_win_path(src), _win_path(dst))
    except OSError:
        pass

    return h.hexdigest(), time.perf_counter() - start


# ── Transfer engine ───────────────────────────────────────────────────────────

class TransferEngine:
    """
    Runs transfer jobs in a background thread.
    All callbacks are invoked from that background thread; the GUI must
    dispatch them to the main thread with ``widget.after(0, ...)``.
    
    Supports concurrent file transfers using a thread pool.
    """

    def __init__(self, num_workers: int = 2):
        self.num_workers = max(1, min(num_workers, 8))  # Clamp 1-8 workers
        
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()            # not paused
        self._skip_current = threading.Event()  # set to skip all active files

        self._thread: Optional[threading.Thread] = None
        self._speed_samples: List[tuple[float, float]] = []   # (timestamp, bytes/s)
        self._lock = threading.Lock()

        # ── Callbacks (set by GUI) ────────────────────────────────────────────
        # Called when file copying starts
        self.on_file_start:    Optional[Callable[[FileItem, TransferJob], None]] = None
        # Called periodically: (file_item, bytes_done, speed_bps)
        self.on_file_progress: Optional[Callable[[FileItem, int, float], None]] = None
        # Called when a file finishes (any status)
        self.on_file_done:     Optional[Callable[[FileItem, TransferJob], None]] = None
        # Called when the whole job finishes
        self.on_job_done:      Optional[Callable[[TransferJob], None]] = None
        # Called after scanning completes
        self.on_scan_done:     Optional[Callable[[TransferJob], None]] = None
        # Called with current speed in bytes/s (throttled)
        self.on_speed_sample:  Optional[Callable[[float], None]] = None

    # ── Public control ────────────────────────────────────────────────────────

    def start(self, job: TransferJob):
        self._cancel.clear()
        self._pause.set()
        self._speed_samples.clear()
        self._thread = threading.Thread(
            target=self._run, args=(job,), daemon=True, name=f"engine-{job.job_id}"
        )
        self._thread.start()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def cancel(self):
        self._cancel.set()
        self._pause.set()   # unblock any pause-wait

    def skip_current(self):
        """Skip all files currently being transferred."""
        self._skip_current.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_speed_history(self) -> List[float]:
        with self._lock:
            return [s for _, s in self._speed_samples]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, job: TransferJob):
        job.started_at = time.time()
        job.add_log(f"Job started: {job.source_path} → {job.target_path}")

        # Scan if file list is empty
        if not job.files:
            job.status = JobStatus.SCANNING
            job.add_log("Scanning source files…")
            try:
                self._scan(job)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error_message = str(exc)
                job.add_log(f"Scan failed: {exc}")
                if self.on_job_done:
                    self.on_job_done(job)
                return

            if self._cancel.is_set():
                job.status = JobStatus.CANCELLED
                if self.on_job_done:
                    self.on_job_done(job)
                return

            job.add_log(f"Found {len(job.files)} files ({job.total_size_str})")
            if self.on_scan_done:
                self.on_scan_done(job)

        job.status = JobStatus.RUNNING
        
        # ── Concurrent transfer phase using thread pool ────────────────────────
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {}
            file_index = 0
            
            # Submit initial batch of files
            while file_index < len(job.files) and len(futures) < self.num_workers:
                fi = job.files[file_index]
                if fi.status in (FileStatus.PENDING, FileStatus.FAILED, FileStatus.HASH_MISMATCH):
                    future = executor.submit(self._transfer_file, fi, job)
                    futures[future] = fi
                file_index += 1
            
            # Process completions and submit new files
            while futures:
                # Check for pause (wait while paused)
                while not self._pause.is_set() and not self._cancel.is_set():
                    time.sleep(0.05)
                
                if self._cancel.is_set():
                    break
                
                # Wait for at least one to complete (with timeout)
                try:
                    done_futures = list(as_completed(futures, timeout=0.1))
                except TimeoutError:
                    # Timeout is OK, just try again
                    done_futures = []
                
                for future in done_futures:
                    del futures[future]
                    
                    # Submit next file if available
                    while file_index < len(job.files) and len(futures) < self.num_workers:
                        fi = job.files[file_index]
                        if fi.status in (FileStatus.PENDING, FileStatus.FAILED, FileStatus.HASH_MISMATCH):
                            future = executor.submit(self._transfer_file, fi, job)
                            futures[future] = fi
                        file_index += 1

        if not self._cancel.is_set():
            job.status = (
                JobStatus.COMPLETED if job.failed_files == 0 else JobStatus.FAILED
            )
        else:
            job.status = JobStatus.CANCELLED

        job.completed_at = time.time()
        job.add_log(
            f"Job {job.status.value}. "
            f"OK={job.ok_files} Skipped={job.skipped_files} Failed={job.failed_files}"
        )

        if self.on_job_done:
            self.on_job_done(job)

    def _scan(self, job: TransferJob):
        src = job.source_path
        dst = job.target_path

        if src.is_file():
            tgt = (dst / src.name) if (dst and dst.is_dir()) else dst
            job.files.append(
                FileItem(source=src, target=tgt, size=src.stat().st_size)
            )
            return

        pattern = "**/*" if job.include_subdirs else "*"
        for path in sorted(src.glob(pattern)):
            if self._cancel.is_set():
                return
            if not path.is_file():
                continue

            rel = path.relative_to(src)
            tgt = dst / rel if dst else None

            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            # Overwrite-mode check
            if tgt and tgt.exists():
                if job.overwrite_mode == "skip_existing":
                    job.files.append(
                        FileItem(source=path, target=tgt, size=size, status=FileStatus.SKIPPED)
                    )
                    continue
                elif job.overwrite_mode == "overwrite_newer":
                    try:
                        if path.stat().st_mtime <= tgt.stat().st_mtime:
                            job.files.append(
                                FileItem(source=path, target=tgt, size=size, status=FileStatus.SKIPPED)
                            )
                            continue
                    except OSError:
                        pass

            job.files.append(FileItem(source=path, target=tgt, size=size))

    def _transfer_file(self, fi: FileItem, job: TransferJob):
        chunk = job.buffer_size_mb * 1024 * 1024
        self._skip_current.clear()  # reset per-file skip flag

        fi.status = FileStatus.COPYING
        if self.on_file_start:
            self.on_file_start(fi, job)

        job.add_log(f"Copying: {fi.source.name} ({fi.size_str})")

        # Speed tracking state
        _last_bytes = [0]
        _last_ts = [time.perf_counter()]
        _throttle_ts = [0.0]

        def _progress(written: int):
            fi.bytes_copied = written
            now = time.perf_counter()
            dt = now - _last_ts[0]
            if dt >= 0.1:
                speed = (written - _last_bytes[0]) / dt
                _last_bytes[0] = written
                _last_ts[0] = now
                with self._lock:
                    self._speed_samples.append((now, speed))
                    if len(self._speed_samples) > 120:
                        self._speed_samples.pop(0)
                if now - _throttle_ts[0] >= 0.1:
                    _throttle_ts[0] = now
                    if self.on_speed_sample:
                        self.on_speed_sample(speed)
                    if self.on_file_progress:
                        self.on_file_progress(fi, written, speed)

        # ── Copy with retries ─────────────────────────────────────────────────
        src_hash = ""
        success = False
        for attempt in range(job.retry_count + 1):
            if self._cancel.is_set():
                fi.status = FileStatus.SKIPPED
                if self.on_file_done:
                    self.on_file_done(fi, job)
                return
            try:
                fi.bytes_copied = 0
                src_hash, elapsed = copy_with_hash(
                    fi.source, fi.target, job.hash_algorithm,
                    chunk_size=chunk,
                    progress_cb=_progress,
                    cancel_event=self._cancel,
                    skip_event=self._skip_current,
                )
                fi.src_hash = src_hash
                fi.transfer_time = elapsed
                success = True
                break
            except _SkipError:
                # User clicked Skip — remove partial file and move on
                fi.status = FileStatus.SKIPPED
                fi.error_message = "Skipped by user"
                self._skip_current.clear()
                try:
                    if fi.target and fi.target.exists():
                        fi.target.unlink()
                except OSError:
                    pass
                job.add_log(f"  Skipped: {fi.source.name}")
                if self.on_file_done:
                    self.on_file_done(fi, job)
                return
            except InterruptedError:
                fi.status = FileStatus.SKIPPED
                if self.on_file_done:
                    self.on_file_done(fi, job)
                return
            except OSError as exc:
                fi.retry_count = attempt + 1
                fi.error_message = str(exc)
                job.add_log(
                    f"  Attempt {attempt + 1}/{job.retry_count + 1} failed for "
                    f"{fi.source.name}: {exc}"
                )
                if attempt < job.retry_count:
                    wait = min(2 ** attempt, 30)
                    job.add_log(f"  Retrying in {wait}s…")
                    time.sleep(wait)

        if not success:
            fi.status = FileStatus.FAILED
            job.add_log(f"  FAILED: {fi.source.name} — {fi.error_message}")
            if self.on_file_done:
                self.on_file_done(fi, job)
            return

        # ── Verify ────────────────────────────────────────────────────────────
        if job.verify_after_copy and fi.target:
            fi.status = FileStatus.VERIFYING
            if self.on_file_progress:
                self.on_file_progress(fi, fi.bytes_copied, 0)
            try:
                dst_hash = compute_hash(
                    fi.target, job.hash_algorithm,
                    chunk_size=chunk,
                    cancel_event=self._cancel,
                )
                fi.dst_hash = dst_hash
                if src_hash == dst_hash:
                    fi.status = FileStatus.VERIFIED
                    job.add_log(f"  ✓ Verified: {fi.source.name}")
                else:
                    fi.status = FileStatus.HASH_MISMATCH
                    fi.error_message = (
                        f"Hash mismatch  src={src_hash[:8]}  dst={dst_hash[:8]}"
                    )
                    job.add_log(f"  ⚠ Hash mismatch: {fi.source.name}")
            except Exception as exc:
                fi.status = FileStatus.FAILED
                fi.error_message = f"Verify error: {exc}"
                job.add_log(f"  ✗ Verify failed: {fi.source.name}: {exc}")
        else:
            fi.status = FileStatus.OK

        if self.on_file_done:
            self.on_file_done(fi, job)
