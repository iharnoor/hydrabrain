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
- **`engine.py`** — `BrainEngine`, the gbrain-style capability surface backed entirely by HydraDB. Constructs a `HydraDBClient` and exposes `capture` / `ingest_file` / `sync` / `ingest_url` / `search` / `think` / `enrich` / `briefing` / `export` / `graph` (and `status`); every operation routes to HydraDB. Mirrors gbrain's two axes: **brain** = HydraDB `tenant_id`, **source** = HydraDB `sub_tenant_id` namespace (threaded through every read/write via `self.source_id`).
- **`sync.py`** — bulk, incremental ingest of directories / globs into HydraDB. Content-hash + local manifest make re-runs idempotent (unchanged files skipped); each new/changed file is captured via `add_memory(infer=True)`. This is the north-star "dump in all my content" path, beyond single-file `ingest`.
- **`connectors.py`** — web ingestion connectors, all free/no-auth. `fetch(url)` routes to an article reader (stdlib `HTMLParser` → clean text), a **tweet** fetcher (Twitter oEmbed, no API key), or a YouTube transcript fetcher (optional `youtube-transcript-api`); LinkedIn is best-effort via the article reader with a "paste it" hint when login-walled. Returns normalized text that `BrainEngine.ingest_url` captures into HydraDB. Extensible: add one `fetch_*` function per source.
- **`onboarding.py`** + **`config.write_keys`** — first-run setup. Validates a HydraDB key live (timeout-bounded), accepts an optional Gemini key, and persists both to `~/.hydrabrain/.env` (chmod 600), which `config` now checks ahead of the legacy paths. "Free mode" = HydraDB key only (capture/sync/read/search work; `synth` degrades to returning the top memory instead of a synthesized answer when `GEMINI_API_KEY` is absent). Surfaced by `hydrabrain init` (CLI) and the web setup screen (`web/setup.html`, served by `webapp` whenever `config.needs_onboarding()`); a CLI first-run guard points unconfigured users at `init`/`web` instead of a stack trace.
- **`enrich.py`** — `enrich(text)` derives a one-line summary + topical tags + entities via Gemini (reusing `synth._genai`'s cached client). HydraDB does the *graph* extraction natively on `infer=True`; this is the human-facing enrichment layer.
- **`reports.py`** — `briefing(engine, topic?)` produces a synthesized digest: topic-scoped (recall + synthesize) or a whole-brain overview (list + synthesize). Built on HydraDB recall + the existing synthesis layer.
- **`export.py`** — `export(client, dir, sub_tenant_id)` pages every memory in a (tenant, source) namespace out to Markdown files + a `manifest.json` index. Inverse of `sync`; makes a brain portable/backup-able.
- **`webapp.py`** + **`web/index.html`** — the zero-dependency web UI. `serve(...)` runs a stdlib `http.server` (no Flask/FastAPI) that serves a single self-contained page plus a JSON API (`/api/status` · `/api/read` · `/api/capture` · `/api/think` · `/api/search`), all routing through `BrainEngine`. Built for creators: paste a blog/article/YouTube URL → ingested via the connectors → chat with cited answers. Launched by `hydrabrain web [--open] [--port]`.
- **`synth.py`** — produces cited answers. All facts come from HydraDB retrieval; Gemini is only the writer/grounding layer, never a store. Degrades to returning the top memory when no Gemini key (free mode).
- **`llm.py`** — the one place a Gemini client is created, with a **hard 90s per-request timeout** (`HttpOptions`). Prevents the failure where a hung Gemini socket wedged a whole benchmark run for ~10h. Every Gemini call in `hydrabrain/` and `bench/` routes through `llm.client()` (cached). Tunable via `HYDRABRAIN_LLM_TIMEOUT_MS`.
- **`mcp_server.py`** — MCP server exposing 8 tools: `capture` / `read_url` / `search` / `think` / `briefing` / `enrich` / `graph` / `status`. Honors `--tenant`/`--source`. Backed entirely by HydraDB.
- **`cli.py`** — `hydrabrain` CLI, 16 commands (`init` / `status` / `capture` / `ingest` / `sync` / `read` / `search` / `think` / `chat` / `web` / `briefing` / `enrich` / `graph` / `export` / `serve` / `bench`), with global `--tenant` (brain) and `--source` (namespace) flags. Backed by HydraDB via `BrainEngine`.
- **`config.py`** — loads keys from `./.env` → `~/.hydrabrain/.env` (onboarding target) → legacy path; `require()` points missing keys at `hydrabrain init`. Exposes recall tuning via `HYDRA_RECALL_MODE` / `HYDRA_RECALL_ALPHA`, brain/source defaults via `HYDRABRAIN_TENANT` / `HYDRABRAIN_SOURCE`, and `write_keys` / `needs_onboarding` / `have_gemini` for setup. Gemini keys are used only for embedding/chat, not for storage.

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
| Brain axis (which database) | HydraDB `tenant_id` (`--tenant`) |
| Source axis (which repo inside it) | HydraDB `sub_tenant_id` (`--source`) |
| `BrainEngine` (TS contract) | `hydrabrain.engine.BrainEngine` (Python) |

---

## Honesty / fork boundary

The upstream gbrain TypeScript source under `src/` (and its docs) is **preserved unchanged** and **legitimately uses pgvector/PGLite**. We did not and will not rewrite it to claim HydraDB. gbrain itself does not use HydraDB.

HydraDB is the backend for the `hydrabrain/` reimplementation and **all new work in this fork**. Where the benchmark code references "gbrain-stack", "pgvector-equiv", or "dense + BM25 + RRF", those names describe the **comparison baseline** — gbrain's pipeline — and never our backend. No part of this fork routes our memory storage or retrieval through pgvector/PGLite.

---

## See also

- [`README.md`](README.md) — overview and quickstart.
- [`BENCHMARKS.md`](BENCHMARKS.md) — results, including HydraDB recall@5 of 96.5% vs the full-stack baseline's 92.1%.
