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


# ── chunking (parameter-faithful to real gbrain) ────────────────────
# Real gbrain chunks every document before indexing — src/core/chunkers/
# recursive.ts: 300-word chunks, 50-word overlap, 6000-char hard cap.
# The baseline must do the same: indexing a whole multi-topic chat session
# as ONE unsplit unit gives it an artificially tiny candidate pool (on the
# LongMemEval oracle split, fewer units than top-k — it "wins" recall by
# returning everything it has), while HydraDB searches among many chunks
# of the same content. Chunk parity makes recall a measurement again.
CHUNK_WORDS = 300
CHUNK_OVERLAP_WORDS = 50
CHUNK_MAX_CHARS = 6000


def chunk_text(text: str) -> list[str]:
    """Sliding word-window chunker with gbrain's parameters (300w / 50w
    overlap / 6000-char cap). Word-boundary port of gbrain's recursive
    chunker — same size/overlap/cap, without the 5-level delimiter
    hierarchy (chat-transcript lines make word windows a close proxy)."""
    words = text.split()
    if not words:
        return []
    step = CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    chunks: list[str] = []
    for start in range(0, len(words), step):
        piece = " ".join(words[start:start + CHUNK_WORDS])
        # Hard char cap — the sliding-window safety belt from recursive.ts.
        while len(piece) > CHUNK_MAX_CHARS:
            chunks.append(piece[:CHUNK_MAX_CHARS])
            piece = piece[CHUNK_MAX_CHARS - 200:]
        chunks.append(piece)
        if start + CHUNK_WORDS >= len(words):
            break
    return chunks


_EMBED_BATCH = 50  # texts per request — Gemini's free-tier quota counts REQUESTS
                   # per day (1000), so batching is a ~50× quota saving vs singles


def _embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    import time

    from hydrabrain import llm

    client = llm.client()
    model = model or config.GEMINI_EMBED_MODEL
    vecs: list[list[float]] = []
    # Batch-embed with exponential backoff — chunking multiplies embed volume,
    # and both transient 503s and per-day request quotas must not kill (or
    # needlessly drain quota on) a multi-hour benchmark run.
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i:i + _EMBED_BATCH]
        for attempt in range(9):
            try:
                resp = client.models.embed_content(model=model, contents=batch)
                vecs.extend(list(e.values) for e in resp.embeddings)
                break
            except Exception as e:
                # Only backoff-retry transient failures (rate limits, overload,
                # network). Auth/validation errors would otherwise burn ~5min of
                # sleeps before surfacing the real misconfiguration.
                transient = any(sig in repr(e) for sig in (
                    "429", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                    "DEADLINE", "Timeout", "timeout", "Connection", "reset"))
                if not transient or attempt == 8:
                    raise
                time.sleep(min(2 ** attempt, 60))  # 1..60s, ~5min total
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

    from hydrabrain import config, llm

    listing = "\n".join(f"[{i}] {txt[:500]}" for i, (_, txt) in enumerate(candidates))
    client = llm.client()
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
        # Chunk each page the way real gbrain does (300w/50w/6000c) before
        # indexing — for both the dense and BM25 arms. Pages shorter than one
        # chunk pass through unchanged, so small-corpus benchmarks are
        # unaffected; long documents get a realistic candidate pool.
        self.docs = [c for p in pages for c in chunk_text(p)]
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
