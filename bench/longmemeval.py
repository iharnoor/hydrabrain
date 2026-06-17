"""LongMemEval benchmark — HydraDB vs gbrain-stack.

LongMemEval (ICLR 2025) is the standard benchmark for long-term memory in chat
assistants: each of 500 questions ships its OWN haystack of chat sessions
(~48 sessions / ~115K tokens in the full `_s` split; only the evidence sessions
in the `oracle` split). The system must store the haystack, retrieve the right
sessions, and answer correctly across 6 abilities: information extraction,
multi-session reasoning, temporal reasoning, knowledge updates, preferences, and
abstention.

This is HydraDB's home turf — the regime it's built for (multi-session reasoning
at scale), versus the tiny 19-page corpus in run_bench.py.

How the comparison is kept fair and isolated:
  • Each question's haystack is ingested into its OWN namespace:
      HydraDB      → sub_tenant_id = question_id (verified to isolate cleanly)
      gbrain-stack → a fresh in-memory dense+BM25+RRF index per question
  • One memory unit per session (dated transcript), identical for both systems.
  • Two metrics:
      evidence recall@k — did top-k retrieval include a gold answer session?
      QA accuracy       — LLM-as-judge (Gemini) grades the generated answer,
                          with abstention handling for `_abs` questions.

Usage:
  python3 -m bench.longmemeval --limit 15
  python3 -m bench.longmemeval --limit 30 --types temporal-reasoning,multi-session
  python3 -m bench.longmemeval --data bench/data/longmemeval_s.json --limit 50
  python3 -m bench.longmemeval --no-hydra --limit 50        # baseline only (offline)
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from hydrabrain import config
from hydrabrain.client import HydraDBClient
from .gbrain_stack import GBrainStack

DATA_DEFAULT = Path(__file__).resolve().parent / "data" / "longmemeval_oracle.json"
RESULTS_PATH = Path(__file__).resolve().parent / "longmemeval_results.json"
TOP_K = 5


# ── corpus building ────────────────────────────────────────────────
def session_to_text(date: str, turns: list[dict]) -> str:
    lines = [f"[session date: {date}]"]
    for t in turns:
        role = t.get("role", "user")
        lines.append(f"{role}: {t.get('content','').strip()}")
    return "\n".join(lines)


def build_units(q: dict) -> list[tuple[str, str]]:
    """Return [(session_id, session_text)] for one question's haystack."""
    out = []
    dates = q.get("haystack_dates", [])
    sids = q.get("haystack_session_ids", [])
    for i, sess in enumerate(q["haystack_sessions"]):
        sid = sids[i] if i < len(sids) else f"sess_{i}"
        date = dates[i] if i < len(dates) else "unknown"
        out.append((sid, session_to_text(date, sess)))
    return out


def is_evidence(retrieved_sids: list[str], gold_sids: list[str]) -> bool:
    gold = set(gold_sids or [])
    return any(s in gold for s in retrieved_sids)


# ── LLM answer + judge ─────────────────────────────────────────────
def _genai():
    from google import genai

    return genai.Client(api_key=config.require("GEMINI_API_KEY"))


def generate_answer(gc, question: str, contexts: list[str]) -> str:
    if not contexts:
        return "I don't know."
    ctx = "\n\n---\n\n".join(contexts[:TOP_K])
    resp = gc.models.generate_content(
        model=config.GEMINI_CHAT_MODEL,
        contents=(
            "You are a personal assistant answering from the user's chat history. "
            "Use ONLY the retrieved sessions below. Answer concisely. If the answer is "
            "not present, say 'I don't know'.\n\n"
            f"Question: {question}\n\nRetrieved sessions:\n{ctx}"
        ),
    )
    return (resp.text or "").strip()


