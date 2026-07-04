"""
CopyForge — GUI main application.
Built with customtkinter for a modern dark UI.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

# ── Application metadata ──────────────────────────────────────────────────────
APP_VERSION = "1.0.0"
APP_DEVELOPER = "Jeysson Rostran"
APP_TITLE = "CopyForge — Advanced File Transfer"

# Setup logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('copyforge_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from engine import TransferEngine, SUPPORTED_ALGORITHMS
from models import (
    FileItem, FileStatus, JobStatus, TransferJob,
    format_size, format_duration,
)
from report import save_report

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG_DARK    = "#1a1a1a"
BG_MED     = "#242424"
BG_PANEL   = "#2b2b2b"
BG_LIGHT   = "#333333"
BG_LIGHTER = "#3c3c3c"
ACCENT     = "#0078d4"
ACCENT_H   = "#1084d8"
C_OK       = "#4caf50"
C_FAIL     = "#f44336"
C_WARN     = "#ff9800"
C_SKIP     = "#888888"
C_COPY     = "#0078d4"
C_VERIFY   = "#9c27b0"
C_TEXT     = "#ffffff"
C_DIM      = "#aaaaaa"
C_BORDER   = "#444444"

STATUS_COLOR: Dict[FileStatus, str] = {
    FileStatus.OK:           C_OK,
    FileStatus.VERIFIED:     C_OK,
    FileStatus.FAILED:       C_FAIL,
    FileStatus.HASH_MISMATCH: C_WARN,
    FileStatus.SKIPPED:      C_SKIP,
    FileStatus.COPYING:      C_COPY,
    FileStatus.VERIFYING:    C_VERIFY,
    FileStatus.PENDING:      C_BORDER,
}

STATUS_ICON: Dict[FileStatus, str] = {
    FileStatus.OK:           "✓",
    FileStatus.VERIFIED:     "✓✓",
    FileStatus.FAILED:       "✗",
    FileStatus.HASH_MISMATCH: "⚠",
    FileStatus.SKIPPED:      "—",
    FileStatus.COPYING:      "►",
    FileStatus.VERIFYING:    "◎",
    FileStatus.PENDING:      "·",
}


# ── Speed graph ───────────────────────────────────────────────────────────────

class SpeedGraph(tk.Canvas):
    """Filled area-chart showing transfer speed over the last N samples."""

    MAX_SAMPLES = 90

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            bg=BG_MED,
            highlightthickness=0,
            **kwargs,
        )
        self._samples: List[float] = []
        self.bind("<Configure>", lambda _e: self._redraw())

    def push(self, speed_bps: float):
        self._samples.append(speed_bps)
        if len(self._samples) > self.MAX_SAMPLES:
            self._samples.pop(0)
        self._redraw()

    def clear(self):
        self._samples.clear()
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2 or not self._samples:
            return

        peak = max(self._samples) or 1
        n = len(self._samples)
        step = w / max(n - 1, 1)

        pts = []
        for i, v in enumerate(self._samples):
            x = i * step
            y = h - (v / peak) * (h - 4) - 2
            pts.extend([x, y])

        # Close the polygon at the bottom
        pts.extend([pts[-2], h, 0, h])

        if len(pts) >= 6:
            self.create_polygon(pts, fill="#1565c0", outline="")
            # Top line
            line_pts = pts[: len(self._samples) * 2]
            self.create_line(line_pts, fill="#2196f3", width=2, smooth=True)

        # Y-axis label (peak speed)
        label = format_size(int(peak)) + "/s"
        self.create_text(4, 4, anchor="nw", text=label, fill=C_DIM, font=("Segoe UI", 8))


# ── File list ─────────────────────────────────────────────────────────────────

class FileListView(ttk.Frame):
    """Treeview wrapper showing the files in the current job."""

    COLS = ("icon", "path", "src_hash", "dst_hash", "size", "status")

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.configure(style="Dark.TFrame")

        # Style
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Dark.TFrame", background=BG_PANEL)
        style.configure(
            "CF.Treeview",
            background=BG_PANEL,
            foreground=C_TEXT,
            fieldbackground=BG_PANEL,
            borderwidth=0,
            rowheight=26,
            font=("Segoe UI", 9),
        )
        style.configure(
            "CF.Treeview.Heading",
            background=BG_DARK,
            foreground=C_DIM,
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "CF.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", C_TEXT)],
        )

        vsb = ttk.Scrollbar(self, orient="vertical")
        hsb = ttk.Scrollbar(self, orient="horizontal")
        self.tree = ttk.Treeview(
            self,
            columns=self.COLS,
            show="headings",
            style="CF.Treeview",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="extended",
        )
        vsb.configure(command=self.tree.yview)
        hsb.configure(command=self.tree.xview)

        self.tree.heading("icon",     text="")
        self.tree.heading("path",     text="File")
        self.tree.heading("src_hash", text="Src Hash")
        self.tree.heading("dst_hash", text="Dst Hash")
        self.tree.heading("size",     text="Size")
        self.tree.heading("status",   text="Status")

        self.tree.column("icon",     width=28,  stretch=False, anchor="center")
        self.tree.column("path",     width=420, minwidth=200)
        self.tree.column("src_hash", width=90,  stretch=False, anchor="center")
        self.tree.column("dst_hash", width=90,  stretch=False, anchor="center")
        self.tree.column("size",     width=80,  stretch=False, anchor="e")
        self.tree.column("status",   width=110, stretch=False, anchor="center")

        # Row tags for status colours
        for fs, color in STATUS_COLOR.items():
            self.tree.tag_configure(fs.name, foreground=color)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Map FileItem → row id
        self._item_ids: Dict[int, str] = {}   # id(FileItem) → iid

    def populate(self, files: List[FileItem]):
        """Clear list and add all files."""
        self.tree.delete(*self.tree.get_children())
        self._item_ids.clear()
        for fi in files:
            iid = self.tree.insert(
                "", "end",
                values=self._row_values(fi),
                tags=(fi.status.name,),
            )
            self._item_ids[id(fi)] = iid

    def update_item(self, fi: FileItem):
        """Update a single row in-place."""
        iid = self._item_ids.get(id(fi))
        if iid and self.tree.exists(iid):
            self.tree.item(iid, values=self._row_values(fi), tags=(fi.status.name,))

    def add_item(self, fi: FileItem):
        """Append a new row."""
        iid = self.tree.insert(
            "", "end",
            values=self._row_values(fi),
            tags=(fi.status.name,),
        )
        self._item_ids[id(fi)] = iid

    def get_selected_items(self, job: TransferJob) -> List[FileItem]:
        selected = []
        selected_iids = set(self.tree.selection())
        for fi in job.files:
            iid = self._item_ids.get(id(fi))
            if iid and iid in selected_iids:
                selected.append(fi)
        return selected

    def scroll_to_bottom(self):
        children = self.tree.get_children()
        if children:
            self.tree.see(children[-1])

    @staticmethod
    def _row_values(fi: FileItem):
        icon = STATUS_ICON.get(fi.status, "·")
        short = str(fi.source)
        return (icon, short, fi.src_hash_short, fi.dst_hash_short,
                fi.size_str, fi.status.value)


# ── Job card (left panel) ─────────────────────────────────────────────────────

class JobCard(ctk.CTkFrame):
    def __init__(self, parent, job: TransferJob, on_select, **kwargs):
        super().__init__(
            parent,
            corner_radius=6,
            fg_color=BG_LIGHT,
            **kwargs,
        )
        self.job = job
        self._on_select = on_select
        self._selected = False

        self._name_lbl = ctk.CTkLabel(
            self, text=job.label, font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w", text_color=C_TEXT,
        )
        self._name_lbl.grid(row=0, column=0, columnspan=2, padx=8, pady=(6, 0), sticky="ew")

        self._src_lbl = ctk.CTkLabel(
            self, text=self._short(str(job.source_path)), font=ctk.CTkFont(size=10),
            anchor="w", text_color=C_DIM,
        )
        self._src_lbl.grid(row=1, column=0, columnspan=2, padx=8, sticky="ew")

        self._dst_lbl = ctk.CTkLabel(
            self, text=self._short(str(job.target_path or "No target")),
            font=ctk.CTkFont(size=10), anchor="w", text_color=C_DIM,
        )
        self._dst_lbl.grid(row=2, column=0, columnspan=2, padx=8, sticky="ew")

        self._stat_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=10), anchor="w", text_color=C_DIM,
        )
        self._stat_lbl.grid(row=3, column=0, padx=8, pady=(0, 4), sticky="w")

        self._status_lbl = ctk.CTkLabel(
            self, text=job.status.value, font=ctk.CTkFont(size=10),
            anchor="e", text_color=C_DIM,
        )
        self._status_lbl.grid(row=3, column=1, padx=8, pady=(0, 4), sticky="e")

        self._progress = ctk.CTkProgressBar(self, height=4, corner_radius=2)
        self._progress.set(0)
        self._progress.grid(row=4, column=0, columnspan=2, padx=8, pady=(0, 6), sticky="ew")

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        # Click to select
        for widget in (self, self._name_lbl, self._src_lbl, self._dst_lbl,
                       self._stat_lbl, self._status_lbl):
            widget.bind("<Button-1>", lambda _e: self._on_select(self.job))

    @staticmethod
    def _short(path: str, max_len: int = 30) -> str:
        if len(path) > max_len:
            return "…" + path[-(max_len - 1):]
        return path

    def refresh(self):
        job = self.job
        # Status colour
        color_map = {
            JobStatus.COMPLETED: C_OK,
            JobStatus.FAILED: C_FAIL,
            JobStatus.RUNNING: ACCENT,
            JobStatus.PAUSED: C_WARN,
            JobStatus.CANCELLED: C_SKIP,
        }
        sc = color_map.get(job.status, C_DIM)
        self._status_lbl.configure(text=job.status.value, text_color=sc)

        n = len(job.files)
        if n:
            self._stat_lbl.configure(
                text=f"{n} files  {job.total_size_str}"
            )
        self._progress.set(job.progress_percent / 100)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.configure(fg_color=ACCENT if selected else BG_LIGHT)


# ── Options panel ─────────────────────────────────────────────────────────────

class OptionsPanel(ctk.CTkScrollableFrame):
    def __init__(self, parent, job: TransferJob, on_change, **kwargs):
        super().__init__(parent, fg_color=BG_PANEL, **kwargs)
        self._job = job
        self._on_change = on_change

        # ── Transfer section ──────────────────────────────────────────────────
        _head(self, "Transfer")

        self._var_subdirs = _bool_var(job.include_subdirs)
        _check(self, "Include sub-folders", self._var_subdirs)

        self._var_verify = _bool_var(job.verify_after_copy)
        _check(self, "Verify files after transfer", self._var_verify)

        _lbl(self, "Overwrite mode")
        self._ow_var = tk.StringVar(value=job.overwrite_mode)
        ow_menu = ctk.CTkOptionMenu(
            self, values=["overwrite_all", "overwrite_newer", "skip_existing"],
            variable=self._ow_var,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        )
        ow_menu.pack(fill="x", padx=8, pady=(0, 8))

        # ── Concurrency section ───────────────────────────────────────────────
        _head(self, "Concurrency")

        _lbl(self, "Parallel file transfers")
        self._workers_var = tk.StringVar(value=str(job.num_workers))
        ctk.CTkOptionMenu(
            self, values=["1", "2", "3", "4", "5", "6", "7", "8"],
            variable=self._workers_var,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        ).pack(fill="x", padx=8, pady=(0, 8))

        # ── Hash section ──────────────────────────────────────────────────────
        _head(self, "Checksum / Verification")

        _lbl(self, "Hash algorithm")
        self._hash_var = tk.StringVar(value=job.hash_algorithm)
        ctk.CTkOptionMenu(
            self, values=SUPPORTED_ALGORITHMS,
            variable=self._hash_var,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        ).pack(fill="x", padx=8, pady=(0, 8))

        # ── Retry section ─────────────────────────────────────────────────────
        _head(self, "Error Recovery")

        _lbl(self, "Max retries per file")
        self._retry_var = tk.StringVar(value=str(job.retry_count))
        ctk.CTkOptionMenu(
            self, values=["0", "1", "2", "3", "5", "10"],
            variable=self._retry_var,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        ).pack(fill="x", padx=8, pady=(0, 8))

        _lbl(self, "Buffer size (MB)")
        self._buf_var = tk.StringVar(value=str(job.buffer_size_mb))
        ctk.CTkOptionMenu(
            self, values=["1", "4", "8", "16", "32", "64"],
            variable=self._buf_var,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        ).pack(fill="x", padx=8, pady=(0, 8))

        ctk.CTkButton(
            self, text="Apply", command=self._apply,
            fg_color=ACCENT, hover_color=ACCENT_H,
        ).pack(fill="x", padx=8, pady=8)

    def _apply(self):
        j = self._job
        j.include_subdirs = bool(self._var_subdirs.get())
        j.verify_after_copy = bool(self._var_verify.get())
        j.overwrite_mode = self._ow_var.get()
        j.hash_algorithm = self._hash_var.get()
        j.retry_count = int(self._retry_var.get())
        j.buffer_size_mb = int(self._buf_var.get())
        j.num_workers = int(self._workers_var.get())
        if self._on_change:
            self._on_change()


# ── Status / speed panel ──────────────────────────────────────────────────────

class StatusPanel(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=BG_PANEL, **kwargs)

        self.graph = SpeedGraph(self, height=160)
        self.graph.pack(fill="x", padx=10, pady=(10, 6))

        # Stats table
        cols = ("category", "files", "bytes", "time")
        style = ttk.Style(self)
        style.configure("Stats.Treeview",
                        background=BG_MED, foreground=C_TEXT,
                        fieldbackground=BG_MED, rowheight=24,
                        font=("Segoe UI", 10))
        style.configure("Stats.Treeview.Heading",
                        background=BG_DARK, foreground=C_DIM,
                        font=("Segoe UI", 10, "bold"))
        style.map("Stats.Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", C_TEXT)])

        self.stats_tree = ttk.Treeview(
            self, columns=cols, show="headings",
            style="Stats.Treeview", height=5,
        )
        for col, heading, w in [
            ("category", "Category", 120),
            ("files",    "Files",    80),
            ("bytes",    "Bytes",    160),
            ("time",     "Time",     100),
        ]:
            self.stats_tree.heading(col, text=heading)
            self.stats_tree.column(col, width=w, stretch=(col == "bytes"), anchor="center")

        self.stats_tree.pack(fill="x", padx=10, pady=(0, 10))
        self._row_ids: Dict[str, str] = {}

    def init_stats(self):
        self.stats_tree.delete(*self.stats_tree.get_children())
        self._row_ids.clear()
        for cat in ("OK", "Verified", "Failed", "---", "Total"):
            iid = self.stats_tree.insert("", "end", values=(cat, 0, 0, "00:00:00"))
            self._row_ids[cat] = iid

    def update_stats(self, job: TransferJob):
        def _upd(cat, files, size, dur):
            iid = self._row_ids.get(cat)
            if iid:
                self.stats_tree.item(
                    iid, values=(cat, files, format_size(size), format_duration(dur))
                )

        ok_f  = [f for f in job.files if f.status in (FileStatus.OK,)]
        ver_f = [f for f in job.files if f.status == FileStatus.VERIFIED]
        fail_f= [f for f in job.files if f.status in (FileStatus.FAILED, FileStatus.HASH_MISMATCH)]

        ok_size   = sum(f.bytes_copied for f in ok_f)
        ver_size  = sum(f.bytes_copied for f in ver_f)
        fail_size = sum(f.size for f in fail_f)
        total_size= sum(f.bytes_copied for f in job.files)

        ok_time   = sum(f.transfer_time for f in ok_f)
        ver_time  = sum(f.transfer_time for f in ver_f)

        _upd("OK",       len(ok_f),   ok_size,    ok_time)
        _upd("Verified", len(ver_f),  ver_size,   ver_time)
        _upd("Failed",   len(fail_f), fail_size,  0)
        _upd("Total",    len(job.files), total_size, job.duration)


# ── Log panel ─────────────────────────────────────────────────────────────────

class LogPanel(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=BG_PANEL, **kwargs)

        self.text = tk.Text(
            self,
            bg=BG_MED, fg=C_DIM,
            font=("Consolas", 9),
            wrap="none",
            relief="flat",
            insertbackground=C_TEXT,
            state="disabled",
        )
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)

        self.text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        vsb.pack(side="right", fill="y", padx=(0, 6), pady=6)

    def set_lines(self, lines: List[str]):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(lines))
        self.text.configure(state="disabled")
        self.text.see("end")

    def append(self, line: str):
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


# ── Main application ──────────────────────────────────────────────────────────

class App(ctk.CTk):
    POLL_MS = 120    # UI refresh interval

    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1200x760")
        self.minsize(900, 600)
        self.configure(fg_color=BG_DARK)

        # State
        self._jobs: List[TransferJob] = []
        self._active_job: Optional[TransferJob] = None
        self._engine = TransferEngine()
        self._job_cards: Dict[str, JobCard] = {}      # job_id → card
        self._last_log_len = 0
        self._current_speed = 0.0

        self._wire_engine()
        self._build_ui()
        # Initialize buttons as disabled (no job running yet)
        self._update_button_states(job_running=False)
        self._start_poll()

    # ── Engine wiring ─────────────────────────────────────────────────────────

    def _wire_engine(self):
        e = self._engine

        def _on_scan_done(job):
            self.after(0, lambda: self._on_scan_done(job))

        def _on_file_start(fi, job):
            self.after(0, lambda: self._on_file_start(fi, job))

        def _on_file_progress(fi, done, speed):
            self.after(0, lambda: self._on_file_progress(fi, done, speed))

        def _on_file_done(fi, job):
            self.after(0, lambda: self._on_file_done(fi, job))

        def _on_job_done(job):
            self.after(0, lambda: self._on_job_done(job))

        def _on_speed(bps):
            self._current_speed = bps
            self.after(0, lambda: self._speed_panel.graph.push(bps))

        e.on_scan_done     = _on_scan_done
        e.on_file_start    = _on_file_start
        e.on_file_progress = _on_file_progress
        e.on_file_done     = _on_file_done
        e.on_job_done      = _on_job_done
        e.on_speed_sample  = _on_speed

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top toolbar ───────────────────────────────────────────────────────
        tb = ctk.CTkFrame(self, fg_color=BG_MED, height=48, corner_radius=0)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        logo = ctk.CTkLabel(tb, text="  ⬡  CopyForge",
                            font=ctk.CTkFont(size=15, weight="bold"),
                            text_color=C_TEXT)
        logo.pack(side="left", padx=12)

        btn_cfg = dict(width=38, height=32, corner_radius=4,
                       fg_color=BG_LIGHTER, hover_color=BG_LIGHT, text_color=C_TEXT,
                       font=ctk.CTkFont(size=14))

        ctk.CTkButton(tb, text="＋", command=self._add_job, **btn_cfg).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(tb, text="⟳", command=self._rescan_job, **btn_cfg).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(tb, text="🗂", command=self._open_dest_folder, **btn_cfg).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(tb, text="📋", command=self._export_report, **btn_cfg).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(tb, text="✕", command=self._remove_job, **btn_cfg).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(tb, text="ℹ", command=self._show_about, **btn_cfg).pack(side="left", padx=2, pady=8)

        # On-finish dropdown
        self._finish_var = tk.StringVar(value="Keep app open")
        ctk.CTkOptionMenu(
            tb,
            values=["Keep app open", "Close when done", "Shutdown when done"],
            variable=self._finish_var,
            width=180, height=30,
            fg_color=BG_LIGHTER, button_color=BG_LIGHTER,
        ).pack(side="right", padx=12, pady=8)
        ctk.CTkLabel(tb, text="On finish:", text_color=C_DIM,
                     font=ctk.CTkFont(size=10)).pack(side="right", padx=(0, 2))

        # ── Main split ────────────────────────────────────────────────────────
        split = ctk.CTkFrame(self, fg_color=BG_DARK)
        split.pack(fill="both", expand=True)

        # Left job queue
        left = ctk.CTkFrame(split, fg_color=BG_MED, width=250, corner_radius=0)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="Job Queue", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C_DIM, anchor="w").pack(fill="x", padx=10, pady=(8, 4))

        self._job_list = ctk.CTkScrollableFrame(left, fg_color=BG_MED, corner_radius=0)
        self._job_list.pack(fill="both", expand=True, padx=4, pady=4)

        # Right detail
        right = ctk.CTkFrame(split, fg_color=BG_DARK, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        self._build_detail(right)

    def _build_detail(self, parent):
        # ── Progress area ─────────────────────────────────────────────────────
        prog_frame = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=0, height=120)
        prog_frame.pack(fill="x")
        prog_frame.pack_propagate(False)

        # Current file copy bar
        copy_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        copy_row.pack(fill="x", padx=10, pady=(8, 2))

        self._copy_badge = ctk.CTkLabel(
            copy_row, text="  Copying  ",
            fg_color=ACCENT, corner_radius=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="white", width=70,
        )
        self._copy_badge.pack(side="left")

        self._copy_path_lbl = ctk.CTkLabel(
            copy_row, text="—", anchor="w",
            font=ctk.CTkFont(size=10), text_color=C_TEXT,
        )
        self._copy_path_lbl.pack(side="left", padx=8, fill="x", expand=True)

        self._copy_count_lbl = ctk.CTkLabel(
            copy_row, text="", anchor="e",
            font=ctk.CTkFont(size=10), text_color=C_DIM,
        )
        self._copy_count_lbl.pack(side="right", padx=4)

        self._copy_bar = ctk.CTkProgressBar(
            prog_frame, height=6, corner_radius=2,
            progress_color=ACCENT,
        )
        self._copy_bar.set(0)
        self._copy_bar.pack(fill="x", padx=10, pady=(0, 4))

        # Target/overall bar
        tgt_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        tgt_row.pack(fill="x", padx=10, pady=(0, 2))

        self._tgt_badge = ctk.CTkLabel(
            tgt_row, text="  Target  ",
            fg_color=BG_LIGHTER, corner_radius=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C_DIM, width=70,
        )
        self._tgt_badge.pack(side="left")

        self._tgt_path_lbl = ctk.CTkLabel(
            tgt_row, text="—", anchor="w",
            font=ctk.CTkFont(size=10), text_color=C_DIM,
        )
        self._tgt_path_lbl.pack(side="left", padx=8, fill="x", expand=True)

        self._tgt_speed_lbl = ctk.CTkLabel(
            tgt_row, text="", anchor="e",
            font=ctk.CTkFont(size=10), text_color=C_DIM,
        )
        self._tgt_speed_lbl.pack(side="right", padx=4)

        self._tgt_bar = ctk.CTkProgressBar(
            prog_frame, height=6, corner_radius=2,
            progress_color=C_OK,
        )
        self._tgt_bar.set(0)
        self._tgt_bar.pack(fill="x", padx=10, pady=(0, 6))

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(parent, fg_color=BG_PANEL, height=44, corner_radius=0)
        btn_row.pack(fill="x")
        btn_row.pack_propagate(False)

        b_cfg = dict(width=90, height=30, corner_radius=4,
                     fg_color=BG_LIGHTER, hover_color=BG_LIGHT, text_color=C_TEXT)
        self._pause_btn = ctk.CTkButton(btn_row, text="Pause",
                                        command=self._toggle_pause, **b_cfg)
        self._pause_btn.pack(side="left", padx=(10, 4), pady=6)
        
        self._skip_btn = ctk.CTkButton(btn_row, text="Skip", command=self._skip_file, **b_cfg)
        self._skip_btn.pack(side="left", padx=4, pady=6)
        
        self._stop_btn = ctk.CTkButton(btn_row, text="Stop", command=self._stop_job,
                      fg_color="#7b1c1c", hover_color="#9e2424",
                      width=90, height=30, corner_radius=4, text_color=C_TEXT,
                      )
        self._stop_btn.pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(btn_row, text="", width=20).pack(side="left")

        self._verify_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            btn_row, text="Verify", variable=self._verify_var,
            font=ctk.CTkFont(size=11), text_color=C_DIM,
            command=self._toggle_verify,
        ).pack(side="right", padx=16, pady=6)

        self._unattended_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            btn_row, text="Unattended", variable=self._unattended_var,
            font=ctk.CTkFont(size=11), text_color=C_DIM,
        ).pack(side="right", padx=8, pady=6)

        # Separator
        sep = ctk.CTkFrame(parent, fg_color=C_BORDER, height=1, corner_radius=0)
        sep.pack(fill="x")

        # ── Tab view ──────────────────────────────────────────────────────────
        self._tabs = ctk.CTkTabview(
            parent,
            fg_color=BG_PANEL,
            segmented_button_fg_color=BG_MED,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color=BG_MED,
            segmented_button_unselected_hover_color=BG_LIGHTER,
            text_color=C_DIM,
        )
        self._tabs.pack(fill="both", expand=True)

        for tab_name in ("File List", "Options", "Status", "Log"):
            self._tabs.add(tab_name)

        # File List tab
        self._file_list = FileListView(self._tabs.tab("File List"))
        self._file_list.pack(fill="both", expand=True)

        # Options tab (placeholder until a job is selected)
        self._options_frame = ctk.CTkFrame(
            self._tabs.tab("Options"), fg_color=BG_PANEL)
        self._options_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(
            self._options_frame,
            text="Select or add a job to configure options.",
            text_color=C_DIM,
        ).pack(expand=True)

        # Status tab
        self._speed_panel = StatusPanel(self._tabs.tab("Status"))
        self._speed_panel.pack(fill="both", expand=True)
        self._speed_panel.init_stats()

        # Log tab
        self._log_panel = LogPanel(self._tabs.tab("Log"))
        self._log_panel.pack(fill="both", expand=True)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _start_poll(self):
        self._poll()

    def _poll(self):
        job = self._active_job
        if job:
            self._refresh_progress(job)
            self._refresh_job_card(job)
            self._sync_log(job)
        self.after(self.POLL_MS, self._poll)

    def _refresh_progress(self, job: TransferJob):
        # Find current file
        current_fi: Optional[FileItem] = None
        for fi in reversed(job.files):
            if fi.status in (FileStatus.COPYING, FileStatus.VERIFYING):
                current_fi = fi
                break

        done = job.ok_files + job.failed_files + job.skipped_files
        total = len(job.files)

        if current_fi:
            name = current_fi.source.name
            self._copy_path_lbl.configure(text=name)
            self._tgt_path_lbl.configure(
                text=str(current_fi.target) if current_fi.target else "—"
            )
            # Per-file progress
            pct = (current_fi.bytes_copied / current_fi.size) if current_fi.size else 0
            self._copy_bar.set(min(pct, 1.0))
            # Count
            self._copy_count_lbl.configure(
                text=f"{done}/{total}  {format_size(current_fi.size)}  "
                     f"{format_size(job.transferred_size)}  "
                     f"{job.progress_percent:.1f}%"
            )
            
            # Calculate ETA
            remaining_bytes = job.total_size - job.transferred_size
            eta_str = ""
            if self._current_speed > 0 and remaining_bytes > 0:
                eta_seconds = remaining_bytes / self._current_speed
                hours = int(eta_seconds // 3600)
                minutes = int((eta_seconds % 3600) // 60)
                seconds = int(eta_seconds % 60)
                if hours > 0:
                    eta_str = f" ETA: {hours}h {minutes}m"
                elif minutes > 0:
                    eta_str = f" ETA: {minutes}m {seconds}s"
                else:
                    eta_str = f" ETA: {seconds}s"
            
            # Speed with ETA
            speed_str = format_size(int(self._current_speed)) + "/s " if self._current_speed else ""
            self._tgt_speed_lbl.configure(
                text=speed_str + eta_str + f"  {format_size(job.transferred_size)}/"
                     f"{format_size(job.total_size)}  "
                     f"{job.progress_percent:.1f}%"
            )
            badge_map = {
                FileStatus.COPYING:   ("  Copying  ",   ACCENT),
                FileStatus.VERIFYING: ("  Verifying  ", C_VERIFY),
            }
            txt, clr = badge_map.get(current_fi.status, ("  Copying  ", ACCENT))
            self._copy_badge.configure(text=txt, fg_color=clr)

        # Overall bar - use job progress percentage
        overall_pct = job.progress_percent / 100
        self._tgt_bar.set(overall_pct)
        # Force redraw of progress bars
        self._copy_bar.update()
        self._tgt_bar.update()

        # Stats panel
        self._speed_panel.update_stats(job)

    def _refresh_job_card(self, job: TransferJob):
        card = self._job_cards.get(job.job_id)
        if card:
            card.refresh()

    def _sync_log(self, job: TransferJob):
        if len(job.log_lines) != self._last_log_len:
            self._log_panel.set_lines(job.log_lines)
            self._last_log_len = len(job.log_lines)

    # ── Engine callbacks ──────────────────────────────────────────────────────

    def _on_scan_done(self, job: TransferJob):
        if job is not self._active_job:
            return
        self._file_list.populate(job.files)
        card = self._job_cards.get(job.job_id)
        if card:
            card.refresh()
        self._speed_panel.init_stats()

    def _on_file_start(self, fi: FileItem, job: TransferJob):
        if job is not self._active_job:
            return
        # Add to list if scan happened incrementally
        if id(fi) not in self._file_list._item_ids:
            self._file_list.add_item(fi)
        self._file_list.update_item(fi)

    def _on_file_progress(self, fi: FileItem, _done: int, _speed: float):
        # O(1) lookup via id dict — avoids expensive dataclass __eq__ on full list
        if id(fi) in self._file_list._item_ids:
            self._file_list.update_item(fi)

    def _on_file_done(self, fi: FileItem, job: TransferJob):
        if job is not self._active_job:
            return
        self._file_list.update_item(fi)

    def _on_job_done(self, job: TransferJob):
        self._refresh_job_card(job)
        self._refresh_progress(job)
        self._current_speed = 0.0
        
        # Disable control buttons when job is done
        self._update_button_states(job_running=False)

        status_msg = {
            JobStatus.COMPLETED: f"✓  Transfer complete — {job.ok_files} files OK",
            JobStatus.FAILED:    f"✗  Transfer finished with {job.failed_files} errors",
            JobStatus.CANCELLED: "Transfer cancelled",
        }.get(job.status, "Transfer finished")

        self._copy_path_lbl.configure(text=status_msg)

        if not self._verify_var.get():
            pass   # no-verify note already in log

        # Auto on-finish
        finish = self._finish_var.get()
        if finish == "Close when done" and job.status == JobStatus.COMPLETED:
            self.after(2000, self.destroy)
        elif finish == "Shutdown when done" and job.status == JobStatus.COMPLETED:
            self.after(2000, lambda: os.system("shutdown /s /t 30"))

        # Start next queued job
        self._run_next_job()

    def _update_button_states(self, job_running: bool):
        """Enable/disable control buttons based on job state."""
        state = "normal" if job_running else "disabled"
        self._pause_btn.configure(state=state)
        self._skip_btn.configure(state=state)
        self._stop_btn.configure(state=state)

    # ── Job management ────────────────────────────────────────────────────────

    def _bring_to_front(self):
        """Prepare window for dialog opening."""
        self.lift()
        self.focus_force()
        self.update()

    def _open_dialog(self, dialog_func, **kwargs):
        """Open a file dialog with proper window management."""
        logger.debug(f"Opening dialog: {kwargs.get('title', 'untitled')}")
        
        # Ensure the main window is visible and focused before dialog
        self.deiconify()
        self.update()
        
        try:
            # Open dialog without parent to avoid layering issues with customtkinter
            # Remove parent if it was passed in
            kwargs.pop('parent', None)
            
            result = dialog_func(**kwargs)
            logger.info(f"Dialog closed, result: {result}")
            
            # Ensure main window is visible and focused after dialog closes
            self.update()
            self.lift()
            self.focus_force()
            
            return result
        except Exception as e:
            logger.error(f"Dialog error: {e}", exc_info=True)
            raise

    def _choose_source_kind(self) -> Optional[str]:
        """Show a themed modal that asks whether the source is files or a folder."""
        choice = tk.StringVar(value="")

        dlg = ctk.CTkToplevel(self)
        dlg.title("Add source")
        dlg.configure(fg_color=BG_DARK)
        dlg.resizable(False, False)
        dlg.transient(self)

        w, h = 420, 230
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        def pick(value: str):
            choice.set(value)
            dlg.destroy()

        def cancel():
            choice.set("")
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", cancel)

        wrap = ctk.CTkFrame(dlg, fg_color=BG_PANEL, corner_radius=8)
        wrap.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            wrap,
            text="Add Source",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=C_TEXT,
            anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 4))

        ctk.CTkLabel(
            wrap,
            text="Choose what you want to copy. You will select the destination next.",
            font=ctk.CTkFont(size=12),
            text_color=C_DIM,
            anchor="w",
            justify="left",
            wraplength=360,
        ).pack(fill="x", padx=18, pady=(0, 16))

        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 14))

        button_font = ctk.CTkFont(size=13, weight="bold")
        ctk.CTkButton(
            row,
            text="Files",
            command=lambda: pick("files"),
            height=46,
            corner_radius=6,
            fg_color=ACCENT,
            hover_color=ACCENT_H,
            text_color=C_TEXT,
            font=button_font,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            row,
            text="Folder",
            command=lambda: pick("folder"),
            height=46,
            corner_radius=6,
            fg_color=BG_LIGHTER,
            hover_color=BG_LIGHT,
            text_color=C_TEXT,
            font=button_font,
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        ctk.CTkButton(
            wrap,
            text="Cancel",
            command=cancel,
            width=96,
            height=32,
            corner_radius=4,
            fg_color=BG_LIGHT,
            hover_color=BG_LIGHTER,
            text_color=C_DIM,
        ).pack(anchor="e", padx=18, pady=(0, 16))

        dlg.grab_set()
        dlg.focus_force()
        dlg.wait_window()
        return choice.get() or None

    def _add_job(self):
        """Add a new transfer job via file dialogs."""
        logger.info("=== _add_job() START ===")

        source_kind = self._choose_source_kind()
        if source_kind is None:
            logger.info("Source type selection cancelled")
            return
        
        if source_kind == "files":
            logger.debug("Opening source files dialog")
            self._bring_to_front()
            src_files = self._open_dialog(
                filedialog.askopenfilenames,
                title="Choose files to copy",
                filetypes=[("All files", "*.*")],
            )
            logger.info(f"Files dialog result: {len(src_files)} files")
            
            if not src_files:
                logger.info("No files selected - aborting job creation")
                return
            
            # Multiple files → use first file's parent as job name
            src_path = Path(src_files[0]).parent
            job = TransferJob(source_path=src_path, target_path=None)
            job.label = f"{len(src_files)} files from {src_path.name}"
            
            logger.debug("Opening target folder dialog for files")
            self._bring_to_front()
            dst = self._open_dialog(
                filedialog.askdirectory,
                title="Choose destination folder",
            )
            logger.info(f"Target dialog result: {dst}")
            
            if not dst:
                logger.info("No target selected - aborting")
                return
                
            job.target_path = Path(dst)
            try:
                for p in src_files:
                    fp = Path(p)
                    job.files.append(FileItem(
                        source=fp,
                        target=job.target_path / fp.name,
                        size=fp.stat().st_size,
                    ))
            except OSError as exc:
                logger.error(f"Unable to read selected file metadata: {exc}", exc_info=True)
                messagebox.showerror(
                    "CopyForge",
                    f"Unable to read one of the selected files:\n\n{exc}",
                    parent=self,
                )
                return
        else:
            logger.debug("Opening source folder dialog")
            self._bring_to_front()
            src = self._open_dialog(
                filedialog.askdirectory,
                title="Choose folder to copy",
            )
            logger.info(f"Source dialog result: {src}")

            if not src:
                logger.info("No folder selected - aborting job creation")
                return

            logger.debug("Folder selected, opening target folder dialog")
            src_path = Path(src)
            self._bring_to_front()
            dst = self._open_dialog(
                filedialog.askdirectory,
                title="Choose destination folder",
            )
            logger.info(f"Target dialog result: {dst}")
            
            if not dst:
                logger.info("No target selected - aborting")
                return
                
            job = TransferJob(source_path=src_path, target_path=Path(dst))

        job.verify_after_copy = self._verify_var.get()
        logger.debug(f"Job created: {job.label}")

        self._jobs.append(job)
        self._add_job_card(job)
        self._select_job(job)
        logger.info("Job added to queue")

        if not self._engine.is_running():
            self._run_next_job()
        
        logger.info("=== _add_job() END ===")

    def _add_job_card(self, job: TransferJob):
        card = JobCard(self._job_list, job, on_select=self._select_job)
        card.pack(fill="x", pady=2)
        self._job_cards[job.job_id] = card
        card.refresh()

    def _select_job(self, job: TransferJob):
        self._active_job = job
        self._last_log_len = 0
        for jid, card in self._job_cards.items():
            card.set_selected(jid == job.job_id)

        self._file_list.populate(job.files)
        self._log_panel.set_lines(job.log_lines)
        self._speed_panel.init_stats()
        self._speed_panel.update_stats(job)
        self._rebuild_options(job)

    def _rebuild_options(self, job: TransferJob):
        for w in self._options_frame.winfo_children():
            w.destroy()
        OptionsPanel(self._options_frame, job, on_change=None).pack(
            fill="both", expand=True)

    def _run_next_job(self):
        if self._engine.is_running():
            return
        for job in self._jobs:
            if job.status == JobStatus.PENDING:
                self._active_job = job
                for jid, card in self._job_cards.items():
                    card.set_selected(jid == job.job_id)
                self._file_list.populate(job.files)
                self._speed_panel.init_stats()
                self._speed_panel.graph.clear()
                self._current_speed = 0.0
                self._last_log_len = 0
                # Set worker count from job
                self._engine.num_workers = job.num_workers
                self._engine.start(job)
                # Enable control buttons when job starts
                self._update_button_states(job_running=True)
                break

    def _remove_job(self):
        job = self._active_job
        if job is None:
            return
        if job.status == JobStatus.RUNNING:
            messagebox.showwarning("CopyForge", "Stop the transfer before removing it.")
            return
        card = self._job_cards.pop(job.job_id, None)
        if card:
            card.destroy()
        self._jobs.remove(job)
        self._active_job = None
        if self._jobs:
            self._select_job(self._jobs[-1])
        else:
            self._file_list.populate([])
            self._log_panel.clear()

    def _rescan_job(self):
        job = self._active_job
        if job is None:
            return
        if self._engine.is_running() and job.status == JobStatus.RUNNING:
            messagebox.showinfo("CopyForge", "Pause or stop the transfer before rescanning.")
            return
        # Clear pending files, keep completed ones
        job.files = [f for f in job.files
                     if f.status in (FileStatus.OK, FileStatus.VERIFIED,
                                     FileStatus.SKIPPED)]
        job.status = JobStatus.PENDING
        job.error_message = ""
        job.add_log("--- Rescan ---")
        self._select_job(job)
        if not self._engine.is_running():
            self._engine.start(job)

    def _show_about(self):
        """Show about dialog with version and developer info."""
        about_text = f"""{APP_TITLE}

