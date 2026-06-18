"""Bulk sync — ingest a directory / globs of files into HydraDB, incrementally.

Mirrors gbrain's flagship `gbrain sync`: point it at a folder, it walks the files,
captures each as a memory (`infer=True` → HydraDB wires the graph), and remembers
what it already ingested so re-running only sends what changed. This is the
north-star "dump in *all* the content I consume" path — beyond single-file `ingest`.

State lives in a local manifest (path → content hash + mtime/size), so the sync is
incremental and idempotent: unchanged files are skipped on the next run. Deleting the
manifest (or `--force`) re-ingests everything.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Text-like extensions we ingest by default. Anything else is skipped unless the
# caller passes an explicit extension set.
DEFAULT_EXTENSIONS = (".md", ".markdown", ".mdx", ".txt", ".text", ".rst", ".org")


def _manifest_path(tenant_id: str) -> Path:
    return Path.home() / ".hydrabrain" / f"sync-{tenant_id or 'default'}.json"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _iter_files(paths: list[str], extensions: tuple[str, ...], recursive: bool) -> list[Path]:
    """Expand a mix of files, directories, and globs into a sorted, de-duplicated file list."""
    found: set[Path] = set()
    exts = {e.lower() for e in extensions}
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            walker = p.rglob("*") if recursive else p.glob("*")
            for f in walker:
                if f.is_file() and f.suffix.lower() in exts:
                    found.add(f.resolve())
        elif p.is_file():
            found.add(p.resolve())
        else:
            # Treat as a glob relative to cwd.
            for f in Path().glob(raw):
                if f.is_file() and (f.suffix.lower() in exts or any(
                    fnmatch.fnmatch(f.name, os.path.basename(raw)) for _ in (0,)
                )):
                    found.add(f.resolve())
    return sorted(found)


@dataclass
class SyncResult:
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_ingested: int = 0
    details: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "ingested": self.ingested,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_ingested": self.bytes_ingested,
        }


def sync(
    client,
    paths: list[str],
    *,
    tenant_id: str = "",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    recursive: bool = True,
    force: bool = False,
    dry_run: bool = False,
    manifest_path: Path | None = None,
    on_progress=None,
) -> SyncResult:
    """Walk `paths`, ingest changed files into HydraDB, update the local manifest.

    `client` is a HydraDBClient already pointed at the target tenant. `force` ignores
    the manifest (re-ingests all). `dry_run` reports what *would* happen without writing.
    `on_progress(done, total, path, action)` is called per file if provided.
    """
    mpath = manifest_path or _manifest_path(tenant_id or getattr(client, "tenant_id", ""))
    manifest: dict[str, dict] = {}
    if mpath.exists() and not force:
        try:
            manifest = json.loads(mpath.read_text())
        except Exception:
            manifest = {}

    files = _iter_files(paths, extensions, recursive)
    result = SyncResult()
    total = len(files)

    for i, f in enumerate(files, 1):
        key = str(f)
        action = "skipped"
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                result.skipped += 1
                action = "empty"
            else:
                h = _content_hash(text)
                prev = manifest.get(key)
                if prev and prev.get("hash") == h and not force:
                    result.skipped += 1
                    action = "unchanged"
                elif dry_run:
                    result.ingested += 1
                    result.bytes_ingested += len(text.encode("utf-8"))
                    action = "would-ingest"
                else:
                    client.add_memory(text, title=f.name, infer=True)
                    manifest[key] = {
                        "hash": h,
                        "mtime": f.stat().st_mtime,
                        "size": f.stat().st_size,
                        "title": f.name,
                        "ingested_at": time.time(),
                    }
                    result.ingested += 1
                    result.bytes_ingested += len(text.encode("utf-8"))
                    action = "ingested"
        except Exception as e:  # one bad file never aborts the whole sync
            result.failed += 1
            action = f"error: {type(e).__name__}"
            result.details.append({"path": key, "action": action, "error": str(e)[:200]})

        if action not in {"unchanged", "empty"}:
            result.details.append({"path": key, "action": action})
        if on_progress:
            on_progress(i, total, key, action)

    if not dry_run:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, indent=2))

    return result
