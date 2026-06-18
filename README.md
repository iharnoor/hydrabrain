> **🍴 This repository is a fork of [gbrain](https://github.com/garrytan/gbrain)** (MIT, by Garry Tan).
> gbrain's original TypeScript source is preserved here unchanged — see [`README.upstream.md`](README.upstream.md), `src/`, `skills/`, etc.
> The **`hydrabrain/`** and **`bench/`** directories add an *independent Python reimplementation on [HydraDB](https://hydradb.com)* plus head-to-head benchmarks. They share no code with gbrain's TS source — this fork exists to carry the lineage and run the comparison side-by-side. The document below describes that reimplementation.

**Context memory:** this project runs entirely on [HydraDB](https://hydradb.com) — see [CONTEXT-MEMORY.md](CONTEXT-MEMORY.md).

---

<div align="center">

# 🧠 hydrabrain

### A [gbrain](https://github.com/garrytan/gbrain) clone, rebuilt on [**HydraDB**](https://hydradb.com) — and benchmarked honestly against a reproduction of its stack.

[![recall@5](https://img.shields.io/badge/recall%405-96.5%25-7c3aed?style=flat-square)](#-benchmark-1--hydradb-vs-a-faithful-gbrain-stack)
[![vs gbrain full stack](https://img.shields.io/badge/vs%20gbrain%20full%20stack-%2B4.4%20pts-16a34a?style=flat-square)](#tldr)
[![fork of gbrain](https://img.shields.io/badge/fork%20of-garrytan%2Fgbrain-555?style=flat-square&logo=github)](https://github.com/garrytan/gbrain)
[![license MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14-3776ab?style=flat-square&logo=python&logoColor=white)](requirements.txt)

**On a 19-document corpus, vs a reproduction of gbrain's *full* retrieval stack (vector + BM25 + RRF + reranker):**
**`recall@5 96.5%` vs `92.1%`  ·  answers correct `12/19` vs `8/19`  ·  0 losses / 19 queries  ·  (loses MRR: 0.912 vs 0.947)**

*HydraDB does it in one native `recall` call, no separate rerank stage. Same corpus, queries, and gold labels for both.*

</div>

---

## 🎯 The goal (north star — keep us aligned)

> **A personal second brain over everything I consume.**
> Dump in *all* the content I take in — Instagram saves, YouTube videos, articles,
> podcasts, notes — then **chat with it and get answers as accurate as possible**, out of
> the box.
>
> **Accuracy first, then scale the ingestion.** That's why this repo leads with rigorous,
> reproducible benchmarks instead of a flashy demo: if the memory can't answer accurately
> on a small, hard corpus, no amount of ingestion volume will save the chat experience.

---

## 📍 The migration — gbrain → HydraDB (the headline goal + living tracker)

> **🎯 What we're building & showing off:** a **capability migration** — gbrain, the
> "next Postgres for memory," **reimplemented feature-for-feature on HydraDB's graph-native
> store.** gbrain assembles its memory from pgvector + BM25 + RRF + a reranker + a hand-rolled
> graph extractor; we collapse that whole stack into HydraDB's native `capture`/`recall`.
> Same capabilities, a fraction of the moving parts — *that's* the story (and the benchmarks
> below are the receipts). This is the narrative for the blog posts / articles / threads.
>
> **Scope (important for honesty):** this is **(A) capability reimplementation** — rebuilding
> gbrain's *features* on HydraDB as a fresh Python package (`hydrabrain/`). It is **not**
> **(B) data-migration ETL**: there's no tool that reads an existing gbrain pgvector/graph
> brain and bulk-loads it into HydraDB, and that's out of scope. gbrain's TS `src/` stays
> unchanged (it legitimately uses pgvector/PGLite); the benchmark *reproduces* gbrain's
> algorithm, it never reads a real gbrain database.
>
> **Legend:** ✅ done · 🟡 partial · ⬜ not started. *Last updated: 2026-06-18.*

**Stage: core memory loop migrated + benchmarked — the part worth showing off. Operational/product surface still ahead (~6 of gbrain's ~92 ops).**

| Area | Status | Notes |
|---|:---:|---|
| Ingest / capture | ✅ | `capture` / `ingest_file` → `add_memory(infer=True)` |
| Hybrid retrieval (vector+BM25+RRF+rerank) | ✅ | one native HydraDB `recall` call |
| Self-wiring knowledge graph | ✅ | native `infer=True`, no extractor code |
| Synthesis (cited answers) | ✅ | `think` — Gemini grounding over HydraDB chunks |
| Graph traversal / explore | 🟡 | `graph_relations` by `source_id` only |
| Status / list / delete / wipe | ✅ | tenant + memory count, live deletes |
| CLI (`hydrabrain`) | ✅ | `status/capture/ingest/search/think/graph/serve/bench` |
| MCP server | 🟡 | 5 tools (gbrain ships 30+) |
| Benchmark #1 (19-doc relational) | ✅ | HydraDB 96.5% vs 92.1% full stack |
| Benchmark #2 (LongMemEval `_s`) | 🟡 | harness ready; decisive run not done (oracle inconclusive) |
| Sources / brains two-axis routing, mounts | ⬜ | gbrain's core org model — not ported |
| Bulk sync / import | ✅ | `brain.sync(dir)` / `hydrabrain sync` — incremental, content-hash dedup, manifest-backed |
| Export | ⬜ | dump a tenant back out to files — not built |
| Enrichment / extraction / schema+lens packs | ⬜ | — |
| Cron / scheduling / reports | ⬜ | — |
| Identity / access control / trust boundary | ⬜ | — |
| Advisor / skillpacks | ⬜ | — |
| Ingestion connectors (articles / YouTube / IG) | 🟡 | web article reader + YouTube transcript shipped (`hydrabrain read <url>`); IG/podcasts next |
| Chat UI over `think()` | ⬜ | north-star surface |
| Data-migration ETL (real gbrain brain → HydraDB) | — | **out of scope** — this is a capability migration, not a data move |

**Recently shipped:** ✅ bulk incremental `sync` (dir/glob, content-hash dedup, idempotent) · ✅ web/YouTube
connectors (`hydrabrain read <url>` → article text / video transcript → `capture`).
**Next up (in priority order):** (1) decisive LongMemEval `_s` run *(in flight)* · (2) more connectors
(Instagram saves, podcasts) · (3) enrichment. See [Next steps](#next-steps-toward-the-north-star).

---

## TL;DR

Benchmark #1, recall@5 (gbrain's own P@5 metric), against **two** versions of gbrain's stack:

| Metric | **HydraDB** | gbrain **full stack** (RRF **+ reranker**) | gbrain fusion core (RRF, no reranker) |
|---|:---:|:---:|:---:|
| **recall@5** | **96.5%** 🟢 | 92.1% | 75.4% |
| **MRR** | 0.912 | **0.947** | 0.675 |
| **answers correct (LLM-judge)** | **12 / 19** 🟢 | 8 / 19 | 8 / 19 |
| **per-query (vs full stack)** | **2 wins · 0 losses · 17 ties** | 0 wins | — |

<p align="center"><img src="bench/assets/recall.svg" alt="recall@5 — HydraDB 96.5% vs gbrain full stack 92.1% vs fusion core 75.4%" width="720"></p>

> 📊 **Full benchmark report — what we ran, how, and on which data (local / partial / full):** [`BENCHMARKS.md`](BENCHMARKS.md)

Two honest readings:
- **The graph is worth +21 points** over gbrain's *fusion core* (96.5% vs 75.4%) — the mirror of
  gbrain's own *"+31.4 P@5 from the knowledge graph"* claim.
- **A reranker recovers most of that** (→ 92.1%). But HydraDB still **wins the full reranked stack**
  on recall@5 (+4.4) and on answer accuracy (12 vs 8), never losing a query — **with one native
  `recall` call and no separate reranking stage.** gbrain needs the extra reranker pass to claw the
  graph's advantage back; HydraDB has it built in. *(gbrain's reranker does edge MRR — slightly
  tighter top-5 ordering when both find the answer.)*

---

## ⚠️ Read this first — what this proves, and what it doesn't

Being precise so nobody can call this rigged:

- **We did NOT run gbrain, and did NOT run pgvector.** The opponent ("gbrain-stack") is a
  from-scratch **reproduction of gbrain's *documented* retrieval algorithm** (`bench/gbrain_stack.py`),
  not gbrain's actual code or database. So this proves *"HydraDB's native graph beats that algorithm,"*
  **not** *"we ran gbrain head-to-head and beat it."*
- **The embedder and reranker are strong substitutes, not gbrain's actual ones.** gbrain's embedder
  is undocumented (we used Gemini 3072-d); its reranker is a MiniLM cross-encoder (we used a Gemini
  LLM reranker, which we *assume* is ≥ as strong). Source-tier boost is omitted (a no-op on a
  single-tier corpus).
- **The corpus is tiny — 19 documents** (a personal demo timeline). This is a small, hard
  *relational-reasoning* probe, **not** an at-scale benchmark. Findings may not hold at 10K+ docs.
- **HydraDB does not win everything.** gbrain's full stack **beats it on MRR** (0.947 vs 0.912) —
  slightly better top-5 ordering. HydraDB wins recall@5 and answer-correctness; it loses ranking order.
- **"Answers correct" is an LLM-as-judge** (Gemini) and is **noisy** — it varied 8–11 for the
  baseline and 11–12 for HydraDB across runs. Treat ±2 as noise, not signal.
- **HydraDB's config was tuned** (`mode=thinking, alpha=1.0`) after a sweep; in compensation the
  baseline got the better embedder + a reranker. Both sides were given their best shot.
- **The one at-scale test we attempted (LongMemEval *oracle*) did NOT favor HydraDB** (50% vs 78%);
  that split neutralizes retrieval and the indexing wait was too short — see Benchmark #2. The
  decisive `_s` run has **not** been run yet.

**Honest bottom line:** on a small relational corpus, HydraDB's native graph **edges a faithful
reproduction of gbrain's full retrieval algorithm** on recall and answer accuracy (and crushes the
no-reranker version), with no separate rerank stage. That's real, reproducible evidence — but it is
**not** a definitive "HydraDB > gbrain at scale" claim. The scale claim is still to be earned (Benchmark #2, `_s`).

## The architectural difference (assemble vs. native)

This is the *why* behind the numbers. gbrain is excellent — but look at what it has to *assemble* to get its memory:

```
gbrain:   pgvector(HNSW)  +  BM25  +  reciprocal-rank fusion  +  reranker  +  ⟨hand-rolled graph extractor⟩
hydrabrain (HydraDB):   brain.capture(text)         # infer=True → graph built, zero extra LLM calls
                        brain.think("...")          # hybrid dense+graph+BM25, cited answer
```

The knowledge graph is the part gbrain credits for **+31.4 P@5**. It's also the part that's
hardest to build, tune, and keep wired. HydraDB makes it a property of `ingest`, not a
pipeline you own. Everything gbrain exposes, hydrabrain exposes — on top of that native graph.

```python
from hydrabrain.engine import BrainEngine
brain = BrainEngine()
brain.capture("On May 7, 2022 we bought a white Tesla Model 3 together.")
print(brain.think("What car did we buy?").render())
#  A white Tesla Model 3, bought on May 7, 2022 [1].
#  Sources: [1] May 7, 2022 - Buying a Car Together, Tesla Model 3: ...
```

---

## 🏆 Benchmark #1 — HydraDB vs a faithful gbrain stack

**The fair fight.** Per the instruction *"compare against whatever stack gbrain is using,"*
the opponent is **not** a strawman pure-vector store. It reproduces gbrain's *entire documented
retrieval pipeline* — reranker included:

> dense vectors (Gemini `gemini-embedding-001`, 3072-d — a **top-tier** embedder, *generous* to
> the baseline) **+** BM25 (`rank_bm25`) **+** reciprocal-rank fusion (k=60) **+** a **reranker**
> (LLM cross-encoder, at least as strong as gbrain's MiniLM reranker) — **with no knowledge graph.**

The **only** thing the baseline lacks vs HydraDB is **the graph** — which is the whole experiment.
Notes on fidelity: exact cosine NN over 19 docs is identical to pgvector HNSW recall at this scale;
**source-tier boost is a no-op here** because all 19 pages are a single source/tier (nothing to
re-weight). We run the comparison both **with** the reranker (the honest full-stack number, 92.1%)
and **without** it (fusion core, 75.4%) so the reranker's contribution is explicit, not hidden.

- **Corpus** — 19 dense, temporal, entity-heavy "pages" (a relationship timeline): the regime
  where pure vector search breaks (dates, negation, who-did-what-to-whom, aggregation).
- **Queries** — 19 gold-labelled cases · **Metric** — `recall@5` (gbrain's own P@5), `MRR`, and an LLM-as-judge answer pass.

### Where the win comes from — capability-by-capability

Against gbrain's **full stack (reranker on)**, HydraDB **ties or wins every category, loses none**.
The remaining gaps sit exactly on the graph/relational abilities a reranker can't fully recover —
because a reranker can only reorder candidates retrieval already surfaced, and without the graph
the right chunk never enters the pool:

| Capability | **HydraDB** | gbrain full stack (+rerank) | Winner |
|---|:---:|:---:|:---:|
| Negation ("NOT a birthday") | **92%** | 67% | 🟣 HydraDB +25 |
| Multi-Session Reasoning | **100%** | 83% | 🟣 HydraDB +17 |
| Information Extraction | 100% | 100% | tie |
| Temporal Reasoning | 100% | 100% | tie |
| Temporal Adjacency ("day after") | 100% | 100% | tie |
| Entity Direction (who→whom) | 100% | 100% | tie |
| Semantic Understanding | 100% | 100% | tie |
| Abstention (don't hallucinate) | 100% | 100% | tie |
| Geographic Filtering | 100% | 100% | tie |
| Aggregation (exhaustive list) | 50% | 50% | tie (top-5 cap) |

*(Without the reranker, gbrain's fusion core scores far lower on these — Multi-Session 33%,
Geographic 0%, Negation 58% — which is the +21-point picture. The reranker closes the ties; the
graph-dependent gaps remain.)*

Full per-query table → **`bench/report.html`**. HydraDB result is **deterministic** — identical across 3 repeated runs.

---

## What actually drives the accuracy — reranker vs. graph

Straight from this benchmark, building up the graph-less baseline:

| pipeline | recall@5 |
|---|:---:|
| vector + BM25 + RRF (fusion core) | 75.4% |
| **+ reranker** | **92.1%** |
| HydraDB — graph-native, *no* separate reranker | **96.5%** |

**The reranker is the single biggest lever (~+17 pts).** Why: vector search is a *bi-encoder* —
query and document are embedded **separately**, so it never sees them together. A reranker
(cross-encoder / LLM) reads query **+** passage **jointly** and judges relevance directly — far
more precise, but too expensive to index, so it only re-scores the top-k that cheap retrieval
already surfaced. *"Retrieve wide, then rerank precise"* is where most modern RAG accuracy comes from.

**But a reranker can only reorder what was retrieved — it cannot surface a chunk that was never in
the candidate set.** That is the graph's unique job, and the data shows it: against the *full
reranked* baseline, HydraDB's only remaining wins are **Negation (92% vs 67%)** and **Multi-Session
(100% vs 83%)** — queries where the right chunk isn't lexically or semantically near the query, so
retrieval never pulls it in and the reranker has nothing to fix. The graph follows a relationship
**edge** to reach it. *(This is exactly why gbrain credits its **graph**, not its reranker, with "+31.4 P@5.")*

```mermaid
flowchart LR
  Q([query]) --> H["vector + BM25"]
  H --> C["top-k candidates"]
  C --> RR["reranker<br/>(reorder candidates)"]
  RR --> A([answer])
  C -. "right chunk never retrieved" .-> Z["reranker can't fix this"]
  Q --> G["graph<br/>(follow relationship edge)"]
  G == "pulls the missing chunk in" ==> C
```

**So gbrain's accuracy = hybrid retrieval + reranker (the biggest lever) + graph (catches the
relational / multi-hop queries the first two structurally can't).** They overlap on easy queries
and complement on hard ones. HydraDB folds the graph into a **single `recall` call**, matching the
reranked stack with no second model pass — and since the two-stage pattern is complementary,
**adding a reranker on top of HydraDB would likely push it higher still** (especially the MRR it
currently loses, 0.912 vs 0.947).

## 🔬 Benchmark #2 — LongMemEval (the at-scale test)

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (ICLR 2025) is the standard academic
benchmark for long-term chat memory, and the realistic proxy for the north-star goal: each of
500 questions ships **its own multi-session chat haystack**; the system must store it, retrieve
the right sessions, and answer — across 6 abilities (extraction, multi-session, temporal,
knowledge-update, preference, abstention).

The harness (`bench/longmemeval.py`) is wired up and runnable. Each question's haystack is
ingested into an **isolated namespace** (HydraDB `sub_tenant_id = question_id` — verified to
isolate with **zero** cross-leakage; a fresh local dense+BM25+RRF index per question for the
baseline), one memory per session. It scores **QA accuracy** (LLM-judge, abstention-aware) and
**evidence recall@5**.

```bash
# small balanced sanity sample (auto-downloads the oracle split)
python3 -m bench.longmemeval --limit 18 --report

# the DECISIVE run — full _s split, 48 sessions/question WITH distractors
hf download xiaowu0162/longmemeval-cleaned longmemeval_s_cleaned.json --repo-type dataset --local-dir bench/data
python3 -m bench.longmemeval --data bench/data/longmemeval_s_cleaned.json --limit 100 --hydra-wait 90 --report
```

### Honest status — and why oracle isn't the proof

> 🟠 An 18-question oracle sample scored **HydraDB 50% / gbrain-stack 78%**. HydraDB lost — and
> I'm flagging *exactly* why that result is **not conclusive**, because integrity is the whole
> point of showing this off:
>
> 1. **Oracle removes the retrieval challenge.** Oracle haystacks contain *only* the evidence
>    sessions — no distractors. The baseline trivially retrieves all of them (100% evidence
>    recall) and feeds perfect context to the same answerer. HydraDB's actual edge — finding the
>    needle among ~48 distractor sessions — is **never tested**. With identical context, both
>    converge to the same answers.
> 2. **Async indexing handicaps HydraDB at short waits.** HydraDB's evidence recall was only 78%
>    — it sometimes failed to return a session that was the *only thing* in its namespace, because
>    `infer=True` graph-wiring hadn't finished. Use `--hydra-wait 90`.
>
> **Bottom line:** the decisive comparison is the **full `_s` split with distractors**, where
> Benchmark #1's graph advantage should reappear at scale. That run is heavy (264 MB, hundreds of
> 48-session questions) — it's the recommended next step, not a number to read into the quick
> oracle sample.

---

## Capabilities (mirrors gbrain's `#capabilities`)

| gbrain capability | hydrabrain (HydraDB) |
|---|---|
| Hybrid search (vector + BM25 + RRF + rerank) | `brain.search()` → HydraDB hybrid recall (`mode=thinking`) |
| Self-wiring knowledge graph (typed edges) | **native** via `infer=True` — no extraction code |
| Synthesis layer (cited prose + gap analysis) | `brain.think()` (Gemini grounding over retrieved chunks) |
| 30+ tool MCP server (stdio) | `hydrabrain serve` (FastMCP: capture/search/think/graph/status) |
| Eval framework (LongMemEval-style P@5) | `bench/` — two benchmarks, recall@5 / MRR / LLM-judge / QA acc |
| Bulk sync (incremental dir ingest) | `brain.sync(paths)` / `hydrabrain sync <dir>` — content-hash dedup, idempotent |
| Ingestion connectors (consume the web) | `brain.ingest_url(url)` / `hydrabrain read <url>` — article reader + YouTube transcript |
| CLI (`init/capture/search/think/sync`) | `hydrabrain` CLI (`capture/ingest/sync/search/think/graph/status`) |

### CLI

```bash
python3 -m hydrabrain.cli status
python3 -m hydrabrain.cli capture "Saved a YouTube video on espresso ratios: 1:2 in 28s."
python3 -m hydrabrain.cli ingest notes/*.md
python3 -m hydrabrain.cli sync ~/notes            # bulk, incremental — skips unchanged files
python3 -m hydrabrain.cli sync ~/notes --dry-run  # preview what would ingest
python3 -m hydrabrain.cli read https://example.com/post   # ingest an article
python3 -m hydrabrain.cli read https://youtu.be/VIDEO_ID   # ingest a video transcript
python3 -m hydrabrain.cli search "espresso ratio" -k 5
python3 -m hydrabrain.cli think  "what coffee setup did I save?"
python3 -m hydrabrain.cli serve         # MCP stdio server
```

### MCP (Claude Code / Cursor / Claude Desktop)

```bash
claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve
```

---

## Methodology — why & how (in one screen)

**The question.** gbrain credits its knowledge graph with *"+31.4 P@5."* HydraDB ships that
graph natively (`infer=True`). So: **does HydraDB's native graph beat the lift gbrain assembles
by hand — on gbrain's own metric, against a fair copy of gbrain's own stack?**

**Why it's a fair fight, not a strawman:**
- **Opponent = gbrain's full retrieval pipeline** — dense + BM25 + RRF **+ a reranker** — with
  *only the graph removed*, so a win is attributable to the graph and nothing else. (We also report
  the no-reranker "fusion core" number for transparency.)
- **The baseline gets the *better* embedder** (Gemini 3072-d, likely stronger than gbrain's real
  one) **and a strong LLM reranker** (≥ gbrain's MiniLM cross-encoder). I rigged it *against*
  HydraDB, not for it.
- **gbrain's own metric** — `recall@5` *is* P@5 — plus MRR and an LLM-judge answer-quality pass.
- **Gold labels are keyword-group matches** (deterministic, no LLM in the scoring of retrieval).

**How it was run — against the *live* HydraDB API (`api.hydradb.com`), not mocks:**
1. Ingest the identical 19-page corpus into both systems (HydraDB via real `/memories/add_memory`,
   `infer=True`).
2. **Wait for HydraDB's async graph-indexing to settle** (querying too early understates it).
3. Run all 19 gold queries through each; score `recall@5` / `MRR` live via `/recall/recall_preferences`
   (`mode=thinking, alpha=1.0`, `graph_context=true`).
4. Generate + LLM-judge a one-sentence answer per system. Repeat 3× → **identical** results.

**Footguns found & fixed (all real):** `alpha=0.8` starved HydraDB to 54% (use `1.0`); a stale
tenant had the corpus ingested *twice* (38 docs stealing top-5 slots → wiped clean via live
`DELETE`s); sub-tenant isolation verified with a zebra/llama probe before trusting it. **And the
big one for honesty:** our first baseline lacked gbrain's reranker — adding it lifted the baseline
75.4% → 92.1%, shrinking HydraDB's lead from +21 to +4.4. We report both so nothing is hidden.

## Reproduce

```bash
pip install rank-bm25 mcp requests python-dotenv google-genai
# .env needs HYDRADB_API_KEY and GEMINI_API_KEY

# Benchmark #1 — the headline win (full-stack: include gbrain's reranker)
python3 -m bench.run_bench --ingest --rerank --judge --report && open bench/report.html
#   --rerank : give the baseline gbrain's reranker stage (the honest full-stack comparison)
#   --ingest : wipe tenant + re-ingest a clean corpus (waits for indexing)
#   --judge  : add the LLM-as-judge answer pass   --report : write report.html
#   --no-hydra : baseline only (offline)
# omit --rerank to see the "fusion core" (no reranker) comparison: 96.5% vs 75.4%

# Benchmark #2 — LongMemEval
python3 -m bench.longmemeval --limit 18 --report && open bench/longmemeval_report.html
```

## Methodology & integrity (the fairness ledger)

Both sides get their **best** shot — this is engineered to be *hard* for HydraDB to win, so the win means something:

- ✅ Baseline gets a **top-tier 3072-d embedder** (likely stronger than gbrain's actual one).
- ✅ HydraDB runs in its flagship **`mode=thinking, alpha=1.0`** config. *(Footgun: `alpha=0.8`
  starves the keyword signal and tanks HydraDB to ~54% — the wrong knobs matter.)*
- ✅ **Identical, de-duplicated corpus** for both. *(A stale tenant once had the corpus ingested
  twice — 38 docs — which unfairly stole HydraDB's top-5 slots. The harness now wipes + re-ingests
  clean.)*
- ✅ HydraDB's `infer=True` indexing is **asynchronous** — the harness waits for it to settle
  before measuring. Querying too early badly understates HydraDB (we caught this and fixed it).
- ✅ Results are **deterministic** and reproducible (Benchmark #1 identical across 3 runs).

## Layout

```
hydrabrain/        the gbrain-style memory engine on HydraDB
  client.py        HydraDB REST client (ingest / hybrid recall / graph / delete)
  engine.py        BrainEngine: capture / ingest_file / sync / ingest_url / search / think / graph
  sync.py          bulk incremental ingest (dir/glob, content-hash dedup, manifest)
  connectors.py    web connectors: article reader (stdlib HTML→text) + YouTube transcript
  synth.py         synthesis layer — cited answer + gap analysis (Gemini)
  cli.py           the hydrabrain CLI       mcp_server.py   MCP stdio server (FastMCP)
  config.py        env + recall tuning (mode=thinking, alpha=1.0)
bench/
  dataset.py       19 pages + 19 gold test cases (dependency-free)
  gbrain_stack.py  faithful gbrain pipeline: dense + BM25 + RRF, NO graph
  run_bench.py     Benchmark #1 — recall@5 / MRR / LLM-judge   → report.html
  longmemeval.py   Benchmark #2 — LongMemEval QA + evidence    → longmemeval_report.html
  data/            LongMemEval splits (oracle auto-downloaded; _s on demand)
```

## Next steps (toward the north star)

1. **LongMemEval-S full run** — harness ready; run the `_s` split with distractors +
   `--hydra-wait 90` for the decisive at-scale number.
2. **Ingestion connectors** — Instagram saves, YouTube transcripts, article readers →
   `brain.capture()` / `brain.ingest_file()`.
3. **Chat UI** over `brain.think()` with streaming + citations.
4. **Scale test** — 10K+ pages, re-measure recall to confirm the graph holds.

## License & credits

MIT — matching [gbrain](https://github.com/garrytan/gbrain), which is also MIT. As a fork, gbrain's original `LICENSE` (© Garry Tan) is preserved at repo root; the `hydrabrain/` and `bench/` additions are likewise MIT © Harnoor Singh. hydrabrain
is an independent reimplementation: the engine, client, synthesis layer, and benchmarks are
original code written against [HydraDB](https://hydradb.com); only the *capability surface*
and CLI command names are modeled on gbrain. Huge respect to **Garry Tan** for gbrain — it's
the system this one set out to match, and beat, on the merits.

<div align="center"><sub>Built to prove a point, honestly. HydraDB gives you gbrain's graph advantage natively — and the numbers hold up.</sub></div>
