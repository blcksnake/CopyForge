"""
Report generation for CopyForge.
Exports job results as HTML or CSV.
"""
from __future__ import annotations

import csv
import html as _html
import io
import time
from pathlib import Path

from models import TransferJob, FileStatus, format_size, format_duration


# ── CSS / HTML template ───────────────────────────────────────────────────────

_HTML_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;background:#1a1a1a;color:#ddd;margin:0;padding:20px}
h1{color:#fff;font-size:1.4em;margin-bottom:4px}
.meta{color:#888;font-size:.85em;margin-bottom:20px}
.summary{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.card{background:#2b2b2b;border-radius:6px;padding:14px 20px;min-width:120px;text-align:center}
.card .val{font-size:1.8em;font-weight:700;color:#fff}
.card .lbl{font-size:.78em;color:#888;margin-top:2px}
.ok   .val{color:#4caf50}
.fail .val{color:#f44336}
.warn .val{color:#ff9800}
.skip .val{color:#888}
table{width:100%;border-collapse:collapse;font-size:.85em}
thead th{background:#111;color:#aaa;padding:8px 10px;text-align:left;position:sticky;top:0}
tbody tr:nth-child(even){background:#242424}
tbody tr:hover{background:#333}
td{padding:6px 10px;vertical-align:middle;word-break:break-all}
.s-ok{color:#4caf50}
.s-verified{color:#4caf50}
.s-failed{color:#f44336}
.s-mismatch{color:#ff9800}
.s-skipped{color:#888}
.s-pending{color:#666}
.hash{font-family:Consolas,monospace;font-size:.8em;color:#aaa}
"""

_STATUS_CLASS = {
    FileStatus.OK:           "s-ok",
    FileStatus.VERIFIED:     "s-verified",
    FileStatus.FAILED:       "s-failed",
    FileStatus.HASH_MISMATCH:"s-mismatch",
    FileStatus.SKIPPED:      "s-skipped",
    FileStatus.PENDING:      "s-pending",
    FileStatus.COPYING:      "s-pending",
    FileStatus.VERIFYING:    "s-pending",
}

_STATUS_ICON = {
    FileStatus.OK:           "✓",
    FileStatus.VERIFIED:     "✓✓",
    FileStatus.FAILED:       "✗",
    FileStatus.HASH_MISMATCH:"⚠",
    FileStatus.SKIPPED:      "—",
    FileStatus.PENDING:      "·",
    FileStatus.COPYING:      "►",
    FileStatus.VERIFYING:    "◎",
}


def _esc(s: str) -> str:
    return _html.escape(str(s))


def generate_html_report(job: TransferJob) -> str:
    """Return a complete HTML document as a string."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    total_bytes = sum(f.size for f in job.files if f.status != FileStatus.SKIPPED)
    verified_files = sum(1 for f in job.files if f.status == FileStatus.VERIFIED)

    rows_html = []
    for fi in job.files:
        sc = _STATUS_CLASS.get(fi.status, "")
        icon = _STATUS_ICON.get(fi.status, "")
        src_h = fi.src_hash_short if fi.src_hash else "----:----"
        dst_h = fi.dst_hash_short if fi.dst_hash else "----:----"
        match_cls = ""
        if fi.src_hash and fi.dst_hash:
            match_cls = "s-ok" if fi.src_hash == fi.dst_hash else "s-mismatch"

        err = f'<br><span style="color:#f66;font-size:.8em">{_esc(fi.error_message)}</span>' if fi.error_message else ""

        rows_html.append(
            f"<tr>"
            f'<td class="{sc}">{icon} {_esc(str(fi.source))}{err}</td>'
            f'<td class="hash">{_esc(src_h)}</td>'
            f'<td class="hash {match_cls}">{_esc(dst_h)}</td>'
            f'<td style="text-align:right">{_esc(fi.size_str)}</td>'
            f'<td class="{sc}">{_esc(fi.status.value)}</td>'
            f"</tr>"
        )

    rows = "\n".join(rows_html)
    src_label = _esc(str(job.source_path))
    dst_label = _esc(str(job.target_path or "—"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CopyForge Report — {_esc(job.label)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<h1>CopyForge Transfer Report</h1>
<div class="meta">
  Generated: {ts} &nbsp;|&nbsp;
  Job: {_esc(job.label)} &nbsp;|&nbsp;
  Algorithm: {_esc(job.hash_algorithm)} &nbsp;|&nbsp;
  Duration: {format_duration(job.duration)}
</div>
<div class="meta">
  Source: <strong>{src_label}</strong><br>
  Target: <strong>{dst_label}</strong>
</div>
<div class="summary">
  <div class="card ok">
    <div class="val">{job.ok_files}</div><div class="lbl">OK</div>
  </div>
  <div class="card ok">
    <div class="val">{verified_files}</div><div class="lbl">Verified</div>
  </div>
  <div class="card fail">
    <div class="val">{job.failed_files}</div><div class="lbl">Failed</div>
  </div>
  <div class="card skip">
    <div class="val">{job.skipped_files}</div><div class="lbl">Skipped</div>
  </div>
  <div class="card">
    <div class="val">{len(job.files)}</div><div class="lbl">Total Files</div>
  </div>
  <div class="card">
    <div class="val">{format_size(total_bytes)}</div><div class="lbl">Total Size</div>
  </div>
</div>
<table>
<thead>
  <tr>
    <th>File</th>
    <th>Src Hash</th>
    <th>Dst Hash</th>
    <th>Size</th>
    <th>Status</th>
  </tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def generate_csv_report(job: TransferJob) -> str:
    """Return CSV content as a string."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    # Header block
    writer.writerow(["CopyForge Transfer Report"])
    writer.writerow(["Generated", time.strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["Job", job.label])
    writer.writerow(["Source", str(job.source_path)])
    writer.writerow(["Target", str(job.target_path or "")])
    writer.writerow(["Hash Algorithm", job.hash_algorithm])
    writer.writerow(["Duration", format_duration(job.duration)])
    writer.writerow(["OK", job.ok_files])
    writer.writerow(["Failed", job.failed_files])
    writer.writerow(["Skipped", job.skipped_files])
    writer.writerow(["Total Files", len(job.files)])
    writer.writerow([])

    # File rows
    writer.writerow(["Source Path", "Target Path", "Size (bytes)", "Source Hash",
                     "Dest Hash", "Hash Match", "Status", "Error"])
    for fi in job.files:
        match = ""
        if fi.src_hash and fi.dst_hash:
            match = "YES" if fi.src_hash == fi.dst_hash else "NO"
        writer.writerow([
            str(fi.source),
            str(fi.target or ""),
            fi.size,
            fi.src_hash,
            fi.dst_hash,
            match,
            fi.status.value,
            fi.error_message,
        ])

    return buf.getvalue()


def save_report(job: TransferJob, output_path: Path, fmt: str = "html"):
    """Save report to *output_path*. *fmt* is 'html' or 'csv'."""
    if fmt.lower() == "csv":
        content = generate_csv_report(job)
        encoding = "utf-8-sig"   # BOM for Excel compatibility
    else:
        content = generate_html_report(job)
        encoding = "utf-8"
    output_path.write_text(content, encoding=encoding)
