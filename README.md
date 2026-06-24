> **🍴 This repository is a fork of [gbrain](https://github.com/garrytan/gbrain)** (MIT, by Garry Tan).
> gbrain's original TypeScript source is preserved here unchanged - see [`README.upstream.md`](README.upstream.md), `src/`, `skills/`, etc.
> The **`hydrabrain/`** and **`bench/`** directories add an *independent Python reimplementation on [HydraDB](https://hydradb.com)* plus head-to-head benchmarks. They share no code with gbrain's TS source - this fork exists to carry the lineage and run the comparison side-by-side. The document below describes that reimplementation.

**Context memory:** this project runs entirely on [HydraDB](https://hydradb.com) - see [CONTEXT-MEMORY.md](CONTEXT-MEMORY.md).

---

<div align="center">

# 🧠 hydrabrain

### A [gbrain](https://github.com/garrytan/gbrain) clone, rebuilt on [**HydraDB**](https://hydradb.com) - and benchmarked head-to-head against the **real gbrain binary** (graph ON).

[![relational R@5](https://img.shields.io/badge/relational%20R%405-~88%25_vs_~77%25-2dd4bf?style=flat-square)](#-the-benchmark-the-fair-relational-head-to-head)
[![multi-hop R@5](https://img.shields.io/badge/multi--hop%20R%405-~86%25_vs_~64%25-2dd4bf?style=flat-square)](#-the-benchmark-the-fair-relational-head-to-head)
[![retrieval code](https://img.shields.io/badge/retrieval%20code-29%C3%97%20less-16a34a?style=flat-square)](#architecture--what-a-maintainer-owns)
[![fork of gbrain](https://img.shields.io/badge/fork%20of-garrytan%2Fgbrain-555?style=flat-square&logo=github)](https://github.com/garrytan/gbrain)
[![license MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

**Fair head-to-head vs the real `gbrain` (PGLite, Gemini embeddings, typed-edge graph ON, relational arm engaged) - same 50-entity prose corpus, 149 queries, both build their own graph:**

| What | gbrain (graph ON) | **HydraDB** |
|---|:---:|:---:|
| Relational **R@5**, gbrain handed a **100%-correct graph** | 77.4% | **88.4%** |
| **Multi-hop** (2-hop) R@5 | 63.8% | **86.0%** |
| Relational R@5, both **auto-extract from prose** | 50.0% | **88.0%** |
| Retrieval pipeline | 6 stages · 9,345 LOC | **1 `recall()` · 327 LOC** |

**HydraDB wins relational retrieval overall and dominates multi-hop - even when gbrain is handed a perfect graph - in one `recall()` call vs a 6-stage pipeline.** Its real edge: robust auto-extraction from raw prose (gbrain's own NER recovered only 44% of edges) plus multi-hop traversal.

<sub>Honest, on the record: **gbrain wins simple 1-hop lookups** (100% vs 92%) when handed a perfect graph. Corpus is small + synthetic (50 entities, 149 queries) - not gbrain's 240-doc scale. HydraDB is a **hosted** service: numbers drift a few points between runs (non-deterministic) and it carries uptime/cost risk vs gbrain's local-first store. Full scorecard + the fairness bugs we fixed below; rerun it in one command.</sub>

</div>

---

## 🎯 The goal (north star - keep us aligned)

> **A personal second brain over everything I consume.**
> Dump in *all* the content I take in - Instagram saves, YouTube videos, articles,
> podcasts, notes - then **chat with it and get answers as accurate as possible**, out of
> the box.
>
> **Accuracy first, then scale the ingestion.** That's why this repo leads with rigorous,
> reproducible benchmarks instead of a flashy demo: if the memory can't answer accurately
> on a small, hard corpus, no amount of ingestion volume will save the chat experience.

---

## 📍 The migration - gbrain → HydraDB (the headline goal + living tracker)

> **🎯 What we're building & showing off:** a **capability migration** - gbrain, the
> "next Postgres for memory," **reimplemented feature-for-feature on HydraDB's graph-native
> store.** gbrain assembles its memory from pgvector + BM25 + RRF + a reranker + a hand-rolled
> graph extractor; we collapse that whole stack into HydraDB's native `capture`/`recall`.
> Same capabilities, a fraction of the moving parts - *that's* the story (and the benchmarks
> below are the receipts). This is the narrative for the blog posts / articles / threads.
>
> **Scope (important for honesty):** this is **(A) capability reimplementation** - rebuilding
> gbrain's *features* on HydraDB as a fresh Python package (`hydrabrain/`). It is **not**
> **(B) data-migration ETL**: there's no tool that reads an existing gbrain pgvector/graph
> brain and bulk-loads it into HydraDB, and that's out of scope. gbrain's TS `src/` stays
> unchanged (it legitimately uses pgvector/PGLite); the benchmark *reproduces* gbrain's
> algorithm, it never reads a real gbrain database.
>
> **Legend:** ✅ done · 🟡 partial · ◐ delegated to HydraDB / OS · ⬜ not started. *Last updated: 2026-06-19.*

**Stage: core memory loop + the everyday product surface (sync, connectors, source scoping, enrich, briefing, export, chat) all migrated. What's left is mostly gbrain's heavy ops (mounts, schema/lens packs, identity, cron, advisor).**

| Area | Status | Notes |
|---|:---:|---|
| Ingest / capture | ✅ | `capture` / `ingest_file` → `add_memory(infer=True)` |
| Hybrid retrieval (vector+BM25+RRF+rerank) | ✅ | one native HydraDB `recall` call |
| Self-wiring knowledge graph | ✅ | native `infer=True`, no extractor code |
| Synthesis (cited answers) | ✅ | `think` - Gemini grounding over HydraDB chunks |
| Graph traversal / explore | 🟡 | `graph_relations` by `source_id` only |
| Status / list / delete / wipe | ✅ | tenant + memory count, live deletes |
| CLI (`hydrabrain`) | ✅ | 14 commands incl. sync/read/enrich/briefing/export/chat |
| MCP server | ✅ | 8 tools: capture/read_url/search/think/briefing/enrich/graph/status |
| **Fair relational head-to-head (vs real gbrain, graph ON)** | ✅ | **DONE - HydraDB wins overall + multi-hop even with gbrain handed a perfect graph:** R@5 88.4% vs 77.4%, 2-hop 86.0% vs 63.8%, MRR 0.894 vs 0.826; when both auto-extract from prose, 88.0% vs 50.0%. gbrain wins 1-hop (100% vs 92%). Reproduce: `python3 -m bench.relational_v2 --seed-edges --report`. |
| Architecture (retrieval surface) | ✅ | **29× less code** - 327 LOC (one `recall()`) vs 9,345 across 32 files (6 stages). Deterministic, offline: `python3 -m bench.architecture`. |
| LongMemEval-S at scale (vs **BM25** baseline) | ✅ | 42 qs × ~48 distractor sessions: QA accuracy 38.1% vs 16.7% (evidence recall tied 97.6%). **Opponent is BM25, not full gbrain.** `python3 -m bench.lme_scale --limit 42`. |
| Bulk sync / import | ✅ | `hydrabrain sync` - incremental, content-hash dedup, manifest-backed |
| Ingestion connectors (articles / tweets / YouTube) | 🟡 | article reader + **tweets (free oEmbed)** + YouTube transcript (`hydrabrain read <url>`); LinkedIn best-effort; IG/podcasts next |
| Source scoping (brains/sources two-axis) | 🟡 | `--source` → HydraDB sub_tenant namespace; full 6-tier resolution + mounts not yet |
| Export | ✅ | `hydrabrain export <dir>` - dumps (tenant, source) to Markdown + manifest |
| Enrichment (summary / tags / entities) | 🟡 | `enrich` done; schema/lens packs not |
| Reports / briefing | ✅ | `hydrabrain briefing [topic]` - synthesized digest over memory |
| Chat over `think()` (REPL + **web UI**) | ✅ | `hydrabrain chat` REPL **and** `hydrabrain web` - zero-dep creator UI (add link/note, cited chat) |
| **Onboarding / first-run key setup** | ✅ | `hydrabrain init` + web setup screen, **Free mode vs. keys** choice, writes `~/.hydrabrain/.env` (chmod 600), validates HydraDB live, first-run guard |
| Cron / scheduling | 🟡 | `hydrabrain cron add/list/remove` + OS crontab; no pre-wired jobs - see [Company cron playbook](demos/cron-playbook.html) |
| Identity / access control / trust boundary | ◐ | largely **delegated to HydraDB** (API key + tenant/sub_tenant isolation); no per-op trust flags yet |
| Advisor / skillpacks | ⬜ | gbrain-specific; low north-star value - deferred |
| Data-migration ETL (real gbrain brain → HydraDB) | - | **out of scope** - this is a capability migration, not a data move |

**Recently shipped:** ✅ **zero-friction onboarding** (`init` + web setup, Free-mode vs keys) · ✅ **free
tweet connector** (no-auth oEmbed) · ✅ bulk `sync` · ✅ web/YouTube connectors · ✅ source scoping ·
✅ enrichment · ✅ briefing · ✅ export · ✅ chat REPL · ✅ **web UI** · ✅ MCP → 8 tools.
**Next up (in priority order):** (1) run `lme_scale` against **real gbrain** (not just the BM25 baseline) ·
(2) grow the relational corpus toward gbrain's 240-doc scale · (3) Instagram/podcast connectors ·
(4) full brains/sources resolution + mounts. See [Next steps](#next-steps-toward-the-north-star).

---

## 📊 The benchmark: the fair relational head-to-head

This compares **HydraDB** against the **real gbrain** that ships in this fork's `src/` - PGLite
engine, Gemini embeddings, typed-edge graph **on**, relational arm engaged - driven via
`bun src/cli.ts`. Same 50-entity prose corpus, same 149 queries (1- and 2-hop), same gold labels.
Each system builds its graph its own way: HydraDB `infer=True`, gbrain `extract links --ner`.

### First, the fairness bugs we found in our *own* harness

An earlier version of this benchmark showed a HydraDB blowout. It was wrong - the harness was
unfair to gbrain. We fixed three bugs before trusting any number, and the harness now guards each:

1. **gbrain's graph wasn't being built.** Its default schema pack ships no edge-inference regexes,
   so prose produced **zero** typed edges. Fixed: activate the pack that has them; an integrity gate
   now **aborts** if the edge count is zero.
2. **Edges were mis-typed.** On dense prose, gbrain's NER labelled `works_at` as `founded`. Fixed:
   the gate checks edge-type **correctness**, not just count.
3. **gbrain's relational arm sat dormant.** The default query path is vector-dominant; the graph
   walk only engages with `relational:true`. Without it we were under-measuring gbrain. Fixed: on.

We then went further and **handed gbrain a 100%-correct graph** (verified) via its own published
seeding method - so a HydraDB win can't be dismissed as "you broke gbrain's extraction."

### The scorecard

| Metric | gbrain (graph ON) | **HydraDB** | Edge |
|---|:---:|:---:|---|
| **R@5** - gbrain handed a **perfect graph** | 77.4% | **88.4%** | HydraDB **+11** |
| **R@5** - both **auto-extract from prose** | 50.0% | **88.0%** | HydraDB **+38** |
| **1-hop** R@5 (perfect graph) | **100.0%** | 92.3% | **gbrain +8** |
| **2-hop / multi-hop** R@5 (perfect graph) | 63.8% | **86.0%** | HydraDB **+22** |
| **MRR** (perfect graph) | 0.826 | **0.894** | HydraDB |

> 📊 **Full methodology + raw outputs:** [`BENCHMARKS.md`](BENCHMARKS.md) · harness: [`bench/relational_v2.py`](bench/relational_v2.py)

Two honest readings:
- **Even with a perfect graph and its arm on, HydraDB wins relational retrieval overall and dominates
  multi-hop** (2-hop 86% vs 64%) - in one `recall()` call, no assembled pipeline.
- **HydraDB's biggest edge is robust auto-extraction from raw prose.** When both systems extract for
  themselves, HydraDB holds 88% while gbrain drops to 50% - because gbrain's regex NER recovered only
  **44%** of the relationships. Feed both the same documents, HydraDB builds the more useful graph.

### Architecture - what a maintainer owns

Deterministic, offline (`python3 -m bench.architecture`): HydraDB's retrieval surface is **~29× less
code** - **327 LOC** (one `recall()`) vs **9,345 LOC across 32 files** for gbrain's 6-stage pipeline
(dense + BM25 + RRF + reranker + query-expansion + graph). **1 external service vs 4.**

### What this does NOT prove (read before you cite a number)

- **gbrain wins simple 1-hop lookups** (100% vs 92%) when handed a perfect graph. HydraDB's win is
  *overall + multi-hop + extraction*, not every metric.
- **The corpus is small and synthetic** - 50 entities, 149 queries. A relational probe, not an
  at-scale benchmark. gbrain's own published R@5 is 97.9% on a 240-doc corpus.
- **HydraDB is hosted** → results are **not bit-deterministic** (drift a few points per run; quote
  ranges), and it carries uptime + per-call cost risk vs gbrain's local-first PGLite. gbrain's side
  *is* deterministic.
- **The separate LongMemEval-S at-scale result** (QA 38.1% vs 16.7%) is **vs a BM25 baseline, not
  full gbrain** - evidence recall was tied (97.6%). See `bench/lme_scale.py`. Running it against real
  gbrain is next.

**Honest bottom line:** fed the same documents, HydraDB's graph-native retrieval beats real gbrain
overall and on multi-hop - even when gbrain is handed a perfect graph - with a fraction of the moving
parts. gbrain still wins simple lookups, and the at-scale-vs-gbrain claim is not yet earned. Every
number here regenerates from one command.

## The architectural difference (assemble vs. native)

This is the *why* behind the numbers. gbrain is excellent - but look at what it has to *assemble* to get its memory:

```
gbrain:   pgvector(HNSW)  +  BM25  +  reciprocal-rank fusion  +  reranker  +  ⟨hand-rolled graph extractor⟩
hydrabrain (HydraDB):   brain.capture(text)         # infer=True → graph built, zero extra LLM calls
                        brain.think("...")          # hybrid dense+graph+BM25, cited answer
```

The knowledge graph is the part gbrain credits for **+31.4 P@5**. It's also the part that's
hardest to build, tune, and keep wired. HydraDB makes it a property of `ingest`, not a
pipeline you own. Everything gbrain exposes, hydrabrain exposes - on top of that native graph.

```python
from hydrabrain.engine import BrainEngine
brain = BrainEngine()
brain.capture("On May 7, 2022 we bought a white Tesla Model 3 together.")
print(brain.think("What car did we buy?").render())
#  A white Tesla Model 3, bought on May 7, 2022 [1].
#  Sources: [1] May 7, 2022 - Buying a Car Together, Tesla Model 3: ...
```

---

## ⚡ Install in one line

```bash
curl -fsSL https://raw.githubusercontent.com/iharnoor/hydrabrain/master/scripts/install.sh | bash
```

Clones (if needed) → builds a `.venv` (works on Homebrew/managed Python - no PEP 668 error) →
installs deps → guided key setup (**Free mode = just a HydraDB key**) → verifies → registers the
MCP server with Claude if present. Article, tweet, and **YouTube** ingestion all work out of
the box. Agents: invoke the **`setup-hydrabrain`** skill.

**Other ways to install:**

```bash
# From a clone, via make:
make install        # venv + deps + guided key setup     make web   # launch the UI
make dev            # editable install + test tools       make doctor

# Global `hydrabrain` command, isolated (pipx manages its own venv - PEP-668-safe):
pipx install git+https://github.com/iharnoor/hydrabrain.git
hydrabrain init && hydrabrain web --open
```

---

## 🖥️ Web UI - ready out of the box

Built for **creators**: paste a blog post, article, or YouTube URL and it's in your brain;
then chat with everything you've made and consumed - answers come back **with citations**.

```bash
hydrabrain web --open        # → http://127.0.0.1:8765, opens your browser
```

**First run is guided.** No keys yet? `hydrabrain web` serves a **setup screen** - pick
**🆓 Free mode** (just a free HydraDB key: capture, add links, search) or **🔑 I have my keys**
(add a free Gemini key too for synthesized, cited answers). Keys save to `~/.hydrabrain/.env`
(chmod 600). Prefer the terminal? `hydrabrain init` does the same in ~30 seconds.

**Zero new dependencies** - served by the Python stdlib (no Flask/FastAPI/uvicorn to install),
so it runs the instant you install hydrabrain. One self-contained page (no CDNs, works offline
except for the API calls it makes to your own brain).

- **🔗 Add a link** - articles + YouTube transcripts are fetched, cleaned, and graph-wired automatically.
- **✏️ Add a note** - drop a thought, quote, or takeaway.
- **💬 Ask** - cited answers with inline `[n]`, expandable sources, and explicit gap analysis.
- Live status pill (memory count · brain · source). Scopes to any source with `hydrabrain --source <s> web`.

Endpoints (all JSON, for embedding elsewhere): `GET /api/status` · `POST /api/read` ·
`POST /api/capture` · `POST /api/think` · `POST /api/search`.

---

## 🏢 Company brain - cron + push playbook

Scheduled jobs **push** institutional knowledge into HydraDB (`sync`, `capture`, `read`).
Agents and employees **pull** cited answers the next day (`think`, `search`, `graph` via MCP).
Every ingest runs with `infer=True`, so people, companies, and deals link in the graph without a
separate extraction pipeline.

**Interactive guide:** [`demos/cron-playbook.html`](demos/cron-playbook.html) - filter by team
(Sales · CS · Engineering · Legal · Leadership · Ops), copy-paste cron packs, and HydraDB vs
gbrain TS comparison. Open locally:

```bash
open demos/cron-playbook.html
```

**Honest default:** fresh install ships **zero** crontab entries. A 25-person company can be
live in ~30 minutes with three pushes + MCP:

```bash
hydrabrain cron add "*/15 * * * *" "hydrabrain sync ~/company-docs --source wiki"
hydrabrain cron add "0 7 * * 1-5"   "hydrabrain briefing >> ~/briefings/daily.md"
hydrabrain cron add "0 0 * * 0"     "hydrabrain export ~/backups/weekly"
claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve
```

| Cron (push) | Who pulls | Company outcome |
|---|---|---|
| `sync` every 15-30 min | Agents via MCP `search` | Wiki / CRM / meeting exports stay current |
| `capture` at decision time | Next `think` / morning `briefing` | Meeting outcomes don't die in chat |
| `briefing` daily 7 AM | Leadership reads digest | Exec team aligned without a 90-min standup |
| `export` weekly | Legal / compliance | Auditable snapshot; portable exit path |

Upstream gbrain's reference schedule (email, meetings, dream cycle) lives in
[`docs/guides/cron-schedule.md`](docs/guides/cron-schedule.md) and
[`recipes/`](recipes/) - DIY collectors, not pre-installed. Opt-in daemon:
`gbrain autopilot --install` (one maintenance loop, not 50+ jobs).

**Video explainer (HyperFrames):** [`demos/hydrabrain-video/`](demos/hydrabrain-video/) - 78-second
problem → solution journey (scattered knowledge → cron push → HydraDB graph → agent pull).
Preview with `cd demos/hydrabrain-video && npm run dev`, render with `npm run render`, or open
[`output/hydrabrain-enterprise.mp4`](demos/hydrabrain-video/output/hydrabrain-enterprise.mp4) after rendering.

---

## 🔬 Deeper dive + the at-scale test

The full scorecard, the three fairness bugs we fixed, and the architecture numbers are in
[the benchmark section above](#-the-benchmark-the-fair-relational-head-to-head). Full methodology
+ raw per-query outputs live in [`BENCHMARKS.md`](BENCHMARKS.md) and the `bench/` directory.

### LongMemEval-S - the academic at-scale test (vs a BM25 baseline)

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (ICLR 2025) is the standard long-term
chat-memory benchmark: each question ships its own multi-session haystack. We ran the **`_s` split
with distractors** - 42 questions × ~48 sessions each, Claude Haiku as answerer + judge:

| Metric | BM25 baseline | **HydraDB** |
|---|:---:|:---:|
| evidence recall@5 | 97.6% | 97.6% (tied) |
| QA accuracy (LLM-judge) | 16.7% | **38.1%** (2.3×) |

**Honest scope:** the opponent here is a **BM25 lexical baseline, NOT full gbrain** (it's the keyword
arm of gbrain's pipeline). Evidence recall is tied - HydraDB's QA gain comes from feeding cleaner
chunks + graph context to the same answerer, partly a chunk-vs-whole-session granularity effect.
Running this against the real gbrain binary is the next step.

```bash
python3 -m bench.lme_scale --data bench/data/longmemeval_s_cleaned.json --limit 42 --hydra-wait 120
```

---

## Capabilities (mirrors gbrain's `#capabilities`)

| gbrain capability | hydrabrain (HydraDB) |
|---|---|
| Hybrid search (vector + BM25 + RRF + rerank) | `brain.search()` → HydraDB hybrid recall (`mode=thinking`) |
| Self-wiring knowledge graph (typed edges) | **native** via `infer=True` - no extraction code |
| Synthesis layer (cited prose + gap analysis) | `brain.think()` (Gemini grounding over retrieved chunks) |
| 30+ tool MCP server (stdio) | `hydrabrain serve` (FastMCP: capture/read_url/search/think/briefing/enrich/graph/status) |
| Eval framework (LongMemEval-style P@5) | `bench/` - two benchmarks, recall@5 / MRR / LLM-judge / QA acc |
| Bulk sync (incremental dir ingest) | `brain.sync(paths)` / `hydrabrain sync <dir>` - content-hash dedup, idempotent |
| Onboarding (`gbrain init`) | `hydrabrain init` / web setup screen - Free-mode vs keys, writes `~/.hydrabrain/.env` |
| Ingestion connectors (consume the web) | `brain.ingest_url(url)` / `hydrabrain read <url>` - articles + tweets (free oEmbed) + YouTube transcripts |
| Brains / sources two-axis routing | `--tenant` (brain) + `--source` (HydraDB sub_tenant namespace) |
| Enrichment (summary / tags / entities) | `brain.enrich()` / `hydrabrain enrich` (Gemini) |
| Reports / briefing | `brain.briefing(topic)` / `hydrabrain briefing` |
| Export / portability | `brain.export(dir)` / `hydrabrain export <dir>` → Markdown + manifest |
| Chat | `hydrabrain chat` (REPL) **and** `hydrabrain web` (zero-dep web UI for creators) |
| Cron / scheduling | `hydrabrain cron add/list/remove` - OS crontab wrapper; [playbook](demos/cron-playbook.html) |
| CLI | `hydrabrain` - init/status/capture/ingest/sync/read/search/think/chat/web/briefing/enrich/graph/export/cron/jobs/serve/bench |

### CLI

```bash
python3 -m hydrabrain.cli init                     # one-time setup (Free mode or paste keys)
python3 -m hydrabrain.cli status
python3 -m hydrabrain.cli capture "Saved a YouTube video on espresso ratios: 1:2 in 28s."
python3 -m hydrabrain.cli ingest notes/*.md
python3 -m hydrabrain.cli sync ~/notes            # bulk, incremental - skips unchanged files
python3 -m hydrabrain.cli sync ~/notes --dry-run  # preview what would ingest
python3 -m hydrabrain.cli read https://example.com/post   # ingest an article
python3 -m hydrabrain.cli read https://youtu.be/VIDEO_ID   # ingest a video transcript
python3 -m hydrabrain.cli read https://x.com/user/status/123  # ingest a tweet (free, no auth)
python3 -m hydrabrain.cli search "espresso ratio" -k 5
python3 -m hydrabrain.cli think  "what coffee setup did I save?"
python3 -m hydrabrain.cli web --open                # web UI for creators (add link/note + cited chat)
python3 -m hydrabrain.cli chat                      # interactive REPL over your brain
python3 -m hydrabrain.cli briefing "coffee"         # synthesized digest on a topic
python3 -m hydrabrain.cli enrich "..."              # summary + tags + entities
python3 -m hydrabrain.cli export ./brain-backup     # dump brain to Markdown + manifest
python3 -m hydrabrain.cli --source blog sync ~/posts  # scope to a source namespace
python3 -m hydrabrain.cli cron add "0 7 * * 1-5" "hydrabrain briefing >> ~/briefings/daily.md"
python3 -m hydrabrain.cli cron list
python3 -m hydrabrain.cli serve         # MCP stdio server
```

### MCP (Claude Code / Cursor / Claude Desktop)

```bash
claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve
```

---

## Reproduce

```bash
pip install rank-bm25 requests python-dotenv google-genai anthropic
# .env needs HYDRADB_API_KEY (write access) and GEMINI_API_KEY

# The fair relational head-to-head (real gbrain, graph ON) - the headline
python3 -m bench.relational_v2 --seed-edges --report   # gbrain handed a perfect graph
python3 -m bench.relational_v2 --report                # gbrain self-extracts from prose

# Architecture cost - deterministic, no keys, offline
python3 -m bench.architecture

# LongMemEval-S at scale (vs a BM25 baseline)
python3 -m bench.lme_scale --limit 42 --hydra-wait 120
```

### Integrity ledger - how we keep it fair

- gbrain runs **graph ON** with its relational arm engaged (`relational:true`); an integrity gate
  **aborts** if its typed edges are missing or mis-typed, so it is never scored on a broken graph.
- We also hand gbrain a **100%-correct graph** (its own published seeding method) as a
  rebuttal-proof control - and HydraDB still wins overall + multi-hop.
- **Same prose into both systems**; each builds its graph its own way.
- HydraDB is **hosted → non-deterministic**: quote ranges, not exact decimals. gbrain's side is deterministic.
- The earlier "wins both corpora" claim was **retired** - it had run gbrain with its graph
  effectively off. Catching that in our own harness is why these numbers are trustworthy.

## Layout

```
hydrabrain/        the gbrain-style memory engine on HydraDB
  client.py        HydraDB REST client (ingest / hybrid recall / graph / delete)
  engine.py        BrainEngine: capture / ingest_file / sync / ingest_url / search / think /
                     enrich / briefing / export / graph  (+ brain & source axes)
  sync.py          bulk incremental ingest (dir/glob, content-hash dedup, manifest)
  connectors.py    web connectors: articles (stdlib HTML→text) + tweets (oEmbed) + YouTube
  onboarding.py    first-run key setup (validate + write ~/.hydrabrain/.env)
  enrich.py        derive summary + tags + entities (Gemini)
  reports.py       briefing / report synthesis over memory
  export.py        dump a brain (tenant+source) to Markdown files + manifest.json
  webapp.py        zero-dep web UI server (stdlib http.server) + JSON API
  web/index.html   the single-page creator app (add link/note, cited chat)
  web/setup.html   first-run setup screen (Free-mode vs keys)
  synth.py         synthesis layer - cited answer + gap analysis (Gemini)
  cli.py           the hydrabrain CLI (15 cmds)   mcp_server.py   MCP stdio server (8 tools)
  config.py        env + recall tuning + brain/source defaults (mode=thinking, alpha=1.0)
bench/
  dataset.py       19 pages + 19 gold test cases (dependency-free)
  gbrain_stack.py  faithful gbrain pipeline: dense + BM25 + RRF, NO graph
  run_bench.py     Benchmark #1 - recall@5 / MRR / LLM-judge   → report.html
  longmemeval.py   Benchmark #2 - LongMemEval QA + evidence    → longmemeval_report.html
  data/            LongMemEval splits (oracle auto-downloaded; _s on demand)
demos/
  cron-playbook.html        interactive enterprise guide - cron push → HydraDB → agent pull
  hydrabrain-video/         HyperFrames explainer video (problem → solution, ~78s MP4)
```

## Next steps (toward the north star)

1. **LongMemEval-S vs real gbrain** - the `_s` split is run vs a BM25 baseline (38.1% vs 16.7%);
   next is running it against the real gbrain binary, and growing the relational corpus to 240-doc scale.
2. **Ingestion connectors** - Instagram saves, YouTube transcripts, article readers →
   `brain.capture()` / `brain.ingest_file()`.
3. **Chat UI** over `brain.think()` with streaming + citations.
4. **Scale test** - 10K+ pages, re-measure recall to confirm the graph holds.

## License & credits

MIT - matching [gbrain](https://github.com/garrytan/gbrain), which is also MIT. As a fork, gbrain's original `LICENSE` (© Garry Tan) is preserved at repo root; the `hydrabrain/` and `bench/` additions are likewise MIT © Harnoor Singh. hydrabrain
is an independent reimplementation: the engine, client, synthesis layer, and benchmarks are
original code written against [HydraDB](https://hydradb.com); only the *capability surface*
and CLI command names are modeled on gbrain. Huge respect to **Garry Tan** for gbrain - it's
the system this one set out to match, and beat, on the merits.

<div align="center"><sub>Built to prove a point, honestly. HydraDB gives you gbrain's graph advantage natively - and the numbers hold up.</sub></div>
