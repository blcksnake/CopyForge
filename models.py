"""Data models for CopyForge."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class FileStatus(Enum):
    PENDING = "Pending"
    COPYING = "Copying"
    VERIFYING = "Verifying"
    OK = "OK"
    VERIFIED = "Verified"
    FAILED = "Failed"
    SKIPPED = "Skipped"
    HASH_MISMATCH = "Hash Mismatch"


class JobStatus(Enum):
    PENDING = "Pending"
    SCANNING = "Scanning"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class FileItem:
    source: Path
    target: Path
    size: int = 0
    status: FileStatus = FileStatus.PENDING
    src_hash: str = ""
    dst_hash: str = ""
    error_message: str = ""
    bytes_copied: int = 0
    transfer_time: float = 0.0
    retry_count: int = 0

    @property
    def size_str(self) -> str:
        return format_size(self.size)

    @property
    def src_hash_short(self) -> str:
        return self.src_hash[:9].upper() if self.src_hash else "----:----"

    @property
    def dst_hash_short(self) -> str:
        return self.dst_hash[:9].upper() if self.dst_hash else "----:----"

    @property
    def hash_match(self) -> Optional[bool]:
        if self.src_hash and self.dst_hash:
            return self.src_hash == self.dst_hash
        return None

    @property
    def rel_path(self) -> str:
        return str(self.source)


@dataclass
class TransferJob:
    source_path: Path
    target_path: Optional[Path]
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: str = ""
    files: List[FileItem] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    hash_algorithm: str = "BLAKE3"
    verify_after_copy: bool = True
    retry_count: int = 3
    include_subdirs: bool = True
    overwrite_mode: str = "overwrite_all"   # overwrite_all | overwrite_newer | skip_existing
    buffer_size_mb: int = 1
    num_workers: int = 2                    # concurrent file transfers (1-8)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_message: str = ""
    log_lines: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.label:
            self.label = self.source_path.name or str(self.source_path)

    # ── Aggregates ────────────────────────────────────────────────────────────

    @property
    def ok_files(self) -> int:
        return sum(1 for f in self.files if f.status in (FileStatus.OK, FileStatus.VERIFIED))

    @property
    def verified_files(self) -> int:
        return sum(1 for f in self.files if f.status == FileStatus.VERIFIED)

    @property
    def failed_files(self) -> int:
        return sum(1 for f in self.files if f.status in (FileStatus.FAILED, FileStatus.HASH_MISMATCH))

    @property
    def skipped_files(self) -> int:
        return sum(1 for f in self.files if f.status == FileStatus.SKIPPED)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def transferred_size(self) -> int:
        return sum(f.bytes_copied for f in self.files)

    @property
    def progress_percent(self) -> float:
        if not self.files:
            return 0.0
        done = self.ok_files + self.failed_files + self.skipped_files
        return done / len(self.files) * 100

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def total_size_str(self) -> str:
        return format_size(self.total_size)

    @property
    def transferred_size_str(self) -> str:
        return format_size(self.transferred_size)

    def add_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {msg}")


# ── Utility helpers ───────────────────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable string."""
    if size_bytes < 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB", "PB"):
        size /= 1024.0
        if size < 1024.0:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
