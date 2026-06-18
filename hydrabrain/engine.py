"""BrainEngine — the gbrain-style capability surface, backed by HydraDB.

Capabilities mirrored from gbrain:
  capture(text)      ingest a thought / piece of consumed content
  ingest_file(path)  ingest a text/markdown file (one memory)
  sync(paths)        bulk, incremental ingest of dirs/globs (content-hash dedup)
  ingest_url(url)    ingest a web article / YouTube transcript (connectors)
  search(query)      hybrid vector + graph + BM25 retrieval (raw ranked chunks)
  think(query)       synthesis: cited prose answer + gap analysis
  enrich(text)       derive a summary + tags + entities for a memory (LLM)
  briefing(topic?)   a synthesized briefing/report over memory
  export(dir)        dump the brain back out to files
  graph(source_id)   explore the self-wired knowledge graph
  status()           tenant + memory count

Two organizational axes, mirroring gbrain:
  • brain  = WHICH DATABASE  → HydraDB tenant_id
  • source = WHICH REPO INSIDE IT → HydraDB sub_tenant_id namespace

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
    def __init__(self, tenant_id: str | None = None, api_key: str | None = None,
                 source_id: str | None = None):
        self.client = HydraDBClient(api_key=api_key or config.require("HYDRADB_API_KEY"))
        self.client.use_tenant(tenant_id or config.DEFAULT_TENANT)
        # source = which repo inside the brain (gbrain's second axis) → sub_tenant_id
        self.source_id = source_id if source_id is not None else config.DEFAULT_SOURCE

    # ── ingest ───────────────────────────────────────────────
    def capture(self, text: str, title: str = "") -> dict:
        return self.client.add_memory(text, title=title, infer=True,
                                      sub_tenant_id=self.source_id)

    def ingest_file(self, path: str | Path) -> dict:
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="ignore")
        return self.client.add_memory(text, title=p.name, infer=True,
                                      sub_tenant_id=self.source_id)

    def ingest_url(self, url: str) -> dict:
        """Fetch a web page / YouTube transcript and capture it (HydraDB wires the graph)."""
        from . import connectors
        src = connectors.fetch(url)
        res = self.client.add_memory(src.text, title=src.title, infer=True,
                                     sub_tenant_id=self.source_id)
        return {"url": url, "title": src.title, "kind": src.kind,
                "chars": len(src.text), "result": res}

    def sync(self, paths: list[str], *, recursive: bool = True, force: bool = False,
             dry_run: bool = False, extensions=None, on_progress=None):
        """Bulk, incremental ingest of files/dirs/globs. See hydrabrain.sync."""
        from . import sync as _sync
        kwargs = dict(tenant_id=self.client.tenant_id, source_id=self.source_id,
                      recursive=recursive, force=force, dry_run=dry_run,
                      on_progress=on_progress)
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
            sub_tenant_id=self.source_id,
        )

    def think(self, query: str, k: int = 6, graph: bool = True) -> Answer:
        chunks = self.search(query, k=k, graph=graph)
        return synthesize(query, chunks)

    # ── enrich / report ──────────────────────────────────────
    def enrich(self, text: str) -> dict:
        """Derive a summary, tags, and entities for a piece of content (LLM)."""
        from . import enrich as _enrich
        return _enrich.enrich(text)

    def briefing(self, topic: str | None = None, k: int = 12) -> Answer:
        """A synthesized briefing/report over memory (optionally scoped to a topic)."""
        from . import reports
        return reports.briefing(self, topic=topic, k=k)

    # ── export ───────────────────────────────────────────────
    def export(self, out_dir: str | Path) -> dict:
        """Dump every memory in (tenant, source) to files under out_dir."""
        from . import export as _export
        return _export.export(self.client, out_dir, sub_tenant_id=self.source_id)

    # ── graph ────────────────────────────────────────────────
    def graph(self, source_id: str) -> dict:
        return self.client.graph_relations(source_id)

    # ── status ───────────────────────────────────────────────
    def status(self) -> dict:
        return {"tenant": self.client.tenant_id,
                "source": self.source_id or "(host)",
                "memories": self.client.count(sub_tenant_id=self.source_id)}
