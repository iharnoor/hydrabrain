"""Real head-to-head — *actual* gbrain vs HydraDB on one shared corpus.

This is Benchmark v2: the honest fight. Unlike run_bench.py (which compares HydraDB
to a *reproduction* of gbrain's pipeline with the graph removed), this drives the
**real gbrain** that ships in this fork's `src/` — PGLite engine, Gemini embeddings
(`google:gemini-embedding-001`, the same embedder used elsewhere), graph ON — and
compares it to HydraDB on the identical 19-doc corpus, identical gold keyword-groups,
and identical recall@5 / MRR scoring.

So a number here is attributable to "HydraDB vs gbrain," not "graph vs no-graph."

Usage:
  python3 -m bench.headtohead                 # set up a fresh gbrain brain + run
  python3 -m bench.headtohead --gbrain-home /path/to/brain   # reuse a prepared brain
  python3 -m bench.headtohead --no-hydra      # gbrain only (offline-ish)

Requires GEMINI_API_KEY (used as GOOGLE_GENERATIVE_AI_API_KEY for gbrain embeddings)
and HYDRADB_API_KEY. gbrain runs via `bun src/cli.ts`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from bench.dataset import PAGES, TEST_CASES
from bench.run_bench import TOP_K, mrr, recall_at_k
from hydrabrain import config

REPO = Path(__file__).resolve().parent.parent


# ── gbrain driver (drives the real CLI in src/) ─────────────────────
def _gbrain_env(home: Path) -> dict:
    env = dict(os.environ)
    env["GBRAIN_HOME"] = str(home)
    key = config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    env["GOOGLE_GENERATIVE_AI_API_KEY"] = key
    env["GBRAIN_SKIP_STARTUP_HOOKS"] = "1"
    env["GBRAIN_NO_SANITY"] = "1"
    return env


def _gb(args: list[str], env: dict, inp: str | None = None, timeout: int = 180):
    return subprocess.run(
        ["bun", "src/cli.ts", *args], cwd=str(REPO), env=env,
        input=inp, capture_output=True, text=True, timeout=timeout,
    )


def setup_gbrain(home: Path) -> dict:
    env = _gbrain_env(home)
    marker = home / ".h2h-ready"
    if marker.exists():
        print(f"  [gbrain] reusing prepared brain at {home}")
        return env
    print(f"  [gbrain] init PGLite + Gemini embeddings at {home}")
    r = _gb(["init", "--pglite", "--embedding-model", "google:gemini-embedding-001"], env, timeout=400)
    if "Embedding:" not in (r.stdout + r.stderr) and r.returncode not in (0, None):
        print("  [gbrain] init stderr:", r.stderr[-300:])
    print(f"  [gbrain] importing {len(PAGES)} pages…")
    for i, page in enumerate(PAGES, 1):
        _gb(["put", f"page-{i:02d}"], env, inp=page, timeout=120)
    print("  [gbrain] embedding all pages…")
    _gb(["embed", "--all"], env, timeout=400)
    # report whatever graph the import produced (gbrain self-wiring / links)
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok")
    return env


def gbrain_search(env: dict, query: str, k: int) -> tuple[list[str], float]:
    t = time.time()
    r = _gb(["call", "query", json.dumps({"query": query, "limit": k})], env, timeout=120)
    dt = time.time() - t
    try:
        rows = json.loads(r.stdout)
    except Exception:
        return [], dt
    texts = [(row.get("chunk_text") or row.get("title") or "") for row in rows if isinstance(row, dict)]
    return texts, dt


# ── HydraDB driver ──────────────────────────────────────────────────
def setup_hydra(retries: int = 4):
    """Ingest the corpus into HydraDB with retries (the API can 500 transiently)."""
    from hydrabrain.engine import BrainEngine
    eng = BrainEngine()
    n = eng.client.count()
    if n > 0:
        print(f"  [HydraDB] reusing {n} existing memories")
        return eng
    print(f"  [HydraDB] ingesting {len(PAGES)} pages (infer=True → builds graph)…")
    for i, page in enumerate(PAGES, 1):
        for attempt in range(retries):
            try:
                eng.client.add_memory(page, infer=True)
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise RuntimeError(
                        f"HydraDB ingest failed on page {i} after {retries} tries: {e}. "
                        "If the API is 500ing, retry the whole run once it recovers."
                    )
                time.sleep(2 * (attempt + 1))
        time.sleep(0.5)
    print("  [HydraDB] waiting 60s for indexing + graph wiring…")
    time.sleep(60)
    return eng


def hydra_search(eng, query: str, k: int) -> tuple[list[str], float]:
    t = time.time()
    chunks = eng.search(query, k=k)
    dt = time.time() - t
    return [c.text for c in chunks], dt


# ── main ────────────────────────────────────────────────────────────
def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbrain-home", default="", help="reuse a prepared gbrain brain dir")
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--no-gbrain", action="store_true")
    ap.add_argument("-k", type=int, default=TOP_K)
    args = ap.parse_args(argv or [])

    print("=" * 72)
    print("  Benchmark v2 — REAL gbrain (PGLite, Gemini embed, graph) vs HydraDB")
    print(f"  corpus: {len(PAGES)} pages · {len(TEST_CASES)} gold queries · recall@{args.k} / MRR")
    print("=" * 72)

    genv = None
    if not args.no_gbrain:
        # Default to a stable, reusable brain dir so re-runs skip the costly setup
        # (and survive temp cleanup). Override with --gbrain-home.
        home = Path(args.gbrain_home) if args.gbrain_home else (REPO / "bench" / ".gbrain-h2h")
        genv = setup_gbrain(home)
        print(f"  [gbrain] brain ready → {home}\n")

    heng = None
    if not args.no_hydra:
        heng = setup_hydra()
        print()

    agg = {"g_r": 0.0, "g_m": 0.0, "h_r": 0.0, "h_m": 0.0, "g_t": 0.0, "h_t": 0.0}
    per_cat = defaultdict(lambda: {"n": 0, "g_r": 0.0, "h_r": 0.0})
    rows = []

    for i, tc in enumerate(TEST_CASES, 1):
        g_texts, g_dt = (gbrain_search(genv, tc.question, args.k) if genv else ([], 0.0))
        h_texts, h_dt = (hydra_search(heng, tc.question, args.k) if heng else ([], 0.0))
        g_r = recall_at_k(g_texts, tc.gold_keywords, args.k); g_m = mrr(g_texts, tc.gold_keywords)
        h_r = recall_at_k(h_texts, tc.gold_keywords, args.k); h_m = mrr(h_texts, tc.gold_keywords)
        agg["g_r"] += g_r; agg["g_m"] += g_m; agg["h_r"] += h_r; agg["h_m"] += h_m
        agg["g_t"] += g_dt; agg["h_t"] += h_dt
        c = per_cat[tc.category]; c["n"] += 1; c["g_r"] += g_r; c["h_r"] += h_r
        rows.append({"category": tc.category, "name": tc.name, "question": tc.question,
                     "gbrain_recall": g_r, "hydra_recall": h_r,
                     "gbrain_mrr": g_m, "hydra_mrr": h_m})
        print(f"  [{i:2}/{len(TEST_CASES)}] {tc.category[:20]:20} "
              f"R@{args.k} gbrain={g_r:.2f} hydra={h_r:.2f}")

    n = len(TEST_CASES)
    summary = {
        "n": n, "top_k": args.k,
        "gbrain": {"recall@k": agg["g_r"]/n, "mrr": agg["g_m"]/n, "avg_query_s": agg["g_t"]/n},
        "hydra":  {"recall@k": agg["h_r"]/n, "mrr": agg["h_m"]/n, "avg_query_s": agg["h_t"]/n},
        "per_category": {k: {"n": v["n"], "gbrain_recall": v["g_r"]/v["n"], "hydra_recall": v["h_r"]/v["n"]}
                         for k, v in per_cat.items()},
    }
    out = {"summary": summary, "rows": rows}
    (REPO / "bench" / "headtohead_results.json").write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 72)
    print("  RESULTS — real gbrain vs HydraDB")
    print("=" * 72)
    print(f"  recall@{args.k}   gbrain {summary['gbrain']['recall@k']*100:5.1f}%   "
          f"HydraDB {summary['hydra']['recall@k']*100:5.1f}%")
    print(f"  MRR         gbrain {summary['gbrain']['mrr']:.3f}    HydraDB {summary['hydra']['mrr']:.3f}")
    print("\n  recall@{} by category:".format(args.k))
    for cat, v in summary["per_category"].items():
        print(f"    {cat[:26]:26} n={v['n']:2}  gbrain={v['gbrain_recall']*100:5.1f}%  hydra={v['hydra_recall']*100:5.1f}%")
    print(f"\n  (avg query wall-time — gbrain {summary['gbrain']['avg_query_s']:.2f}s incl. CLI cold-start,"
          f" HydraDB {summary['hydra']['avg_query_s']:.2f}s; NOT a fair latency comparison — see Phase 2)")
    print(f"\n  saved → bench/headtohead_results.json")


if __name__ == "__main__":
    main(sys.argv[1:])
