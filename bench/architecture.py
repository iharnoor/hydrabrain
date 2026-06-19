"""Architecture benchmark — the one head-to-head that needs no live API.

gbrain's accuracy benchmark needs both services up; this one is purely structural,
measured from the two real codebases in this repo. It quantifies HydraDB's genuine
edge — radical retrieval simplicity — and is honest about the tradeoff that buys it.

What it measures (all deterministic, reproducible):
  • retrieval-pipeline source size (LOC) for each system
  • number of assembled retrieval stages a maintainer must own
  • number of external models/services the retrieval path depends on

Run: python3 -m bench.architecture
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _loc(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return total


def main():
    gbrain_search = sorted((REPO / "src" / "core" / "search").rglob("*.ts"))
    gbrain_loc = _loc(gbrain_search)
    hydra_files = [REPO / "hydrabrain" / "client.py", REPO / "hydrabrain" / "engine.py"]
    hydra_loc = _loc(hydra_files)

    # Assembled retrieval stages a maintainer owns (from each system's own docs/code).
    # gbrain: dense(HNSW) + BM25(tsvector) + RRF fusion + reranker + LLM query-expansion + graph
    gbrain_stages = ["dense vector (HNSW)", "BM25 (tsvector)", "reciprocal-rank fusion",
                     "reranker model", "LLM query-expansion", "knowledge-graph walk"]
    # HydraDB: one recall() call; the server fuses dense + BM25 + inferred-graph internally.
    hydra_stages = ["one recall() call (server fuses dense + BM25 + graph)"]

    gbrain_deps = ["Postgres/PGLite + pgvector", "embedding API", "reranker model", "expansion LLM"]
    hydra_deps = ["HydraDB API (hosted)"]

    print("=" * 70)
    print("  Architecture benchmark — retrieval surface (real code in this repo)")
    print("=" * 70)
    print(f"  retrieval pipeline LOC       gbrain {gbrain_loc:>6}   HydraDB {hydra_loc:>5}")
    print(f"    ({len(gbrain_search)} files in src/core/search)        (client.py + engine.py)")
    ratio = gbrain_loc / hydra_loc if hydra_loc else 0
    print(f"    → HydraDB's retrieval surface is ~{ratio:.0f}x smaller")
    print(f"  assembled stages to own      gbrain {len(gbrain_stages):>6}   HydraDB {len(hydra_stages):>5}")
    print(f"  external models/services     gbrain {len(gbrain_deps):>6}   HydraDB {len(hydra_deps):>5}")
    print()
    print("  gbrain assembles:  " + " + ".join(gbrain_stages))
    print("  HydraDB:           " + hydra_stages[0])
    print()
    print("  ── where HydraDB shines ──")
    print(f"  • {ratio:.0f}x less retrieval code; hybrid + graph in a single call, graph built on write.")
    print("  • No reranker pass and no expansion-LLM call to run/tune/pay for per query.")
    print()
    print("  ── where it does NOT win (honest) ──")
    print("  • That simplicity is bought with a HOSTED dependency: when the HydraDB API is")
    print("    down, retrieval returns nothing. gbrain's PGLite is local-first and always up.")
    print("  • Accuracy is a SEPARATE benchmark (bench/headtohead.py) and is not settled here.")
    print("  • gbrain's published accuracy (R@5 97.9% on a 240-doc entity corpus) is strong;")
    print("    we have not yet matched it in a confirmed head-to-head.")

    return {"gbrain_loc": gbrain_loc, "hydra_loc": hydra_loc, "ratio": ratio,
            "gbrain_stages": len(gbrain_stages), "hydra_stages": len(hydra_stages)}


if __name__ == "__main__":
    main()
