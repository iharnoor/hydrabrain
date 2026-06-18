# Context Memory

**The context-memory layer for this project is [HydraDB](https://hydradb.com).**

This repository is a fork of gbrain. All new work in this fork — the Python `hydrabrain/` package — stores and retrieves context through HydraDB, a graph-native context-memory backend.

---

## How it's used

The Python `hydrabrain/` package is the HydraDB-backed reimplementation of gbrain's capability surface:

- **`client.py`** — `HydraDBClient`, the only store client. Talks to the HydraDB REST API (`https://api.hydradb.com`):
  - `add_memory(... infer=true)` — writes memories and lets HydraDB build the knowledge graph natively.
  - `recall_preferences(... mode="thinking", alpha=1.0)` — hybrid recall with the thinking recall mode and dense-leaning fusion weight.
  - `graph(...)` — native graph traversal / context expansion.
- **`engine.py`** — `BrainEngine`, the gbrain-style capability surface backed entirely by HydraDB. Constructs a `HydraDBClient` and exposes `capture` / `ingest_file` / `sync` / `search` / `think` / `graph` (and `status`); every operation routes to HydraDB recall.
- **`sync.py`** — bulk, incremental ingest of directories / globs into HydraDB. Content-hash + local manifest make re-runs idempotent (unchanged files skipped); each new/changed file is captured via `add_memory(infer=True)`. This is the north-star "dump in all my content" path, beyond single-file `ingest`.
- **`connectors.py`** — web ingestion connectors. `fetch(url)` routes to an article reader (stdlib `HTMLParser` → clean text, no extra deps) or a YouTube transcript fetcher (optional `youtube-transcript-api`), returning normalized text that `BrainEngine.ingest_url` captures into HydraDB. Extensible: add one `fetch_*` function per source.
- **`synth.py`** — produces cited answers. All facts come from HydraDB retrieval; Gemini is only the writer/grounding layer, never a store.
- **`mcp_server.py`** — MCP server exposing `capture` / `search` / `think` / `graph` / `status`. Header correctly states "Backed entirely by HydraDB."
- **`cli.py`** — `hydrabrain` CLI (`status` / `capture` / `ingest` / `search` / `think` / `graph` / `serve` / `bench`), backed by HydraDB via `BrainEngine`.
- **`config.py`** — requires `HYDRADB_API_KEY`; exposes recall tuning via `HYDRA_RECALL_MODE` / `HYDRA_RECALL_ALPHA`. Gemini keys are used only for embedding/chat, not for storage.

Benchmark entrypoints under `bench/` compare HydraDB against the preserved gbrain stack as a baseline:

- **`bench/run_bench.py`** — HydraDB hybrid recall (`recall_preferences`, `mode=thinking`, `graph_context=True`) vs the gbrain-stack baseline.
- **`bench/longmemeval.py`** — LongMemEval: HydraDB vs the gbrain-stack baseline.

---

## Mapping: gbrain concept → HydraDB equivalent

| gbrain concept | HydraDB equivalent |
| --- | --- |
| pgvector (HNSW dense) | HydraDB hybrid recall (native) |
| BM25 + RRF + reranker | HydraDB hybrid recall (one call) |
| self-wired knowledge graph (hand-rolled extractor) | HydraDB `infer=true` (native graph) |
| PGLite / Postgres tenant | HydraDB tenant / `sub_tenant_id` |
| `BrainEngine` (TS contract) | `hydrabrain.engine.BrainEngine` (Python) |

---

## Honesty / fork boundary

The upstream gbrain TypeScript source under `src/` (and its docs) is **preserved unchanged** and **legitimately uses pgvector/PGLite**. We did not and will not rewrite it to claim HydraDB. gbrain itself does not use HydraDB.

HydraDB is the backend for the `hydrabrain/` reimplementation and **all new work in this fork**. Where the benchmark code references "gbrain-stack", "pgvector-equiv", or "dense + BM25 + RRF", those names describe the **comparison baseline** — gbrain's pipeline — and never our backend. No part of this fork routes our memory storage or retrieval through pgvector/PGLite.

---

## See also

- [`README.md`](README.md) — overview and quickstart.
- [`BENCHMARKS.md`](BENCHMARKS.md) — results, including HydraDB recall@5 of 96.5% vs the full-stack baseline's 92.1%.
