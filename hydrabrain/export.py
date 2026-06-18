"""Export — dump a brain (tenant + source) back out to files.

The inverse of `sync`/`ingest`: page through every memory in the (tenant, source)
namespace and write each to a Markdown file under `out_dir`, plus a manifest.json
index. Makes the brain portable and backup-able — you can re-`sync` the export
into any other tenant/source.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _slug(s: str, fallback: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\- ]+", "", s).strip().replace(" ", "-").lower()
    return (s or fallback)[:80]


def _row_text(row: dict) -> str:
    for k in ("text", "content", "memory", "chunk_content"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def export(client, out_dir, *, sub_tenant_id: str = "", kinds=("memory", "knowledge")) -> dict:
    """Write every row in (tenant, source) to files under out_dir. Returns a summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    written = 0
    seen_names: set[str] = set()

    for kind in kinds:
        try:
            rows = client.list_all(kind=kind, sub_tenant_id=sub_tenant_id)
        except Exception:
            rows = []
        for i, row in enumerate(rows):
            text = _row_text(row)
            if not text:
                continue
            mid = str(row.get("memory_id") or row.get("source_id") or f"{kind}-{i}")
            title = str(row.get("title") or "").strip()
            base = _slug(title, mid)
            name = f"{base}.md"
            n = 1
            while name in seen_names:  # avoid clobbering same-titled rows
                name = f"{base}-{n}.md"
                n += 1
            seen_names.add(name)

            header = f"# {title}\n\n" if title else ""
            (out / name).write_text(f"{header}{text}\n", encoding="utf-8")
            index.append({"file": name, "memory_id": mid, "title": title, "kind": kind})
            written += 1

    (out / "manifest.json").write_text(json.dumps(
        {"tenant": getattr(client, "tenant_id", ""), "source": sub_tenant_id,
         "count": written, "items": index}, indent=2))
    return {"out_dir": str(out), "written": written, "tenant": getattr(client, "tenant_id", ""),
            "source": sub_tenant_id or "(host)"}
