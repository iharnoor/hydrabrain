"""HydraDB vs gbrain-stack benchmark.

Same corpus, same queries, same gold labels, same metric gbrain reports for
itself (P@5 / recall@5, plus MRR and an LLM-as-judge answer-quality layer).

    HydraDB         : graph-native hybrid recall (full_recall, graph_context=True)
    gbrain-stack    : dense(pgvector-equiv) + BM25 + RRF, NO knowledge graph

Usage:
    python3 -m bench.run_bench                 # retrieval metrics (ingests Hydra if empty)
    python3 -m bench.run_bench --judge         # + LLM-as-judge answer quality
    python3 -m bench.run_bench --ingest        # force re-ingest the corpus into HydraDB
    python3 -m bench.run_bench --no-hydra       # baseline only (offline)
    python3 -m bench.run_bench --report         # also write bench/report.html
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from hydrabrain import config
from hydrabrain.client import Chunk
from .dataset import PAGES, TEST_CASES
from .gbrain_stack import GBrainStack

RESULTS_PATH = Path(__file__).resolve().parent / "results.json"
TOP_K = 5


# ── metrics (identical logic to the reference harness) ──────────────
def _chunk_matches_group(text: str, group: list[str]) -> bool:
    low = text.lower()
    return all(kw.lower() in low for kw in group)


def recall_at_k(chunks: list[str], gold_groups: list[list[str]], k: int = TOP_K) -> float:
    if not gold_groups:
        return 0.0
    top = chunks[:k]
    hit = sum(1 for g in gold_groups if any(_chunk_matches_group(c, g) for c in top))
    return hit / len(gold_groups)


def mrr(chunks: list[str], gold_groups: list[list[str]]) -> float:
    if not gold_groups:
        return 0.0
    for rank, c in enumerate(chunks, 1):
        if any(_chunk_matches_group(c, g) for g in gold_groups):
            return 1.0 / rank
    return 0.0


# ── HydraDB corpus management ───────────────────────────────────────
def ensure_hydra_corpus(force: bool = False):
    from hydrabrain.engine import BrainEngine

    eng = BrainEngine()
    client = eng.client
    n = client.count()
    if force:
        print(f"  [HydraDB] wiping tenant '{client.tenant_id}' ({n} sources)...")
        client.wipe()
        n = 0
    if n == 0:
        print(f"  [HydraDB] ingesting {len(PAGES)} pages (infer=True → builds graph)...")
        for i, page in enumerate(PAGES, 1):
            client.add_memory(page, infer=True)
            print(f"    [{i}/{len(PAGES)}] added", flush=True)
            time.sleep(1)
        print("  [HydraDB] waiting 60s for indexing + graph wiring...")
        time.sleep(60)
    else:
        print(f"  [HydraDB] reusing {n} existing sources in '{client.tenant_id}'")
    return eng


# ── LLM-as-judge ────────────────────────────────────────────────────
def _genai():
    from google import genai

    return genai.Client(api_key=config.require("GEMINI_API_KEY"))


def generate_answer(gc, question: str, chunks: list[str]) -> str:
    if not chunks:
        return "Not found in memories"
    context = "\n\n---\n\n".join(chunks[:TOP_K])
    resp = gc.models.generate_content(
        model=config.GEMINI_CHAT_MODEL,
        contents=(
            "Answer the question using ONLY the retrieved memory chunks. Read ALL "
            "chunks carefully. Answer in ONE concise sentence. Only say 'Not found in "
            "memories' if NONE of the chunks contain relevant info.\n\n"
            f"Question: {question}\n\nRetrieved memory chunks:\n{context}"
        ),
    )
    return (resp.text or "").strip()


def judge(gc, question: str, expected: str, answer: str) -> dict:
    resp = gc.models.generate_content(
        model=config.GEMINI_CHAT_MODEL,
        contents=(
            "You are a strict grader. Does the AI answer contain the key facts of the "
            "expected answer? Respond EXACTLY as JSON: "
            '{"verdict":"YES or NO","score":<1-10>,"reasoning":"<one sentence>"}\n\n'
            f"Question: {question}\nExpected: {expected}\nAI answer: {answer}"
        ),
    )
    t = (resp.text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(t)
    except Exception:
        return {"verdict": "NO", "score": 0, "reasoning": f"parse error: {t[:120]}"}


# ── main ────────────────────────────────────────────────────────────
def main(argv=None):
    argv = argv or []
    do_judge = "--judge" in argv
    force_ingest = "--ingest" in argv
    no_hydra = "--no-hydra" in argv
    want_report = "--report" in argv
    do_rerank = "--rerank" in argv

    print("=" * 70)
    print("  HydraDB vs gbrain-stack  —  same corpus, same gold labels")
    print(f"  corpus: {len(PAGES)} pages | queries: {len(TEST_CASES)} | metric: recall@{TOP_K}, MRR")
    print("=" * 70)

    # baseline (local, fast)
    label = "dense + BM25 + RRF + rerank" if do_rerank else "dense + BM25 + RRF"
    print(f"\n[1/3] Building gbrain-stack baseline ({label})...")
    base = GBrainStack(rerank=do_rerank)
    base.ingest(PAGES)
    print(f"  baseline ready: {len(base.docs)} docs embedded + BM25 indexed"
          + ("  + LLM reranker on" if do_rerank else ""))

    # hydra
    eng = None
    if not no_hydra:
        print("\n[2/3] Preparing HydraDB...")
        eng = ensure_hydra_corpus(force=force_ingest)

    gc = _genai() if do_judge else None
    rows = []
    h_recalls, h_mrrs, b_recalls, b_mrrs = [], [], [], []
    h_yes = b_yes = 0

    print("\n[3/3] Running queries...\n")
    for i, case in enumerate(TEST_CASES, 1):
        q = case.question
        b_chunks = [c.text for c in base.search(q, k=TOP_K)]
        b_r, b_m = recall_at_k(b_chunks, case.gold_keywords), mrr(b_chunks, case.gold_keywords)
        b_recalls.append(b_r); b_mrrs.append(b_m)

        h_chunks: list[str] = []
        h_r = h_m = 0.0
        if eng is not None:
            try:
                h_chunks = [c.text for c in eng.search(q, k=TOP_K, graph=True)]
            except Exception as e:
                print(f"    HydraDB recall error: {e}")
            h_r, h_m = recall_at_k(h_chunks, case.gold_keywords), mrr(h_chunks, case.gold_keywords)
            h_recalls.append(h_r); h_mrrs.append(h_m)

        row = {
            "name": case.name, "category": case.category, "question": q,
            "expected": case.expected,
            "hydra_recall": h_r, "hydra_mrr": h_m,
            "base_recall": b_r, "base_mrr": b_m,
            "hydra_chunks": h_chunks, "base_chunks": b_chunks,
        }

        if do_judge:
            b_ans = generate_answer(gc, q, b_chunks)
            b_j = judge(gc, q, case.expected, b_ans)
            row["base_answer"], row["base_verdict"] = b_ans, b_j.get("verdict", "NO")
            b_yes += row["base_verdict"] == "YES"
            if eng is not None:
                h_ans = generate_answer(gc, q, h_chunks)
                h_j = judge(gc, q, case.expected, h_ans)
                row["hydra_answer"], row["hydra_verdict"] = h_ans, h_j.get("verdict", "NO")
                h_yes += row["hydra_verdict"] == "YES"

        rows.append(row)
        tag = ""
        if eng is not None:
            tag = "H>B" if h_r > b_r else ("B>H" if b_r > h_r else "tie")
        print(f"  [{i:2}/{len(TEST_CASES)}] {case.name[:38]:38} "
              f"H r@5={h_r:.2f} mrr={h_m:.2f} | B r@5={b_r:.2f} mrr={b_m:.2f}  {tag}")

    n = len(TEST_CASES)
    summary = {
        "corpus_pages": len(PAGES), "queries": n, "top_k": TOP_K,
        "base_recall_at5": sum(b_recalls) / n, "base_mrr": sum(b_mrrs) / n,
    }
    if eng is not None:
        summary.update({
            "hydra_recall_at5": sum(h_recalls) / n, "hydra_mrr": sum(h_mrrs) / n,
            "hydra_wins": sum(1 for r in rows if r["hydra_recall"] > r["base_recall"]),
            "base_wins": sum(1 for r in rows if r["base_recall"] > r["hydra_recall"]),
            "ties": sum(1 for r in rows if r["hydra_recall"] == r["base_recall"]),
        })
    if do_judge:
        summary["base_judge_yes"] = b_yes
        if eng is not None:
            summary["hydra_judge_yes"] = h_yes

    out = {"summary": summary, "rows": rows}
    RESULTS_PATH.write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)
    if eng is not None:
        dr = summary["hydra_recall_at5"] - summary["base_recall_at5"]
        print(f"  recall@5   HydraDB {summary['hydra_recall_at5']*100:5.1f}%   "
              f"gbrain-stack {summary['base_recall_at5']*100:5.1f}%   "
              f"Δ {dr*100:+.1f} pts")
        print(f"  MRR        HydraDB {summary['hydra_mrr']:.3f}    "
              f"gbrain-stack {summary['base_mrr']:.3f}")
        print(f"  per-query  HydraDB wins {summary['hydra_wins']}  |  "
              f"gbrain-stack wins {summary['base_wins']}  |  ties {summary['ties']}")
    else:
        print(f"  recall@5   gbrain-stack {summary['base_recall_at5']*100:5.1f}%   "
              f"MRR {summary['base_mrr']:.3f}  (baseline only)")
    if do_judge:
        line = f"  LLM-judge  gbrain-stack {b_yes}/{n} YES"
        if eng is not None:
            line = f"  LLM-judge  HydraDB {h_yes}/{n} YES   gbrain-stack {b_yes}/{n} YES"
        print(line)
    print(f"\n  saved → {RESULTS_PATH}")

    if want_report:
        from .report import write_report

        path = write_report(out)
        print(f"  report → {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
