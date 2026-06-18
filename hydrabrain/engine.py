"""BrainEngine — the gbrain-style capability surface, backed by HydraDB.

Capabilities mirrored from gbrain:
  capture(text)      ingest a thought / piece of consumed content
  ingest_file(path)  ingest a text/markdown file (one memory)
  search(query)      hybrid vector + graph + BM25 retrieval (raw ranked chunks)
  think(query)       synthesis: cited prose answer + gap analysis
  graph(source_id)   explore the self-wired knowledge graph
  status()           tenant + memory count

The whole point: HydraDB gives the knowledge-graph + hybrid-retrieval that gbrain
has to assemble out of pgvector + BM25 + RRF + a hand-rolled extractor. Here it's
one `infer=True` ingest and one `recall` call.
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .client import Chunk, HydraDBClient
from .synth import Answer, synthesize


class BrainEngine:
    def __init__(self, tenant_id: str | None = None, api_key: str | None = None):
        self.client = HydraDBClient(api_key=api_key or config.require("HYDRADB_API_KEY"))
        self.client.use_tenant(tenant_id or config.DEFAULT_TENANT)

    # ── ingest ───────────────────────────────────────────────
    def capture(self, text: str, title: str = "") -> dict:
        return self.client.add_memory(text, title=title, infer=True)

    def ingest_file(self, path: str | Path) -> dict:
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.client.add_memory(text, title=p.name, infer=True)

    def ingest_url(self, url: str) -> dict:
        """Fetch a web page / YouTube transcript and capture it (HydraDB wires the graph)."""
        from . import connectors
        src = connectors.fetch(url)
        res = self.client.add_memory(src.text, title=src.title, infer=True)
        return {"url": url, "title": src.title, "kind": src.kind,
                "chars": len(src.text), "result": res}

    def sync(self, paths: list[str], *, recursive: bool = True, force: bool = False,
             dry_run: bool = False, extensions=None, on_progress=None):
        """Bulk, incremental ingest of files/dirs/globs. See hydrabrain.sync."""
        from . import sync as _sync
        kwargs = dict(tenant_id=self.client.tenant_id, recursive=recursive,
                      force=force, dry_run=dry_run, on_progress=on_progress)
        if extensions:
            kwargs["extensions"] = tuple(extensions)
        return _sync.sync(self.client, paths, **kwargs)

    # ── retrieve ─────────────────────────────────────────────
    def search(self, query: str, k: int = 5, graph: bool = True) -> list[Chunk]:
        # Memory-type data (infer=True) is served by the preference recall path,
        # which runs HydraDB's hybrid dense + inferred-graph + BM25 retrieval.
        return self.client.recall_preferences(
            query, max_results=k, graph_context=graph,
            mode=config.HYDRA_RECALL_MODE, alpha=config.HYDRA_RECALL_ALPHA,
        )

    def think(self, query: str, k: int = 6, graph: bool = True) -> Answer:
        chunks = self.search(query, k=k, graph=graph)
        return synthesize(query, chunks)

    # ── graph ────────────────────────────────────────────────
    def graph(self, source_id: str) -> dict:
        return self.client.graph_relations(source_id)

    # ── status ───────────────────────────────────────────────
    def status(self) -> dict:
        return {"tenant": self.client.tenant_id, "memories": self.client.count()}
