"""Background job runner — submit shell commands, track status on disk.

Jobs are launched as detached subprocesses. stdout/stderr go to per-job
log files under ~/.hydrabrain/jobs/<id>/. Status is inferred from whether
the process is still running (via kill -0) or has exited.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

JOBS_DIR = Path.home() / ".hydrabrain" / "jobs"


def _meta_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "meta.json"


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_meta(job_id: str) -> dict | None:
    p = _meta_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def submit(command: str) -> str:
    """Launch command in the background. Returns a short job id."""
    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"

    with open(stdout_path, "w") as out, open(stderr_path, "w") as err:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=out,
            stderr=err,
            start_new_session=True,  # detach from parent's signal group
        )

    meta = {
        "id": job_id,
        "command": command,
        "pid": proc.pid,
        "submitted_at": time.time(),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }
    _meta_path(job_id).write_text(json.dumps(meta, indent=2))
    return job_id


def _enrich(meta: dict) -> dict:
    """Add live status to a meta dict."""
    pid = meta.get("pid")
    if pid and _is_running(pid):
        meta["status"] = "running"
    else:
        # Check if stdout exists and has content to tell if it ran at all
        out = Path(meta.get("stdout", ""))
        meta["status"] = "done" if out.exists() else "unknown"
    return meta


def list_jobs(limit: int = 20) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    dirs = sorted(JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    jobs = []
    for d in dirs[:limit]:
        meta = _read_meta(d.name)
        if meta:
            jobs.append(_enrich(meta))
    return jobs


def get_job(job_id: str) -> dict | None:
    meta = _read_meta(job_id)
    return _enrich(meta) if meta else None


def get_output(job_id: str) -> str:
    meta = _read_meta(job_id)
    if not meta:
        return f"job {job_id} not found"
    parts = []
    for key in ("stdout", "stderr"):
        p = Path(meta.get(key, ""))
        if p.exists():
            content = p.read_text()
            if content.strip():
                parts.append(f"--- {p.name} ---\n{content}")
    return "\n".join(parts) if parts else "(no output yet)"


def watch(job_id: str, tail: int = 40) -> None:
    """Stream output until the job finishes."""
    import time
    meta = _read_meta(job_id)
    if not meta:
        print(f"job {job_id} not found")
        return
    out_path = Path(meta.get("stdout", ""))
    err_path = Path(meta.get("stderr", ""))
    pid = meta.get("pid")
    seen = 0
    print(f"watching job {job_id} (pid={pid}) — Ctrl-C to stop\n")
    try:
        while True:
            for p in (out_path, err_path):
                if p.exists():
                    content = p.read_text()
                    lines = content.splitlines()
                    new_lines = lines[seen:]
                    if new_lines:
                        print("\n".join(new_lines))
                        seen = len(lines)
            if pid and not _is_running(pid):
                print("\n[job finished]")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[detached]")
