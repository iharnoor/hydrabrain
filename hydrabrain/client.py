"""HydraDB API client.

Thin wrapper over the HydraDB v2 REST API (https://api.hydradb.com). HydraDB is
a graph-native context store: a single `add_memory(..., infer=True)` call extracts
entities, preferences, temporal facts, and graph edges with zero extra LLM calls
from our side, and `recall(...)` runs hybrid dense-vector + graph + BM25 retrieval.

Verified endpoints:
  POST /memories/add_memory          ingest (infer=True builds the graph)
  POST /recall/full_recall           hybrid vector + graph + BM25
  POST /recall/recall_preferences    dense + inferred + BM25 (preference-aware)
  POST /recall/boolean_recall        BM25 full-text only
  POST /list/data                    list everything in a tenant
  DELETE /memories/delete_memory     delete by memory_id (query params)
  GET  /list/graph_relations_by_id   explore the knowledge graph
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

BASE_URL = "https://api.hydradb.com"


@dataclass
class Chunk:
    """A normalized retrieval result, source-agnostic."""

    text: str
    score: float = 0.0
    source_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class HydraDBClient:
    api_key: str
    tenant_id: str = ""
    base_url: str = BASE_URL
    _session: requests.Session = field(default_factory=requests.Session, repr=False)

    def __post_init__(self):
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # ── low-level ────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _post(self, path: str, json: dict | None = None, **kwargs) -> dict:
        kwargs.setdefault("timeout", (10, 60))
        resp = self._session.post(self._url(path), json=json, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        resp.close()
        return data

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._session.get(self._url(path), params=params, timeout=(10, 30))
        resp.raise_for_status()
        return resp.json()

    # ── tenant ───────────────────────────────────────────────
    def use_tenant(self, tenant_id: str) -> "HydraDBClient":
        self.tenant_id = tenant_id
        return self

    def list_tenants(self) -> dict:
        return self._get("/tenants/tenant_ids")

    # ── ingest ───────────────────────────────────────────────
    def add_memory(self, text: str, title: str = "", infer: bool = True,
                   sub_tenant_id: str = "") -> dict:
        item = {"text": text, "infer": infer}
        if title:
            item["title"] = title
        payload = {"memories": [item], "tenant_id": self.tenant_id}
        if sub_tenant_id:
            payload["sub_tenant_id"] = sub_tenant_id
        return self._post("/memories/add_memory", payload)

    def add_memories(self, texts: list[str], infer: bool = True,
                     sub_tenant_id: str = "") -> dict:
        memories = [{"text": t, "infer": infer} for t in texts]
        payload = {"memories": memories, "tenant_id": self.tenant_id}
        if sub_tenant_id:
            payload["sub_tenant_id"] = sub_tenant_id
        return self._post("/memories/add_memory", payload)

    # ── recall ───────────────────────────────────────────────
    def _recall(self, endpoint: str, query: str, max_results: int, graph_context: bool,
                mode: str, alpha: float, sub_tenant_id: str = "") -> dict:
        payload = {
            "tenant_id": self.tenant_id,
            "query": query,
            "max_results": max_results,
            "mode": mode,
            "alpha": alpha,
            "graph_context": graph_context,
        }
        if sub_tenant_id:
            payload["sub_tenant_id"] = sub_tenant_id
        return self._post(endpoint, payload)

    @staticmethod
    def _normalize(resp: dict) -> list[Chunk]:
        """HydraDB returns {"chunks": [{"chunk_content", "score", "source_id", ...}]}."""
        chunks = resp.get("chunks") or resp.get("results") or []
        out: list[Chunk] = []
        for c in chunks:
            if not isinstance(c, dict):
                continue
            text = c.get("chunk_content") or c.get("text") or c.get("content") or ""
            if not text:
                continue
            out.append(
                Chunk(
                    text=text,
                    score=float(c.get("score", 0.0) or 0.0),
                    source_id=str(c.get("source_id", "") or c.get("memory_id", "")),
                    metadata={k: v for k, v in c.items()
                              if k not in {"chunk_content", "text", "content", "score"}},
                )
            )
        return out

    def recall(self, query: str, max_results: int = 5, graph_context: bool = True,
               mode: str = "thinking", alpha: float = 0.8,
               sub_tenant_id: str = "") -> list[Chunk]:
        """Hybrid vector + graph + BM25 recall. This is the flagship retrieval path."""
        resp = self._recall("/recall/full_recall", query, max_results, graph_context,
                             mode, alpha, sub_tenant_id)
        return self._normalize(resp)

    def recall_preferences(self, query: str, max_results: int = 5, graph_context: bool = True,
                           mode: str = "fast", alpha: float = 0.8,
                           sub_tenant_id: str = "") -> list[Chunk]:
        resp = self._recall("/recall/recall_preferences", query, max_results, graph_context,
                            mode, alpha, sub_tenant_id)
        return self._normalize(resp)

    # ── graph ────────────────────────────────────────────────
    def graph_relations(self, source_id: str) -> dict:
        return self._get(
            "/list/graph_relations_by_id",
            {"tenant_id": self.tenant_id, "source_id": source_id},
        )

    # ── list / delete ────────────────────────────────────────
    def list_content(self, kind: str = "memory", page: int = 1, page_size: int = 50) -> dict:
        # `kind` must be 'memory' or 'knowledge'.
        return self._post(
            "/list/data",
            {"tenant_id": self.tenant_id, "kind": kind, "page": page, "page_size": page_size},
        )

    def count(self) -> int:
        total = 0
        for kind in ("memory", "knowledge"):
            try:
                data = self.list_content(kind=kind)
                total += len(data.get("user_memories", []) or data.get("sources", []) or [])
            except Exception:
                pass
        return total

    def delete_memory(self, memory_id: str) -> dict:
        resp = self._session.delete(
            self._url(f"/memories/delete_memory?tenant_id={self.tenant_id}&memory_id={memory_id}"),
            timeout=(10, 30),
        )
        resp.raise_for_status()
        return resp.json()

    def wipe(self) -> int:
        """Delete everything in the current tenant. Returns count removed."""
        removed = 0
        for _ in range(20):
            data = self.list_content(kind="memory")
            sources = data.get("user_memories", []) or data.get("sources", [])
            if not sources:
                break
            for s in sources:
                sid = s.get("memory_id") or s.get("source_id") or ""
                if sid:
                    try:
                        self.delete_memory(sid)
                        removed += 1
                    except Exception:
                        pass
            time.sleep(1)
        return removed
