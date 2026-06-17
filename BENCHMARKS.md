# Benchmark Report — hydrabrain (HydraDB) vs gbrain's retrieval stack

**Date:** 2026-06-17 · **Author:** Harnoor Singh · **Repo:** fork of [garrytan/gbrain](https://github.com/garrytan/gbrain)

This report records exactly what we benchmarked, how, on which data, and the verbatim
numbers our harness produced. It is written to be checkable: every result here is
regenerable with the commands in §10, and the raw outputs are in §11.

---

## 0. TL;DR

| Benchmark | Dataset | HydraDB | gbrain-stack | Verdict |
|---|---|:---:|:---:|---|
| **#1 recall@5** vs gbrain **full stack** (+reranker) | 19-doc local, 19 queries | **96.5%** | 92.1% | HydraDB **+4.4** |
| **#1 recall@5** vs gbrain **fusion core** (no reranker) | same | **96.5%** | 75.4% | HydraDB **+21.1** |
| **#1 MRR** vs full stack | same | 0.912 | **0.947** | gbrain (ordering) |
| **#1 answers correct** (LLM-judge) vs full stack | same | **12/19** | 8/19 | HydraDB |
| **#2 QA accuracy** (LongMemEval **oracle**, *partial* 18/500) | downloaded | 50.0% | **77.8%** | *not conclusive — see §7* |
| **#2** LongMemEval **full `_s`** (500×~48 sessions) | not downloaded | — | — | **NOT RUN** (see §7) |

**Honest one-liner:** on a small relational corpus, HydraDB's native graph edges a faithful
reproduction of gbrain's *full* retrieval algorithm on recall@5 and answer accuracy (and far
outperforms the no-reranker version), using one native `recall` call with no separate rerank
stage. The at-scale claim (Benchmark #2 full split) is **not yet proven**.

---

## 1. What we ran

Two benchmarks, both comparing **HydraDB** against **a reproduction of gbrain's retrieval
pipeline** (`bench/gbrain_stack.py`) — *not* a running gbrain instance (see §8).

- **Benchmark #1 — relational-reasoning retrieval.** A small, dense, entity/temporal-heavy
  corpus with gold-labelled queries that stress where pure vector search breaks (negation,
  multi-session, temporal adjacency, entity direction, aggregation). Metric: `recall@5`
  (gbrain's own P@5), plus MRR and an LLM-as-judge answer pass.
- **Benchmark #2 — LongMemEval** (ICLR 2025), the standard long-term-memory benchmark: each
  question carries its own multi-session chat haystack. Metric: QA accuracy (LLM-judge) +
  evidence recall@5.

---

## 2. Systems under test

**HydraDB** — graph-native context store, hit over the **live API** (`api.hydradb.com`):
- ingest: `POST /memories/add_memory` with `infer:true` (builds the graph, no extra LLM calls from us)
- recall: `POST /recall/recall_preferences`, `mode=thinking`, `alpha=1.0`, `graph_context=true`
- tenant `test1`; per-question isolation in #2 via `sub_tenant_id`

**gbrain-stack (reproduction)** — gbrain's documented pipeline, built locally:
- dense vectors (Gemini `gemini-embedding-001`, 3072-d) → exact cosine NN
- BM25 (`rank_bm25` / BM25Okapi)
- reciprocal-rank fusion (k=60)
- **reranker** (Gemini listwise LLM reranker over the top-10) — `--rerank`; run **both** with and without
- **no knowledge graph** (the variable under test)
- **omitted:** source-tier boost (a no-op on a single-tier corpus); gbrain's actual MiniLM cross-encoder (we used a Gemini reranker, assumed ≥ as strong)

**Shared answerer + judge:** Gemini 2.5 Flash generates a one-sentence answer from each
system's top-5 and grades it YES/NO against the gold answer (same model both sides).

---

## 3. Models & environment

| Component | Value |
|---|---|
| HydraDB API | `https://api.hydradb.com` (live) |
| Embedder (baseline) | `gemini-embedding-001` (3072-d) |
| Answer + judge + reranker LLM | `gemini-2.5-flash` |
| BM25 | `rank_bm25` BM25Okapi |
| Runtime | Python 3.14, macOS |
| Determinism | Benchmark #1 identical across 3 repeated runs |

---

## 4. Datasets — local / partial / full

| Dataset | Where from | Size | Used | Partial/Full |
|---|---|---|---|---|
| **Relationship timeline** (Benchmark #1) | local (`bench/dataset.py`) | 19 "pages", 19 gold queries | all 19 | **Full** (this is the entire corpus, not a sample) |
| **LongMemEval `oracle`** | downloaded from HF `xiaowu0162/longmemeval` | 500 questions, ~15 MB (evidence sessions only) | **18** (balanced 3×6 types) | **Partial sample** of a split that itself omits distractors |
| **LongMemEval `_s`** | HF `xiaowu0162/longmemeval-cleaned` | 500 questions × ~48 sessions, ~264 MB | — | **Full — NOT downloaded / NOT run** |

Benchmark #1's corpus is **local demo data** (an intercultural relationship timeline) — small
but deliberately hard for vector search. Benchmark #2 is **public academic data**; we ran only
the small oracle sample, and the heavy full split remains to be run.

---

## 5. Metrics (definitions)

- **recall@5** — fraction of a query's gold *keyword-groups* matched by ≥1 chunk in the top-5.
  Groups are OR'd; keywords within a group are AND'd. Deterministic, no LLM in this scoring.
- **MRR** — 1 / rank of the first chunk matching any gold group.
- **QA accuracy (LLM-judge)** — Gemini grades the generated answer YES/NO vs the gold answer.
  Abstention questions (`_abs`) are correct iff the model declines. *This metric is noisy* (±~2).
- **evidence recall@5** (Benchmark #2) — did the top-5 include a gold *answer session*?

---

## 6. Benchmark #1 — results

**Headline (recall@5, top-k = 5, 19 queries):**

| Metric | HydraDB | gbrain full stack (+rerank) | gbrain fusion core |
|---|:---:|:---:|:---:|
| recall@5 | **96.5%** | 92.1% | 75.4% |
| MRR | 0.912 | **0.947** | 0.675 |
| answers correct (judge) | **12/19** | 8/19 | 8/19 (11/19 in a prior run — judge noise) |
| per-query (vs full stack) | **2 win / 0 lose / 17 tie** | — | — |

**Reranker ablation (the key finding):** adding gbrain's reranker to the baseline lifted it
**75.4% → 92.1%** — the single biggest lever. A reranker reorders retrieved candidates; it
cannot surface a chunk retrieval never found. See README → *"What actually drives the accuracy."*

**Per-category recall@5 (HydraDB vs gbrain full stack + reranker):**

| Capability | HydraDB | gbrain (+rerank) |
|---|:---:|:---:|
| Negation | **92%** | 67% |
| Multi-Session Reasoning | **100%** | 83% |
| Information Extraction | 100% | 100% |
| Temporal Reasoning | 100% | 100% |
| Temporal Adjacency | 100% | 100% |
| Entity Direction | 100% | 100% |
| Semantic Understanding | 100% | 100% |
| Abstention | 100% | 100% |
| Geographic Filtering | 100% | 100% |
| Aggregation | 50% | 50% |

HydraDB ties or wins every category, loses none. The two remaining gaps (Negation,
Multi-Session) are exactly where a reranker can't help — the answer chunk isn't near the query,
so only a graph edge reaches it.

---

## 7. Benchmark #2 — LongMemEval

**What we ran:** a balanced **18-question sample** (3 each of the 6 ability types) from the
**oracle** split. Each question's haystack ingested into an isolated namespace (HydraDB
`sub_tenant_id = question_id`, verified non-leaking; fresh local index per question for the baseline).

**Results (oracle, n=18):**

| | HydraDB | gbrain-stack |
|---|:---:|:---:|
| QA accuracy | 50.0% | **77.8%** |
| evidence recall@5 | 77.8% | **100.0%** |

Per type (QA): single-session-assistant 100/100 · knowledge-update 67/100 · single-session-user
67/100 · multi-session 33/67 · temporal 33/67 · preference 0/33 (H/B).

**⚠️ This result is NOT conclusive, and we do not present it as a HydraDB result:**
1. **Oracle removes the retrieval challenge** — its haystacks contain only evidence sessions, no
   distractors. The baseline trivially gets 100% evidence recall and feeds perfect context to the
   same answerer, so HydraDB's actual edge (finding the needle among ~48 distractors) is never tested.
2. **Indexing wait too short** — HydraDB evidence recall was only 78%, i.e. it sometimes failed to
   return a session that was the *only* thing in its namespace, because `infer=true` graph-wiring
   hadn't finished. Use `--hydra-wait 90`.

**The decisive run — full `_s` split with distractors — has NOT been run** (264 MB, ~500×48
sessions, multi-hour, high API cost). That is the test that would actually prove or disprove
HydraDB's at-scale advantage. Command in §10.

---

## 8. Fairness controls & footguns we found

Engineered to be **hard for HydraDB to win**, so a win means something:
- Baseline got the **better embedder** (Gemini 3072-d) **and** a strong **LLM reranker**.
- HydraDB ran in its best documented config (`mode=thinking, alpha=1.0`).
- **Identical, de-duplicated corpus** for both sides.

Real footguns caught and fixed (all logged honestly in the README):
- `alpha=0.8` starved HydraDB's keyword signal → 54%. Fixed to `1.0`.
- A stale tenant had the corpus ingested **twice** (38 docs stealing top-5 slots) → wiped clean.
- HydraDB's `infer=true` indexing is **async** → must wait for it to settle before measuring.
- Our first baseline **lacked gbrain's reranker** → adding it moved the baseline 75.4% → 92.1%,
  shrinking HydraDB's lead from +21 to +4.4. We report both.

---

## 9. Limitations — what this does NOT prove

- **We did not run gbrain or pgvector.** The opponent is a reproduction of gbrain's *documented
  algorithm*, not its code/DB. This proves *"HydraDB's graph beats that algorithm,"* not *"we beat
  gbrain head-to-head."*
- **Benchmark #1 is 19 documents.** A small relational probe, not an at-scale benchmark.
- **HydraDB loses MRR** (0.912 vs 0.947) — slightly worse top-5 ordering.
- **The LLM-judge metric is noisy** (±~2 between runs).
- **The only at-scale test attempted (oracle) did not favor HydraDB** and is non-conclusive (§7).
- Reranker is a Gemini LLM, *assumed* ≥ gbrain's MiniLM; not verified against the real one.

---

## 10. Reproduce

```bash
pip install rank-bm25 mcp requests python-dotenv google-genai
# .env: HYDRADB_API_KEY, GEMINI_API_KEY

# Benchmark #1 — full stack (with gbrain's reranker), the honest headline
python3 -m bench.run_bench --ingest --rerank --judge --report      # → bench/report.html
# Benchmark #1 — fusion core (no reranker), the +21 picture
python3 -m bench.run_bench --judge                                  # omit --rerank
# Benchmark #1 — baseline only, offline
python3 -m bench.run_bench --no-hydra --rerank

# Benchmark #2 — oracle sanity sample (auto-downloads oracle)
python3 -m bench.longmemeval --limit 18 --report                    # → bench/longmemeval_report.html
# Benchmark #2 — DECISIVE full _s run (heavy)
hf download xiaowu0162/longmemeval-cleaned longmemeval_s_cleaned.json --repo-type dataset --local-dir bench/data
python3 -m bench.longmemeval --data bench/data/longmemeval_s_cleaned.json --limit 100 --hydra-wait 90 --report
```

---

## 11. Artifacts

- `bench/results.json` — Benchmark #1 raw per-query output (gitignored; regenerate via §10)
- `bench/report.html` — Benchmark #1 visual report
- `bench/longmemeval_results.json` — Benchmark #2 raw output (gitignored)
- `bench/longmemeval_report.html` — Benchmark #2 visual report
- `bench/assets/recall.svg` — recall@5 chart
- code: `bench/run_bench.py`, `bench/gbrain_stack.py`, `bench/longmemeval.py`, `bench/dataset.py`
