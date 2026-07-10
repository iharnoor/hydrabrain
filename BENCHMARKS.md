# Benchmark Report — hydrabrain (HydraDB) vs the real gbrain binary

**Author:** Harnoor Singh · **Repo:** fork of [garrytan/gbrain](https://github.com/garrytan/gbrain)

This report records exactly what we benchmarked, how, on which data, and the verbatim
numbers our harness produced. Every result here regenerates from the commands in §8, and
the raw outputs are the committed JSON files in §9.

> **Note on an earlier version of this report.** A prior BENCHMARKS.md reported a HydraDB
> win (recall@5 96.5% vs 92.1%) against a *reproduction of gbrain's pipeline with the
> knowledge graph removed*. That was not a HydraDB-vs-gbrain result — it only showed
> "graph beats no-graph," which is what gbrain itself claims. Those numbers are **retired**.
> Everything below runs against the **real gbrain binary** that ships in this fork's `src/`
> (PGLite, Gemini embeddings, typed-edge graph ON, relational arm engaged), on the same
> corpus, with both systems building their own graph.

---

## 0. TL;DR

| Benchmark | Opponent | HydraDB | Opponent | Verdict |
|---|---|:---:|:---:|---|
| **Relational R@5** — gbrain handed a **perfect graph** | real gbrain, graph ON | **88.4%** | 77.4% | HydraDB **+11** |
| **Relational R@5** — both **auto-extract from prose** | real gbrain, graph ON | **88.0%** | 50.0% | HydraDB **+38** |
| **1-hop R@5** — perfect graph | real gbrain | 92.3% | **100.0%** | gbrain **+8** |
| **1-hop R@5** — auto-extract | real gbrain | **91.4%** | 84.2% | HydraDB **+7** |
| **2-hop / multi-hop R@5** — perfect graph | real gbrain | **86.0%** | 63.8% | HydraDB **+22** |
| **2-hop / multi-hop R@5** — auto-extract | real gbrain | **86.0%** | 29.4% | HydraDB **+57** |
| **MRR** — perfect graph | real gbrain | **0.894** | 0.826 | HydraDB |
| **Retrieval code surface** | real gbrain | **327 LOC / 1 call** | 9,345 LOC / 6 stages | HydraDB **29×** |
| **LongMemEval-S QA accuracy** (at scale) | **BM25 baseline** | **38.1%** | 16.7% | HydraDB (vs BM25, *not* gbrain) |
| **LongMemEval oracle QA** (90 q, fixed harness) | gbrain-stack reproduction (chunked, no graph) | 45.6% | **56.7%** | **baseline wins QA** (evidence recall: HydraDB **100%** vs 98.9%) |

**Honest one-liner:** fed the same prose, HydraDB's graph-native retrieval beats the real gbrain
binary **overall** and **dominates multi-hop under every condition** — in one `recall()` call vs
a 6-stage pipeline. gbrain edges out **single-hop only when handed a hand-built perfect graph**;
when both extract from prose, HydraDB wins single-hop too. The at-scale result is against a BM25
baseline, **not** gbrain — that run is still owed. And on the LongMemEval oracle split HydraDB
**loses QA to a graph-less baseline** (45.6% vs 56.7%) despite perfect evidence recall — a real
weakness on single-needle answer synthesis, reported as such (§8).

**On the single-hop question specifically:** HydraDB is *not* weak at single-hop. 92% is its
**strongest** tier. gbrain's 1-hop win (100 vs 92) exists only inside the artificial
perfect-graph control; under realistic extraction HydraDB wins single-hop (91 vs 84). The claim
"single-hop is bad for HydraDB, multi-hop is better" is false — that shape describes *gbrain*
(100 → 64), not HydraDB (92 → 86).

---

## 1. What we ran

- **Benchmark #1 — fair relational head-to-head** (`bench/relational_v2.py`). A synthetic
  VC/startup network (~50 entities: 16 companies, 30 people, 4 funds), 149 gold-labelled queries
  spanning 1-hop ("who works at company-00") and 2-hop ("which fund backed the company person-00
  works at"). The regime where a graph should matter. Metrics: P@5, R@5 (gbrain's own pair) + MRR,
  broken down by hop depth.
- **Benchmark #2 — architecture** (`bench/architecture.py`). Deterministic, offline: lines of
  retrieval code and services a maintainer owns, on each side.
- **Benchmark #3 — LongMemEval-S at scale** (`bench/lme_scale.py`). The standard long-term-memory
  benchmark, 42 questions × ~48 distractor sessions each. **Opponent is a BM25 baseline, not
  gbrain.**
- **Benchmark #4 — LongMemEval oracle** (`bench/longmemeval.py`). 90 questions (15 per ability),
  evidence-only haystacks. Opponent: a gbrain-stack reproduction (dense+BM25+RRF, chunked like
  real gbrain, no graph). The harness went through a five-bug fairness rebuild first — see §8.

---

## 2. Systems under test

**HydraDB** — graph-native context store, hit over the **live API** (`api.hydradb.com`):
- ingest: `add_memory(infer=True)` — builds the typed-edge graph, no extractor code from us
- recall: one native `recall` call (`mode=thinking`, `graph_context=true`)
- tenant isolation per source via `sub_tenant_id`

**gbrain (real binary)** — the TypeScript gbrain that ships in this fork's `src/`, driven via
`bun src/cli.ts`:
- PGLite engine, Gemini embeddings (`gemini-embedding-001` via `GOOGLE_GENERATIVE_AI_API_KEY`)
- typed-edge graph **on**; edges built from prose via `extract links --ner` (deterministic
  schema-pack regex over the `gbrain-base` pack: `invested_in` / `works_at` / `founded` / `advises`)
- relational arm engaged per query via `relational:true` (the graph walk is otherwise dormant on
  the vector-dominant default path)

Both sides build their graph **their own documented way, from the same prose.**

---

## 3. The fairness bugs we found in our *own* harness

An earlier harness showed a HydraDB blowout. It was wrong — unfair to gbrain. Three bugs, all
now guarded:

1. **gbrain's graph wasn't being built.** `put`/`embed` alone only wires `[[wikilinks]]` +
   frontmatter, not prose like "alice invested in widget-co." So the graph was **empty** and
   gbrain's relational arm walked nothing. Fixed: run `extract links --ner`; an **integrity gate
   aborts scoring if the typed-edge count is 0.**
2. **Edges were mis-typed.** On dense prose, gbrain's NER labelled `works_at` as `founded`. The
   gate now checks edge-type **correctness**, not just count.
3. **gbrain's relational arm sat dormant.** The default query path is vector-dominant; the graph
   walk only engages with `relational:true`. Fixed: on.

We then went further and **handed gbrain a 100%-correct graph** (verified: 39/39 gold edges built
with correct types) via its own published seeding method — the "perfect graph" control — so a
HydraDB win can't be dismissed as "you broke gbrain's extraction."

---

## 4. Metrics (definitions)

- **R@5** — fraction of a query's gold answers matched by ≥1 result in the top-5.
- **P@5** — fraction of the top-5 results that are gold.
- **MRR** — 1 / rank of the first gold result.
- Deterministic scoring; no LLM in the relational scorer.

---

## 5. Benchmark #1 — relational head-to-head (n = 149, k = 5)

### 5a. gbrain handed a perfect graph (`--seed-edges`) — the rebuttal-proof control

Edges: 39 built / 39 correct-type / 39 gold-expected.

| Metric | gbrain (perfect graph) | **HydraDB** | Edge |
|---|:---:|:---:|---|
| **R@5** overall | 77.4% | **88.4%** | HydraDB **+11** |
| **P@5** overall | 25.6% | **28.9%** | HydraDB |
| **MRR** | 0.826 | **0.894** | HydraDB |
| **1-hop** R@5 (n=56) | **100.0%** | 92.3% | **gbrain +8** |
| **2-hop** R@5 (n=93) | 63.8% | **86.0%** | HydraDB **+22** |

### 5b. Both auto-extract from prose (the realistic condition)

Edges (gbrain NER): 37 built / **17 correct-type** / 39 gold-expected — i.e. gbrain's regex NER
recovered only **~44%** of the relationships correctly. That is *why* its realistic numbers drop.

| Metric | gbrain (NER) | **HydraDB** | Edge |
|---|:---:|:---:|---|
| **R@5** overall | 50.0% | **88.0%** | HydraDB **+38** |
| **MRR** | 0.317 | **0.894** | HydraDB |
| **1-hop** R@5 (n=56) | 84.2% | **91.4%** | **HydraDB +7** |
| **2-hop** R@5 (n=93) | 29.4% | **86.0%** | HydraDB **+57** |

### 5c. Reading the two conditions

- **Multi-hop is HydraDB's decisive, condition-independent win.** 86.0% both ways vs gbrain's 63.8%
  (perfect graph) / 29.4% (realistic). Even hand-built to perfection, gbrain's traversal degrades
  as soon as the destination shares no words with the query.
- **Single-hop is not a HydraDB weakness.** 92.3% is HydraDB's best tier. gbrain only wins
  single-hop (100 vs 92) with the artificial perfect graph; under realistic extraction HydraDB
  wins single-hop too (91.4 vs 84.2).
- **HydraDB's biggest edge is robust auto-extraction from raw prose.** Feed both the same
  documents and HydraDB builds the more useful graph (88% vs 50% overall).

---

## 6. Benchmark #2 — architecture (deterministic, offline)

HydraDB's retrieval surface is **~29× less code**: **327 LOC** behind one `recall()` call vs
**9,345 LOC across 32 files** for gbrain's 6-stage pipeline (dense + BM25 + RRF + reranker +
query-expansion + graph). **1 external service vs 4.** Regenerate: `python3 -m bench.architecture`.

---

## 7. Benchmark #3 — LongMemEval-S at scale (vs BM25, NOT gbrain)

42 questions × ~48 distractor sessions each (`longmemeval_s_cleaned`), judge = Claude Haiku 4.5.

| | HydraDB | BM25 baseline |
|---|:---:|:---:|
| QA accuracy | **38.1%** | 16.7% |
| evidence recall@5 | 97.6% | 97.6% (tied) |

**Read this carefully:** the opponent is **BM25, not gbrain.** With evidence recall tied, this
says HydraDB turns retrieved evidence into correct answers far better than lexical search — and
**nothing about gbrain.** Running LongMemEval-S against the real gbrain binary is the next owed
result.

---

## 8. Benchmark #4 — LongMemEval oracle, 90 questions (2026-07-10, fixed harness)

The oracle split of LongMemEval: each question ships ONLY its evidence sessions (1–4, no
distractors). 90 questions, balanced 15 × 6 ability types. Opponent: the gbrain-stack
reproduction (dense Gemini embeddings + BM25 + RRF, **chunked like real gbrain**, no graph, no
reranker). Answerer + judge: Claude Haiku 4.5, identical for both sides.

### 8a. Five harness bugs we fixed before trusting a number

An earlier 18-question version of this benchmark showed the baseline winning QA 77.8% vs 50.0%.
A review flagged three problems; fixing those exposed two more. All five are now guarded:

1. **Blind sleep raced HydraDB's async indexing.** Fixed: poll the namespace's row count until
   it reaches the ingested count and stops changing (`bench/hydra_wait.py`).
2. **The baseline didn't chunk.** It indexed whole multi-topic sessions as single units; on
   oracle haystacks (fewer units than top-k) it returned everything and "won" recall by
   default. Fixed: the baseline now chunks exactly like real gbrain (300 words / 50 overlap /
   6000-char cap — verified against gbrain's own chunker source).
3. **n=18 (3 per type) was noise.** One flipped answer swung a category ±33 pp. Fixed: n=90
   (15 per type; ±10 pp overall, per-type gaps ≥25 pp start to mean something).
4. **Row visibility ≠ retrievability** (found while validating fix 1). HydraDB lists a memory
   before its index is queryable; count-based waiting still under-measured recall — 17/52
   "misses" flipped to hits on re-query. Fixed: also poll the real query until its result set
   is non-empty and stable across consecutive polls.
5. **Cross-run namespace pollution** (found while validating fix 4). Prior runs on the same
   tenant left ~48 distractor sessions in 35 of 52 namespaces (LongMemEval splits share
   question ids), so HydraDB searched a ~50-session haystack while the baseline searched 1–4.
   Fixed: each run now ingests into a verified-empty namespace.

Bugs 1, 4 and 5 penalized only HydraDB; bug 2 handed the baseline its recall score; bug 3 made
every per-type number untrustworthy. Full detail lives in the harness docstrings.

### 8b. Results (n=90, top-k=5)

| Metric | **HydraDB** | gbrain-stack (chunked, no graph) |
|---|:---:|:---:|
| evidence recall@5 | **100.0%** (90/90) | 98.9% (89/90) |
| QA accuracy | 45.6% | **56.7%** |

QA by ability (n=15 each — single flip ≈ 6.7 pp):

| Ability | HydraDB | baseline |
|---|:---:|:---:|
| single-session-assistant | 86.7% | 86.7% |
| single-session-user | 73.3% | 80.0% |
| knowledge-update | 53.3% | 53.3% |
| single-session-preference | 26.7% | **46.7%** |
| temporal-reasoning | 20.0% | **46.7%** |
| multi-session | 13.3% | 26.7% |

### 8c. Honest reading

- **Retrieval is not the problem — HydraDB's recall is perfect here** (and the earlier
  "HydraDB can't find things" signal was 100% harness artifact). But recall@5 on the oracle
  split is near-ceiling for everyone by design (tiny haystacks); it is not a differentiating
  metric — and that cuts against our own 90/90 too: 45 of 90 questions have single-session
  haystacks, where "found the evidence" collapses to "returned anything at all". Treat 100%
  as a health check (no indexing losses, no empty result sets — 89 of 90 scored on the
  question's own namespace; one scored via a fresh namespace after a post-delete indexing
  failure, noted in its row). See Benchmark #3 for recall under real distractor load.
- **HydraDB loses QA on this split, 45.6% vs 56.7%.** Both systems retrieve the right session;
  answers generated from the baseline's chunks are judged correct more often. The gap
  concentrates in temporal-reasoning and preference questions. At n=90 the ~11 pp overall gap
  is at the edge of significance, but it has been directionally stable all run — we report it
  as a loss, not noise.
- **This is a loss to a baseline weaker than gbrain** (no graph, no reranker). It does NOT
  show "gbrain beats HydraDB" — the real-gbrain at-scale run is still owed — but it is a real
  result about answer synthesis from HydraDB's retrieved chunk shapes on single-needle
  questions, and we're not burying it.

### 8d. Operational notes for reproducers (cost us a day — read before running)

- HydraDB indexing is asynchronous with no readiness API: poll retrievability, not row counts
  (`bench/hydra_wait.py` does both stages).
- HydraDB `delete_memory` requires `sub_tenant_id` for namespaced rows — without it the API
  returns HTTP 200 `{"success": false}` and deletes nothing (fixed in `hydrabrain/client.py`).
- After a bulk delete, one namespace never re-indexed new content (stored but unsearchable;
  same content indexed fine in a fresh namespace). The harness therefore never reuses a dirty
  namespace — it walks to a fresh suffixed one.
- Gemini's free tier caps embeddings at 1,000 REQUESTS/day: the harness batches ~50 texts per
  request and checkpoints every question (`--fresh` to rescore), so a quota wall costs a
  resume, not a rerun.

---

## 9. Limitations — what this does NOT prove

- **The relational corpus is small and synthetic** — 50 entities, 149 queries. A relational probe,
  not an at-scale benchmark. gbrain's own published R@5 is 97.9% on a 240-doc corpus.
- **gbrain wins single-hop under its perfect-graph control** (100 vs 92). HydraDB's win is
  *overall + multi-hop + extraction*, not every cell.
- **HydraDB is hosted** → results are **not bit-deterministic** (drift a few points per run; quote
  ranges) and it carries uptime + per-call cost risk vs gbrain's local-first PGLite. gbrain's side
  is deterministic.
- **The at-scale result (§7) is vs BM25, not gbrain.** Evidence recall was tied. Running gbrain at
  this scale is not yet done.
- **HydraDB loses oracle-split QA (§8) to a graph-less baseline** (45.6% vs 56.7%, n=90). A real
  finding about answer synthesis on single-needle questions — stated plainly, not explained away.
  It is not a gbrain-vs-HydraDB result (the baseline lacks gbrain's graph and reranker).
- **The LLM-judge metric is noisy** (single flips move a per-type cell ~7 pp at n=15).

---

## 10. Reproduce

```bash
pip install requests python-dotenv google-genai anthropic rank-bm25 huggingface_hub
# .env: HYDRADB_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY
#       (GEMINI_API_KEY is also exported as GOOGLE_GENERATIVE_AI_API_KEY for gbrain)
# gbrain side of Benchmark #1 needs Bun (runs `bun src/cli.ts`).

# Benchmark #1 — fair relational head-to-head, gbrain handed a perfect graph (headline)
python3 -m bench.relational_v2 --seed-edges --report
# Benchmark #1 — realistic: both auto-extract from prose
python3 -m bench.relational_v2 --report

# Benchmark #2 — architecture (offline, deterministic)
python3 -m bench.architecture

# Benchmark #3 — LongMemEval-S at scale (vs BM25 baseline)
python3 -m bench.lme_scale --limit 42

# Benchmark #4 — LongMemEval oracle, 90 questions (auto-downloads the dataset,
# checkpoints every question, resumes across quota walls; --fresh to rescore)
python3 -m bench.longmemeval --report
```

---

## 11. Artifacts (raw outputs, committed)

- `bench/relational_v2_seeded_results.json` — perfect-graph control, raw per-query + summary
- `bench/relational_v2_results.json` — realistic auto-extract, raw per-query + summary
- `bench/lme_scale_results.json` — LongMemEval-S at-scale raw output
- `bench/longmemeval_results.json` — LongMemEval oracle raw output (every answer + judgment)
- code: `bench/relational_v2.py`, `bench/architecture.py`, `bench/lme_scale.py`,
  `bench/longmemeval.py`, `bench/gbrain_stack.py`, `bench/hydra_wait.py`
