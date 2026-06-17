"""Faithful reproduction of gbrain's retrieval stack — the benchmark baseline.

gbrain (per its own docs) ranks with:
    "vector (HNSW on pgvector), BM25 keyword, reciprocal-rank fusion,
     source-tier boost, and reranking"
and credits its self-wiring knowledge graph with "+31.4 points P@5" over the
graph-disabled variant.

This module reproduces the *graph-disabled* gbrain pipeline as fairly as possible:

    dense vectors  : Gemini `gemini-embedding-001` (a top-tier embedder — generous
                     to the baseline). Exact cosine NN over 19 docs is identical
                     to pgvector HNSW recall at this corpus size.
    keyword        : BM25Okapi (rank_bm25)
    fusion         : Reciprocal Rank Fusion (k=60)

It deliberately has NO knowledge graph. That is the entire experiment: HydraDB
ships the graph natively (`infer=True`), so this measures exactly the lift gbrain
attributes to its graph — except HydraDB gets it for free.

Source-tier boost / cross-encoder rerank are gbrain-proprietary and omitted; both
would only help the baseline, so excluding them is conservative (not a strawman).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from hydrabrain import config
from hydrabrain.client import Chunk

_WORD = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    from google import genai

    client = genai.Client(api_key=config.require("GEMINI_API_KEY"))
    model = model or config.GEMINI_EMBED_MODEL
    vecs: list[list[float]] = []
    # Embed one-by-one for maximal SDK-version compatibility.
    for t in texts:
        resp = client.models.embed_content(model=model, contents=t)
        emb = resp.embeddings[0]
        vecs.append(list(emb.values))
    return vecs


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _llm_rerank(query: str, candidates: list[tuple[int, str]], top_k: int) -> list[int]:
    """Listwise cross-encoder-style reranker (Gemini). Returns candidate indices,
    most-relevant first. This stands in for gbrain's reranking stage — an LLM reranker
    is at least as strong as a MiniLM cross-encoder, so it is *generous* to the baseline.
    Falls back to the input order on any parse failure."""
    import json as _json

    from google import genai

    from hydrabrain import config

    listing = "\n".join(f"[{i}] {txt[:500]}" for i, (_, txt) in enumerate(candidates))
    client = genai.Client(api_key=config.require("GEMINI_API_KEY"))
    resp = client.models.generate_content(
        model=config.GEMINI_CHAT_MODEL,
        contents=(
            "You are a search reranker. Given a query and candidate passages, return the "
            f"passage numbers ordered from MOST to LEAST relevant to the query. Return ONLY "
            f'a JSON array of integers, e.g. [3,0,1]. Include all {len(candidates)} numbers.\n\n'
            f"Query: {query}\n\nPassages:\n{listing}"
        ),
    )
    t = (resp.text or "").strip()
    if "[" in t:
        t = t[t.index("["): t.rindex("]") + 1] if "]" in t else t
    try:
        order = [int(x) for x in _json.loads(t)]
        seen, clean = set(), []
        for x in order:
            if 0 <= x < len(candidates) and x not in seen:
                seen.add(x); clean.append(x)
        for x in range(len(candidates)):  # append any the model dropped
            if x not in seen:
                clean.append(x)
        return [candidates[x][0] for x in clean[:top_k]]
    except Exception:
        return [c[0] for c in candidates[:top_k]]


@dataclass
class GBrainStack:
    """Dense + BM25 + RRF (+ optional rerank) retriever — gbrain's retrieval stack
    minus the knowledge graph."""

    rrf_k: int = 60
    rerank: bool = False          # add gbrain's reranking stage (LLM cross-encoder)
    rerank_pool: int = 10         # how many RRF candidates to feed the reranker
    name: str = "gbrain-stack (pgvector+BM25+RRF, no graph)"

    def __post_init__(self):
        self.docs: list[str] = []
        self._vecs: list[list[float]] = []
        self._bm25: BM25Okapi | None = None
        if self.rerank:
            self.name = "gbrain-stack (pgvector+BM25+RRF+rerank, no graph)"

    def ingest(self, pages: list[str]) -> None:
        self.docs = list(pages)
        self._vecs = _embed(self.docs)
        self._bm25 = BM25Okapi([_tok(d) for d in self.docs])

    def _dense_rank(self, query: str) -> list[int]:
        qv = _embed([query])[0]
        scored = sorted(range(len(self.docs)),
                        key=lambda i: _cosine(qv, self._vecs[i]), reverse=True)
        return scored

    def _bm25_rank(self, query: str) -> list[int]:
        scores = self._bm25.get_scores(_tok(query))
        return sorted(range(len(self.docs)), key=lambda i: scores[i], reverse=True)

    def search(self, query: str, k: int = 5) -> list[Chunk]:
        dense = self._dense_rank(query)
        bm25 = self._bm25_rank(query)
        rrf: dict[int, float] = {}
        for ranking in (dense, bm25):
            for rank, idx in enumerate(ranking):
                rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        # NOTE: gbrain also applies a source-tier boost here. This corpus is a single
        # source/tier, so the boost is a mathematical no-op (nothing to re-weight).
        fused = sorted(rrf, key=lambda i: rrf[i], reverse=True)
        if self.rerank:
            pool = fused[: max(k, self.rerank_pool)]
            order = _llm_rerank(query, [(i, self.docs[i]) for i in pool], k)
        else:
            order = fused[:k]
        return [Chunk(text=self.docs[i], score=rrf[i]) for i in order]
