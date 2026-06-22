"""Cron job management — wraps the OS crontab to schedule hydrabrain commands.

Jobs are stored as normal crontab entries, tagged with a marker comment
so we can identify and manage them. Works on macOS and Linux.
"""
from __future__ import annotations

import hashlib
import re
import subprocess

_MARKER = "# hydrabrain-managed"
_ID_RE = re.compile(r"id=([a-f0-9]+)")


# crontab can block on a macOS TCC/Full-Disk-Access prompt the first time it's
# touched (especially on WRITE). Bound every call so a command never hangs forever.
_TIMEOUT = 10


def _read_crontab() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("`crontab` not found — OS cron isn't available in this environment.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("`crontab -l` timed out — likely a macOS permission prompt. "
                           "Grant your terminal Full Disk Access, or use OS cron directly.")
    # exit 1 with "no crontab" is normal for a fresh user
    return r.stdout if r.returncode == 0 else ""


def _write_crontab(content: str) -> None:
    try:
        p = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True, timeout=_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("`crontab` not found — OS cron isn't available in this environment.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("`crontab` write timed out — grant your terminal Full Disk Access "
                           "(macOS System Settings → Privacy & Security), then retry.")
    if p.returncode != 0:
        raise RuntimeError(f"crontab write failed: {p.stderr.strip()}")


def list_jobs() -> list[dict]:
    jobs = []
    for line in _read_crontab().splitlines():
        if _MARKER not in line:
            continue
        m = _ID_RE.search(line)
        job_id = m.group(1) if m else "?"
        cmd_part = re.sub(r"\s*#.*$", "", line).strip()
        # split cron expr (5 fields) from the command
        parts = cmd_part.split(None, 5)
        expr = " ".join(parts[:5]) if len(parts) >= 5 else cmd_part
        cmd = parts[5] if len(parts) > 5 else ""
        jobs.append({"id": job_id, "expr": expr, "command": cmd, "raw": line})
    return jobs


def add_job(cron_expr: str, command: str) -> str:
    """Add a cron entry. Returns the job id (idempotent on same expr+command)."""
    job_id = hashlib.sha1(f"{cron_expr}|{command}".encode()).hexdigest()[:8]
    existing = _read_crontab()
    if job_id in existing:
        return job_id
    line = f"{cron_expr} {command}  {_MARKER} id={job_id}"
    new_content = existing.rstrip("\n") + "\n" + line + "\n"
    _write_crontab(new_content)
    return job_id


def remove_job(job_id: str) -> bool:
    """Remove a job by id. Returns True if found and removed."""
    existing = _read_crontab()
    lines = existing.splitlines(keepends=True)
    new_lines = [l for l in lines if job_id not in l]
    if len(new_lines) == len(lines):
        return False
    _write_crontab("".join(new_lines))
    return True