def judge(gc, question: str, gold: str, answer: str, qtype: str, abstain: bool) -> bool:
    if abstain:
        # Correct iff the model declines to answer / says it doesn't know.
        low = answer.lower()
        return any(p in low for p in ["i don't know", "i do not know", "not sure",
                                      "no information", "cannot find", "couldn't find",
                                      "not mentioned", "don't have"])
    resp = gc.models.generate_content(
        model=config.GEMINI_CHAT_MODEL,
        contents=(
            f"You are grading a memory assistant on a '{qtype}' question. Is the model's "
            "answer correct — does it contain the key facts of the gold answer? Be strict "
            "but accept paraphrases and extra correct detail. Respond with EXACTLY 'YES' or 'NO'.\n\n"
            f"Question: {question}\nGold answer: {gold}\nModel answer: {answer}"
        ),
    )
    return (resp.text or "").strip().upper().startswith("YES")


# ── runners ────────────────────────────────────────────────────────
def run_hydra(client: HydraDBClient, q: dict, units: list[tuple[str, str]],
              wait: int) -> tuple[list[str], list[str]]:
    """Ingest units under sub_tenant=question_id, wait, retrieve. Returns (texts, sids)."""
    qid = q["question_id"]
    text_by_sid = {sid: txt for sid, txt in units}
    for sid, txt in units:
        client.add_memory(txt, infer=True, sub_tenant_id=qid)
    time.sleep(wait)
    chunks = client.recall_preferences(
        q["question"], max_results=TOP_K, graph_context=True,
        mode=config.HYDRA_RECALL_MODE, alpha=config.HYDRA_RECALL_ALPHA,
        sub_tenant_id=qid,
    )
    texts = [c.text for c in chunks]
    # Map each retrieved chunk back to its source session id. HydraDB re-chunks
    # sessions, so match by max character-window overlap rather than prefix.
    sids = [_best_session(c.text, units) for c in chunks]
    return texts, sids


def _best_session(chunk: str, units: list[tuple[str, str]]) -> str:
    """Pick the session id whose text best contains the retrieved chunk."""
    best_sid, best_score = "", 0
    c = chunk.strip()
    # Try a few distinctive windows from the chunk against each session.
    windows = [c[i:i + 60] for i in range(0, max(1, len(c) - 60), 60)][:6] or [c[:60]]
    for sid, txt in units:
        score = sum(1 for w in windows if w and w in txt)
        if score > best_score:
            best_sid, best_score = sid, score
    return best_sid


