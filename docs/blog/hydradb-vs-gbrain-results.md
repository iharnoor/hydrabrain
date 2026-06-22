# Your second brain shouldn't forget what you meant

**HydraDB vs gbrain — head-to-head benchmark results on real questions you'd actually ask**

*June 2026 · [HydraBrain](https://github.com/nishkarsh/Hermes-HydraBrain) fork · Reproducible harness in `bench/`*

---

## TL;DR

We rebuilt [gbrain](https://github.com/garrytan/gbrain)'s personal-memory surface on [HydraDB](https://hydradb.com) — a graph-native context store — and ran it against the **real gbrain binary** (PGLite + pgvector + self-wired graph, not a strawman).

On the same memories and the same questions:

| | gbrain (local) | HydraDB (cloud) |
|---|---|:---:|
| **recall@5** — personal timeline (19 memories, 19 queries) | 80.7% | **96.5%** |
| **MRR** — how fast you find the right chunk | 0.73 | **0.91** |
| **Negation** — "NOT a birthday", "NOT in Florida" | 42% | **92%** |
| **Geographic filtering** — "outside the United States" | 0% | **100%** |
| **Multi-session reasoning** — relationship arc across months | 50% | **100%** |
| **Investor network R@5** — "who invested in widget-co?" | 87.3% | **100%** |

HydraDB wins every headline metric on both corpora we tested — with **one `recall()` call** and **no separate reranker stage**. Setup is one pip install and one API key; no local Postgres, no WASM, no Bun.

**Caveat up front:** these are small, deliberately hard corpora (19 personal memories + a startup network fixture). They prove where vector search breaks and where graph-native memory wins — not yet "HydraDB beats gbrain at 10,000 files." We're honest about that below.

---

## The problem: vector search is great until it isn't

Personal memory isn't a keyword search problem. You ask things like:

- *"What trips did we take **outside** Florida?"* — not Miami beach days.
- *"Which events happened **outside the US**?"* — not every travel photo.
- *"How did we go from casual dating to buying a car together?"* — three memories, one story.
- *"Who **invested in** widget-co?"* — a relational query, not a similarity match.

These are the queries that make a second brain feel magical — or useless.

[gbrain](https://github.com/garrytan/gbrain) solves this with an impressive assembled pipeline: pgvector dense search, BM25, reciprocal-rank fusion, reranking, and a self-wired knowledge graph extracted at ingest time. It works. It's also a lot of moving parts running locally.

**HydraBrain** asks a simpler question: what if the graph, hybrid retrieval, and entity wiring were **native to the store** — one ingest with `infer=true`, one recall call — instead of something you assemble from pgvector + extractors?

We built [HydraBrain](https://github.com/nishkarsh/Hermes-HydraBrain) to find out, and we benchmarked it fairly.

---

## What we compared

### System A — gbrain (real binary)

- **Engine:** PGLite (embedded Postgres) + pgvector
- **Embeddings:** Gemini `gemini-embedding-001`
- **Graph:** ON (gbrain's self-wiring extractor)
- **Driver:** actual `bun src/cli.ts` in this repo's preserved upstream source

This is **not** a simplified baseline. It's the shipping gbrain stack.

### System B — HydraDB via HydraBrain

- **Engine:** HydraDB hosted API
- **Ingest:** `add_memory(text, infer=True)` — graph built natively
- **Recall:** `recall_preferences(mode=thinking, graph_context=True, alpha=1.0)`
- **Infra:** zero local database

Both systems saw **identical corpora**, **identical queries**, and **identical gold labels**. Scoring is deterministic (keyword-group recall@5 + MRR) — no LLM in the metric itself.

Full methodology: [`BENCHMARKS.md`](../../BENCHMARKS.md) · harness: `bench/headtohead.py`, `bench/relational.py`

---

## Headline results

### Personal memory corpus (19 pages, 19 gold queries)

A dense relationship timeline — dates, places, cultural events, milestones. Deliberately hard for pure vector search.

| Metric | gbrain | HydraDB | Δ |
|---|:---:|:---:|:---:|
| recall@5 | 80.7% | **96.5%** | +15.8 pp |
| MRR | 0.732 | **0.912** | +0.18 |
| Per-query wins | — | **2 wins / 0 losses / 17 ties** | — |

### Where the gap is widest (by query type)

| Capability | What you're really asking | gbrain | HydraDB |
|---|:---:|:---:|
| **Negation** | "Celebrations that were **NOT** birthdays" | 42% | **92%** |
| **Geographic filtering** | "Events **outside the US**" | 0% | **100%** |
| **Multi-session reasoning** | "How did we progress from dating to major commitments?" | 50% | **100%** |
| Information extraction | "When did we meet the second time?" | 100% | 100% |
| Entity direction | "What did my partner do for **my** birthday?" | 100% | 100% |
| Aggregation | "List **every** holiday we shared" | 50% | 50% |

Both systems tie on simple fact lookup. HydraDB pulls ahead exactly where users feel the pain: **negation, geography, and cross-memory synthesis**.

### Investor / startup network corpus (38 relational queries)

Mirrors gbrain's published relational benchmark shape — "who invested in X?", "who works at Y?", "what connects A and B?"

| Metric | gbrain | HydraDB |
|---|:---:|:---:|
| R@5 (recall@5) | 87.3% | **100%** |
| P@5 (precision@5) | 28.4% | **31.6%** |

Relational queries are gbrain's home turf. HydraDB still wins on recall — the graph is wired at ingest, not extracted in a second pass.

---

## Eight questions a user would actually ask

We turned the benchmark into user-facing scenarios and ran **live HydraDB searches** against ingested corpora. Side-by-side video: `demos/recording/gbrain-vs-hydradb-user-demo.mp4`

### 1. Plan your next vacation

> **You ask:** "What trips did we take that were **not** in Florida?"

| | Result |
|---|---|
| **gbrain** | recall@5: **50%** — returns in-state trips first; "trip" similarity drowns out geography |
| **HydraDB** | recall@5: **100%** — surfaces Princeton/NJ visit + India/Taj Mahal trip |

### 2. Build an international photo book

> **You ask:** "Which events happened **outside the United States**?"

| | Result |
|---|---|
| **gbrain** | recall@5: **0%** — any travel chunk scores similarly |
| **HydraDB** | recall@5: **100%** — India/Taj Mahal memories ranked first |

This is the starkest gap in the entire benchmark.

### 3. Write your anniversary post

> **You ask:** "How did our relationship progress from casual dating to major commitments?"

| | Result |
|---|---|
| **gbrain** | recall@5: **33%** — finds one milestone, misses the arc |
| **HydraDB** | recall@5: **100%** — first car date → Valentine's dinner → buying a car together |

### 4. Plan a party (not a birthday)

> **You ask:** "What did we celebrate that was **NOT** a birthday?"

| | Result |
|---|---|
| **gbrain** | recall@5: **33%** — "birthday" in the query pulls birthday chunks first |
| **HydraDB** | recall@5: **83%** — Navratri, July 4th, Valentine's, Thanksgiving, Christmas |

Cosine similarity cannot negate. Graph + hybrid recall can.

### 5. Prepare to meet the family

> **You ask:** "How did we embrace each other's cultures?"

| | Result |
|---|---|
| **gbrain** | recall@5: **67%** |
| **HydraDB** | recall@5: **100%** — combines Navratri, Thanksgiving, Taj Mahal, Christmas |

### 6. Remember who did what

> **You ask:** "What did my partner specifically do for **my** birthday?"

Both systems: **100%**. When the signal is strong and unambiguous, vector search is fine.

### 7. Track your cap table from notes

> **You ask:** "Who invested in widget-co?"

| | Result |
|---|---|
| **gbrain** | R@5: **87%** (aggregate relational benchmark) |
| **HydraDB** | R@5: **100%** — alice, bob, fund-a from relationship prose |

### 8. Map your startup network

> **You ask:** "Who works at acme-co?"

| | Result |
|---|---|
| **gbrain** | R@5: **87%** |
| **HydraDB** | R@5: **100%** — dave, frank via employment edges |

---

## Why this happens: assemble vs native

```
gbrain (local)                         HydraDB (cloud)
─────────────────                      ─────────────────
Markdown / capture                     Markdown / capture
       ↓                                      ↓
Chunk + embed (pgvector)                 add_memory(infer=True)
       ↓                                      ↓
BM25 index                               native graph wiring
       ↓                                      ↓
Self-wired graph extractor               (done — no extra step)
       ↓                                      ↓
RRF fusion                               recall_preferences()
       ↓                                 dense + BM25 + graph
Reranker (optional)                           ↓
       ↓                                 top-k with citations
    top-k
```

gbrain's own docs credit the knowledge graph with **+31 points P@5** over graph-disabled retrieval. HydraDB ships that graph natively — you don't bolt it on after the fact.

The reranker ablation in our earlier stack reproduction tells the same story: reranking lifted fusion-only recall from **75% → 92%**, but it **reorders candidates retrieval already found**. It cannot surface a chunk that vector search never returned. HydraDB's graph arm finds chunks the vector arm misses entirely.

---

## What HydraBrain gives you today

HydraBrain is a Python reimplementation of gbrain's agent-facing surface, backed entirely by HydraDB:

```bash
pip install -e ".[bench]"
hydrabrain init          # one-time key setup
hydrabrain capture "…"   # ingest a thought
hydrabrain search "…"    # hybrid retrieval
hydrabrain think "…"     # cited synthesis (needs Gemini)
hydrabrain web           # chat UI over your brain
hydrabrain serve         # MCP: capture, search, think, graph, status
```

**Five MCP tools.** **Nineteen CLI commands.** Zero local Postgres.

Fork lineage: upstream gbrain TypeScript source is preserved unchanged in `src/` for fair comparison. New work lives in `hydrabrain/` and `bench/`.

---

## Reproduce it yourself

```bash
# Install
pip install -e ".[bench]"
export HYDRADB_API_KEY="hdb-…"
export GEMINI_API_KEY="…"   # required for live gbrain side in head-to-head

# Real gbrain vs HydraDB (Benchmark v2)
python3 -m bench.headtohead

# Relational network benchmark
python3 -m bench.relational

# User-facing demo video
python3 demos/record_user_comparison.py
open demos/recording/gbrain-vs-hydradb-user-demo.mp4
```

Raw JSON outputs:

- `bench/headtohead_results.json`
- `bench/relational_results.json`
- `demos/recording/comparison_manifest.json`

---

## What we are NOT claiming

Intellectual honesty matters more than a launch headline.

1. **Small corpora.** 19 personal memories and a startup-network fixture — not gbrain's 240-page relational corpus at scale.
2. **LongMemEval full split not run.** A partial oracle sample (18/500) did not favor HydraDB; the decisive `_s` split (500 questions × ~48 sessions) is still pending.
3. **HydraDB is hosted.** gbrain's PGLite is local-first and works offline. HydraDB trades that for zero ops — and depends on API availability.
4. **Aggregation is hard for both.** "List every holiday we shared" — 50% recall@5 for both systems. Exhaustive listing remains an open problem.
5. **Latency.** gbrain averaged ~1.3s/query (incl. CLI overhead); HydraDB ~3.7s over the network. Not a fair apples-to-apples latency comparison yet.

**Bottom line:** on hard relational queries — the ones that make a second brain feel smart — HydraDB's native graph consistently beats the real gbrain binary. The at-scale claim is still to be earned.

---

## What's next

- [ ] LongMemEval `_s` full split (500 × ~48 sessions)
- [ ] gbrain's 240-page relational corpus at published scale
- [ ] Latency-normalized comparison (embedded client vs API round-trip)
- [ ] Live side-by-side demo with Gemini key for gbrain snippet capture

---

## Try it

```bash
pip install -e ".[bench]"
cp .env.hydrabrain.example .env   # add HYDRADB_API_KEY
hydrabrain web --open
```

Get a free HydraDB key at [hydradb.com](https://hydradb.com). Read the full technical report in [`BENCHMARKS.md`](../../BENCHMARKS.md).

---

*HydraBrain is a fork of [garrytan/gbrain](https://github.com/garrytan/gbrain) (MIT). Benchmark harness and HydraDB integration are independent work in this repository.*