Version: {APP_VERSION}
Developer: {APP_DEVELOPER}

Advanced file transfer utility with:
• Parallel file transfers (1-8 concurrent workers)
• Hash verification (BLAKE3, SHA256, SHA512, SHA1, MD5)
• Network share support (UNC paths)
• Pause / Resume / Cancel / Skip controls
• HTML & CSV reporting
• Error recovery with automatic retries

Built with Python 3.14 • customtkinter 6.0.0
"""
        messagebox.showinfo(APP_TITLE, about_text)

    # ── Transfer controls ─────────────────────────────────────────────────────

    def _toggle_pause(self):
        job = self._active_job
        if job is None:
            return
        if job.status == JobStatus.PAUSED:
            job.status = JobStatus.RUNNING
            self._engine.resume()
            self._pause_btn.configure(text="Pause")
        elif job.status == JobStatus.RUNNING:
            job.status = JobStatus.PAUSED
            self._engine.pause()
            self._pause_btn.configure(text="Resume")

    def _skip_file(self):
        """Signal the engine to skip the file currently being copied."""
        if self._engine.is_running():
            self._engine.skip_current()

    def _stop_job(self):
        if messagebox.askyesno("CopyForge", "Stop the current transfer?"):
            self._engine.cancel()
            self._pause_btn.configure(text="Pause")

    def _toggle_verify(self):
        if self._active_job:
            self._active_job.verify_after_copy = self._verify_var.get()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _open_dest_folder(self):
        job = self._active_job
        if job and job.target_path and job.target_path.exists():
            os.startfile(str(job.target_path))

    def _export_report(self):
        job = self._active_job
        if job is None:
            messagebox.showinfo("CopyForge", "No job selected.")
            return
        
        logger.info("=== _export_report() START ===")
        self._bring_to_front()
        
        logger.debug("Opening save dialog")
        path = self._open_dialog(
            filedialog.asksaveasfilename,
            defaultextension=".html",
            filetypes=[("HTML Report", "*.html"), ("CSV Report", "*.csv")],
            initialfile=f"CopyForge_{job.label}",
            title="Export Report",
        )
        logger.info(f"Save dialog result: {path}")
        
        if not path:
            logger.info("No path selected - aborting export")
            return
        
        fmt = "csv" if path.lower().endswith(".csv") else "html"
        logger.debug(f"Report format: {fmt}")
        
        try:
            logger.debug(f"Saving report to {path}")
            save_report(job, Path(path), fmt=fmt)
            logger.info(f"Report saved: {path}")
            
            if messagebox.askyesno("CopyForge", f"Report saved.\nOpen {Path(path).name}?"):
                logger.debug(f"Opening file: {path}")
                os.startfile(path)
        except Exception as exc:
            logger.error(f"Failed to save report: {exc}", exc_info=True)
            messagebox.showerror("CopyForge", f"Failed to save report:\n{exc}")
        
        logger.info("=== _export_report() END ===")


# ── Small helpers ─────────────────────────────────────────────────────────────

def _head(parent, text: str):
    ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(size=11, weight="bold"),
        text_color=C_TEXT, anchor="w",
    ).pack(fill="x", padx=8, pady=(12, 2))


def _lbl(parent, text: str):
    ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(size=10), text_color=C_DIM, anchor="w",
    ).pack(fill="x", padx=8, pady=(4, 0))


def _check(parent, text: str, var: tk.BooleanVar):
    ctk.CTkCheckBox(
        parent, text=text, variable=var,
        font=ctk.CTkFont(size=11), text_color=C_TEXT,
    ).pack(anchor="w", padx=8, pady=2)


def _bool_var(value: bool) -> tk.BooleanVar:
    v = tk.BooleanVar()
    v.set(value)
    return v
