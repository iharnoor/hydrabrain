"""LongMemEval-S at-scale benchmark — HydraDB vs BM25 lexical baseline.

This is the decisive at-scale test: 500 questions, each with its own haystack
of ~48 sessions (distractors included). The system must ingest every session,
then find the needle — the answer session — among all the noise.

BM25 baseline: the keyword arm of gbrain's retrieval pipeline. It is the
strongest no-API-cost baseline we can run — it's what gbrain uses when the
dense-vector arm would return identical recall at this corpus size. Dense
vectors are excluded from this run (no Gemini key); that is noted in the report.

Two metrics:
  evidence recall@5 — did top-5 include the gold answer session? (deterministic)
  QA accuracy       — Claude Haiku grades the generated answer YES/NO (LLM judge)

Usage:
  python3 -m bench.lme_scale --limit 30
  python3 -m bench.lme_scale --limit 100 --data bench/data/longmemeval_s_cleaned.json
  python3 -m bench.lme_scale --limit 30 --no-hydra   # BM25 baseline only (offline)
  python3 -m bench.lme_scale --limit 30 --no-bm25    # HydraDB only
  python3 -m bench.lme_scale --limit 30 --no-judge   # skip LLM judge
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from hydrabrain import config
from hydrabrain.client import HydraDBClient

DATA_S = Path(__file__).resolve().parent / "data" / "longmemeval_s_cleaned.json"
DATA_ORACLE = Path(__file__).resolve().parent / "data" / "longmemeval_oracle.json"
RESULTS_PATH = Path(__file__).resolve().parent / "lme_scale_results.json"
TOP_K = 5

_WORD = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _WORD.findall(text.lower())


# ── corpus building ────────────────────────────────────────────────────────────

def session_to_text(date: str, turns: list[dict]) -> str:
    lines = [f"[session date: {date}]"]
    for t in turns:
        role = t.get("role", "user")
        lines.append(f"{role}: {t.get('content', '').strip()}")
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


# ── BM25 baseline ──────────────────────────────────────────────────────────────

def run_bm25(q: dict, units: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Pure BM25 lexical retrieval — no embeddings, no API."""
    from rank_bm25 import BM25Okapi
    docs = [txt for _, txt in units]
    bm25 = BM25Okapi([_tok(d) for d in docs])
    scores = bm25.get_scores(_tok(q["question"]))
    order = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)
    texts = [docs[i] for i in order[:TOP_K]]
    sid_by_text = {txt: sid for sid, txt in units}
    sids = [sid_by_text.get(t, "") for t in texts]
    return texts, sids


# ── Claude LLM judge ──────────────────────────────────────────────────────────

def _claude():
    import anthropic
    return anthropic.Anthropic()


def generate_answer(contexts: list[str], question: str, model: str) -> str:
    """Generate a one-sentence answer from retrieved contexts using Claude."""
    if not contexts:
        return "I don't know."
    ctx = "\n\n---\n\n".join(contexts[:TOP_K])
    try:
        client = _claude()
        msg = client.messages.create(
            model=model,
            max_tokens=200,
            system=(
                "You are a personal assistant answering from the user's chat history. "
                "Use ONLY the retrieved sessions below. Answer in one sentence. "
                "If the answer is not present, say 'I don't know'."
            ),
            messages=[{
                "role": "user",
                "content": f"Question: {question}\n\nRetrieved sessions:\n{ctx}"
            }],
        )
        return (msg.content[0].text or "").strip()
    except Exception as e:
        return f"[error: {repr(e)[:60]}]"