def run_baseline(q: dict, units: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    base = GBrainStack()
    base.docs = [txt for _, txt in units]
    # build indexes
    from .gbrain_stack import _embed, _tok
    from rank_bm25 import BM25Okapi
    base._vecs = _embed(base.docs)
    base._bm25 = BM25Okapi([_tok(d) for d in base.docs])
    hits = base.search(q["question"], k=TOP_K)
    texts = [h.text for h in hits]
    sid_by_text = {txt: sid for sid, txt in units}
    sids = [sid_by_text.get(t, "") for t in texts]
    return texts, sids


# ── main ────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_DEFAULT))
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--types", default="", help="comma-separated question_type filter")
    ap.add_argument("--hydra-wait", type=int, default=60, help="seconds to wait for async indexing per question (HydraDB graph wiring; too low understates HydraDB)")
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv or [])

    data = json.loads(Path(args.data).read_text())
    if args.types:
        keep = set(args.types.split(","))
        data = [q for q in data if q.get("question_type") in keep]
    # Stable, type-balanced sample: round-robin across types so a small --limit
    # still covers every ability.
    by_type = defaultdict(list)
    for q in data:
        by_type[q["question_type"]].append(q)
    ordered = []
    while len(ordered) < len(data):
        for t in sorted(by_type):
            if by_type[t]:
                ordered.append(by_type[t].pop(0))
    sample = ordered[: args.limit]

    print("=" * 70)
    print("  LongMemEval — HydraDB vs gbrain-stack")
    print(f"  data: {Path(args.data).name} | sampled {len(sample)} questions")
    print(f"  type mix: {dict(Counter(q['question_type'] for q in sample))}")
    print("=" * 70)

    client = None
    if not args.no_hydra:
        client = HydraDBClient(api_key=config.require("HYDRADB_API_KEY")).use_tenant(config.DEFAULT_TENANT)

    gc = _genai()
    rows = []
    agg = {"h_rec": 0, "b_rec": 0, "h_qa": 0, "b_qa": 0}
    per_type = defaultdict(lambda: {"n": 0, "h_qa": 0, "b_qa": 0})

    for i, q in enumerate(sample, 1):
        qid = q["question_id"]
        qtype = q["question_type"]
        abstain = qid.endswith("_abs")
        units = build_units(q)

        b_texts, b_sids = run_baseline(q, units)
        b_rec = is_evidence(b_sids, q["answer_session_ids"])
        b_ans = generate_answer(gc, q["question"], b_texts)
        b_qa = judge(gc, q["question"], q["answer"], b_ans, qtype, abstain)

        h_rec = h_qa = False
        h_ans = ""
        if client is not None:
            try:
                h_texts, h_sids = run_hydra(client, q, units, args.hydra_wait)
                h_rec = is_evidence(h_sids, q["answer_session_ids"])
                h_ans = generate_answer(gc, q["question"], h_texts)
                h_qa = judge(gc, q["question"], q["answer"], h_ans, qtype, abstain)
            except Exception as e:
                print(f"    HydraDB error on {qid}: {repr(e)[:80]}")

        agg["b_rec"] += b_rec; agg["b_qa"] += b_qa
        agg["h_rec"] += h_rec; agg["h_qa"] += h_qa
        per_type[qtype]["n"] += 1
        per_type[qtype]["h_qa"] += h_qa; per_type[qtype]["b_qa"] += b_qa

        rows.append({"question_id": qid, "type": qtype, "abstain": abstain,
                     "question": q["question"], "gold": q["answer"],
                     "hydra_recall": h_rec, "base_recall": b_rec,
                     "hydra_qa": h_qa, "base_qa": b_qa,
                     "hydra_answer": h_ans, "base_answer": b_ans})
        print(f"  [{i:2}/{len(sample)}] {qtype[:22]:22} "
              f"QA H={'Y' if h_qa else '.'} B={'Y' if b_qa else '.'}  "
              f"evid H={'Y' if h_rec else '.'} B={'Y' if b_rec else '.'}")

    n = len(sample)
    summary = {
        "n": n, "data": Path(args.data).name, "top_k": TOP_K,
        "base_qa_acc": agg["b_qa"] / n, "base_evidence_recall": agg["b_rec"] / n,
        "type_mix": dict(Counter(q["question_type"] for q in sample)),
    }
    if client is not None:
        summary.update({"hydra_qa_acc": agg["h_qa"] / n,
                        "hydra_evidence_recall": agg["h_rec"] / n})
    summary["per_type"] = {t: {"n": v["n"],
                               "hydra_qa": v["h_qa"] / v["n"],
                               "base_qa": v["b_qa"] / v["n"]} for t, v in per_type.items()}

    out = {"summary": summary, "rows": rows}
    RESULTS_PATH.write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 70)
    print("  LONGMEMEVAL RESULTS")
    print("=" * 70)
    if client is not None:
        print(f"  QA accuracy        HydraDB {summary['hydra_qa_acc']*100:5.1f}%   "
              f"gbrain-stack {summary['base_qa_acc']*100:5.1f}%")
        print(f"  evidence recall@{TOP_K}  HydraDB {summary['hydra_evidence_recall']*100:5.1f}%   "
              f"gbrain-stack {summary['base_evidence_recall']*100:5.1f}%")
        print("\n  QA accuracy by ability:")
        for t, v in summary["per_type"].items():
            print(f"    {t:26} n={v['n']:2}  H={v['hydra_qa']*100:5.1f}%  B={v['base_qa']*100:5.1f}%")
    else:
        print(f"  QA accuracy gbrain-stack {summary['base_qa_acc']*100:.1f}%  "
              f"evidence recall {summary['base_evidence_recall']*100:.1f}%")
    print(f"\n  saved → {RESULTS_PATH}")

    if args.report:
        from .lme_report import write_report
        print(f"  report → {write_report(out)}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