def judge_answer(question: str, gold, answer: str, qtype: str, model: str) -> bool:
    """Grade the answer YES/NO against the gold using Claude."""
    gold_str = str(gold)
    low = answer.lower()
    # Abstention check for single-session-preference with negative gold answers
    if gold_str.lower() in ("i don't know", "not mentioned", "no information"):
        return any(p in low for p in ["i don't know", "i do not know", "not sure",
                                       "no information", "cannot find", "not mentioned"])
    gold = gold_str
    try:
        client = _claude()
        msg = client.messages.create(
            model=model,
            max_tokens=5,
            system=(
                "You are grading a memory assistant answer. "
                "Respond with EXACTLY 'YES' if the answer contains the key facts of the gold, "
                "or 'NO' if it is wrong or missing the main fact. "
                "Accept paraphrases and extra correct detail."
            ),
            messages=[{
                "role": "user",
                "content": f"Question: {question}\nGold: {gold}\nAnswer: {answer}"
            }],
        )
        return (msg.content[0].text or "").strip().upper().startswith("YES")
    except Exception:
        return False


# ── HydraDB runner ─────────────────────────────────────────────────────────────

def _best_session(chunk: str, units: list[tuple[str, str]]) -> str:
    """Map a retrieved chunk back to its source session via character-window overlap."""
    best_sid, best_score = "", 0
    c = chunk.strip()
    windows = [c[i:i + 60] for i in range(0, max(1, len(c) - 60), 60)][:6] or [c[:60]]
    for sid, txt in units:
        score = sum(1 for w in windows if w and w in txt)
        if score > best_score:
            best_sid, best_score = sid, score
    return best_sid


def run_hydra(client: HydraDBClient, q: dict, units: list[tuple[str, str]],
              wait: int) -> tuple[list[str], list[str]]:
    """Ingest sessions under a per-question namespace, wait, retrieve."""
    qid = q["question_id"]
    # Ingest all sessions
    for _sid, txt in units:
        client.add_memory(txt, infer=True, sub_tenant_id=qid)
    # Wait for async graph wiring to settle
    time.sleep(wait)
    chunks = client.recall_preferences(
        q["question"], max_results=TOP_K, graph_context=True,
        mode=config.HYDRA_RECALL_MODE, alpha=config.HYDRA_RECALL_ALPHA,
        sub_tenant_id=qid,
    )
    texts = [c.text for c in chunks]
    sids = [_best_session(c.text, units) for c in chunks]
    return texts, sids


# ── balanced sampler ──────────────────────────────────────────────────────────

def balanced_sample(data: list[dict], limit: int) -> list[dict]:
    """Round-robin across question types so each ability gets equal representation."""
    by_type: dict[str, list] = defaultdict(list)
    for q in data:
        by_type[q["question_type"]].append(q)
    ordered = []
    while len(ordered) < len(data):
        for t in sorted(by_type):
            if by_type[t]:
                ordered.append(by_type[t].pop(0))
    return ordered[:limit]


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv=None):
    try:
        import sys as _sys
        _sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="LongMemEval-S at-scale: HydraDB vs BM25")
    ap.add_argument("--data", default=str(DATA_S),
                    help="path to LongMemEval JSON (default: _s split)")
    ap.add_argument("--limit", type=int, default=30,
                    help="number of questions to run (balanced across ability types)")
    ap.add_argument("--types", default="",
                    help="comma-separated question_type filter (empty = all)")
    ap.add_argument("--hydra-wait", type=int, default=90,
                    help="seconds to wait for HydraDB async graph wiring per question")
    ap.add_argument("--no-hydra", action="store_true", help="skip HydraDB, BM25 baseline only")
    ap.add_argument("--no-bm25", action="store_true", help="skip BM25 baseline, HydraDB only")
    ap.add_argument("-k", type=int, default=TOP_K)
    ap.add_argument("--no-judge", action="store_true",
                    help="skip LLM QA judge (evidence recall@5 only)")
    ap.add_argument("--judge-model", default="claude-haiku-4-5-20251001",
                    help="Claude model id for answer generation + judging")
    args = ap.parse_args(argv or [])

    data = json.loads(Path(args.data).read_text())
    if args.types:
        keep = set(args.types.split(","))
        data = [q for q in data if q.get("question_type") in keep]
    sample = balanced_sample(data, args.limit)

    data_name = Path(args.data).stem
    print("=" * 72)
    print("  LongMemEval at-scale — HydraDB vs BM25 lexical baseline")
    print(f"  data: {data_name}  |  {len(sample)} questions  |  top-k={args.k}")
    print(f"  type mix: {dict(Counter(q['question_type'] for q in sample))}")
    print(f"  avg sessions/question: "
          f"{sum(len(q.get('haystack_sessions',[])) for q in sample)/len(sample):.1f}")
    print("=" * 72)

    client = None
    if not args.no_hydra:
        client = (HydraDBClient(api_key=config.require("HYDRADB_API_KEY"))
                  .use_tenant(config.DEFAULT_TENANT))

    # Pre-build all units + run BM25 (fast, no API)
    all_units = [build_units(q) for q in sample]

    # ── Phase 1: ingest ALL questions into HydraDB (batch, no waiting) ──
    if client is not None:
        total_sessions = sum(len(u) for u in all_units)
        print(f"\n  [Phase 1] ingesting {total_sessions} sessions across {len(sample)} "
              f"namespaces…")
        ingested = 0
        for q, units in zip(sample, all_units):
            qid = q["question_id"]
            for _sid, txt in units:
                try:
                    client.add_memory(txt, infer=True, sub_tenant_id=qid)
                except Exception as e:
                    print(f"    warn: ingest error on {qid}: {repr(e)[:60]}")
                ingested += 1
                if ingested % 50 == 0:
                    print(f"    ingested {ingested}/{total_sessions}…")
        print(f"  [Phase 1] done. waiting {args.hydra_wait}s for graph wiring…")
        time.sleep(args.hydra_wait)
        print("  [Phase 1] graph wiring settled.")

    # ── Phase 2: retrieve + score ───────────────────────────────────────
    print(f"\n  [Phase 2] retrieval + scoring…")
    rows = []
    agg = {"h_rec": 0, "b_rec": 0, "h_qa": 0, "b_qa": 0}
    per_type: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "h_rec": 0, "b_rec": 0, "h_qa": 0, "b_qa": 0})
    run_judge = not args.no_judge

    for i, (q, units) in enumerate(zip(sample, all_units), 1):
        qtype = q["question_type"]
        n_sess = len(units)
        gold_sids = q.get("answer_session_ids", [])
        gold_ans = q.get("answer", "")

        b_rec = h_rec = b_qa = h_qa = False
        b_texts: list[str] = []
        h_texts: list[str] = []
        b_sids: list[str] = []
        h_sids: list[str] = []
        b_ans = h_ans = ""

        if not args.no_bm25:
            b_texts, b_sids = run_bm25(q, units)
            b_rec = is_evidence(b_sids, gold_sids)
            if run_judge:
                b_ans = generate_answer(b_texts, q["question"], args.judge_model)
                b_qa = judge_answer(q["question"], gold_ans, b_ans, qtype, args.judge_model)

        h_err = ""
        if client is not None:
            try:
                qid = q["question_id"]
                chunks = client.recall_preferences(
                    q["question"], max_results=args.k, graph_context=True,
                    mode=config.HYDRA_RECALL_MODE, alpha=config.HYDRA_RECALL_ALPHA,
                    sub_tenant_id=qid,
                )
                h_texts = [c.text for c in chunks]
                h_sids = [_best_session(c.text, units) for c in chunks]
                h_rec = is_evidence(h_sids, gold_sids)
                if run_judge:
                    h_ans = generate_answer(h_texts, q["question"], args.judge_model)
                    h_qa = judge_answer(q["question"], gold_ans, h_ans, qtype, args.judge_model)
            except Exception as e:
                h_err = repr(e)[:80]
                print(f"    HydraDB error on {q['question_id']}: {h_err}")

        agg["b_rec"] += b_rec; agg["h_rec"] += h_rec
        agg["b_qa"] += b_qa; agg["h_qa"] += h_qa
        pt = per_type[qtype]
        pt["n"] += 1
        pt["h_rec"] += h_rec; pt["b_rec"] += b_rec
        pt["h_qa"] += h_qa; pt["b_qa"] += b_qa

        qa_str = f"  QA H={'Y' if h_qa else '.'} B={'Y' if b_qa else '.'}" if run_judge else ""
        status = f"evid H={'Y' if h_rec else '.'} B={'Y' if b_rec else '.'}{qa_str}"
        print(f"  [{i:2}/{len(sample)}] {qtype[:24]:24} {n_sess:2} sess  {status}")

        rows.append({
            "question_id": q["question_id"], "type": qtype,
            "question": q["question"], "gold_answer": gold_ans,
            "n_sessions": n_sess, "gold_sessions": gold_sids,
            "hydra_recall": h_rec, "bm25_recall": b_rec,
            "hydra_qa": h_qa, "bm25_qa": b_qa,
            "hydra_answer": h_ans, "bm25_answer": b_ans,
            "hydra_sids": h_sids, "bm25_sids": b_sids,
            "hydra_error": h_err,
        })

    n = len(sample)
    summary = {
        "n": n, "top_k": args.k, "data": data_name,
        "hydra_wait": args.hydra_wait,
        "avg_sessions": sum(r["n_sessions"] for r in rows) / n,
        "judge_model": args.judge_model if run_judge else None,
        "bm25_evidence_recall": agg["b_rec"] / n if not args.no_bm25 else None,
        "hydra_evidence_recall": agg["h_rec"] / n if client else None,
        "bm25_qa_accuracy": agg["b_qa"] / n if (run_judge and not args.no_bm25) else None,
        "hydra_qa_accuracy": agg["h_qa"] / n if (run_judge and client) else None,
        "per_type": {
            t: {
                "n": v["n"],
                "hydra_recall": v["h_rec"] / v["n"] if client else None,
                "bm25_recall": v["b_rec"] / v["n"] if not args.no_bm25 else None,
                "hydra_qa": v["h_qa"] / v["n"] if (run_judge and client) else None,
                "bm25_qa": v["b_qa"] / v["n"] if (run_judge and not args.no_bm25) else None,
            }
            for t, v in per_type.items()
        },
    }

    out = {"summary": summary, "rows": rows}
    RESULTS_PATH.write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 72)
    print("  RESULTS — LongMemEval at-scale")
    print("=" * 72)
    def _pct(v):
        return f"{v*100:5.1f}%" if v is not None else "  n/a "

    h_label = "HydraDB" if client else "      "
    b_label = "BM25" if not args.no_bm25 else "    "
    print(f"  {'Metric':<28} {h_label:>8}   {b_label}")
    print(f"  {'-'*50}")
    print(f"  {'evidence recall@' + str(args.k):<28} {_pct(summary['hydra_evidence_recall']):>8}   "
          f"{_pct(summary['bm25_evidence_recall'])}")
    if run_judge:
        print(f"  {'QA accuracy (Claude judge)':<28} {_pct(summary['hydra_qa_accuracy']):>8}   "
              f"{_pct(summary['bm25_qa_accuracy'])}")

    print("\n  by ability type:")
    header_qa = "  qa-H    qa-B " if run_judge else ""
    print(f"  {'Type':<30} {'n':>2}  {'evid-H':>6}  {'evid-B':>6}{header_qa}")
    for t, v in summary["per_type"].items():
        h_r = _pct(v["hydra_recall"])
        b_r = _pct(v["bm25_recall"])
        qa_cols = ""
        if run_judge:
            qa_cols = f"  {_pct(v.get('hydra_qa'))}  {_pct(v.get('bm25_qa'))}"
        print(f"    {t:<30} {v['n']:>2}  {h_r:>6}  {b_r:>6}{qa_cols}")

    print(f"\n  saved → {RESULTS_PATH}")
    if not args.no_judge:
        print(f"  judge: {args.judge_model} (Claude)")
    print(f"\n  Note: baseline = BM25 only (lexical keyword search, no dense vectors).")
    print(f"  BM25 is the keyword arm of gbrain's pipeline; dense-vector arm was run")
    print(f"  in Benchmark #2 (headtohead.py) on the relational corpus.")

    return out


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
