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
      QA accuracy       — LLM-as-judge (Claude, shared with lme_scale) grades
                          the generated answer, with abstention handling for
                          `_abs` questions.

Fairness (fixed after review — each was silently penalizing one side):
  • HydraDB indexing is ASYNC: the harness now actively polls each namespace
    until its row count settles (bench/hydra_wait.py) instead of a blind sleep
    that raced the background graph wiring.
  • The baseline now CHUNKS sessions the way real gbrain does (300w/50w/6000c,
    gbrain_stack.chunk_text) — unchunked whole-session units gave it fewer
    candidates than top-k on the oracle split, winning recall by default.
  • Default sample is 90 questions (~15/type) — at 3/type one flipped answer
    swings a category ~33pp, so per-type gaps were sampling noise.

Usage:
  python3 -m bench.longmemeval                              # 90 qs, balanced
  python3 -m bench.longmemeval --limit 30 --types temporal-reasoning,multi-session
  python3 -m bench.longmemeval --data bench/data/longmemeval_s.json --limit 50
  python3 -m bench.longmemeval --no-hydra --limit 50        # baseline only (offline)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from hydrabrain import config
from hydrabrain.client import HydraDBClient
from .gbrain_stack import GBrainStack
from .hydra_wait import wait_for_indexing, wait_for_retrievable

DATA_DEFAULT = Path(__file__).resolve().parent / "data" / "longmemeval_oracle.json"
RESULTS_PATH = Path(__file__).resolve().parent / "longmemeval_results.json"
CHECKPOINT_PATH = Path(__file__).resolve().parent / "longmemeval_checkpoint.jsonl"
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
# Claude-based, shared with bench/lme_scale.py so both LongMemEval harnesses
# use the same answerer + judge. (Was Gemini; gemini-2.5-flash was retired by
# Google mid-2026 and the replacement tier is unreliable under load. The
# answerer is shared by both systems, so this doesn't affect fairness.)
from .lme_scale import generate_answer, judge_answer


def judge(question: str, gold: str, answer: str, qtype: str, abstain: bool,
          model: str) -> bool:
    if abstain:
        # Correct iff the model declines to answer / says it doesn't know.
        low = answer.lower()
        return any(p in low for p in ["i don't know", "i do not know", "not sure",
                                      "no information", "cannot find", "couldn't find",
                                      "not mentioned", "don't have"])
    return judge_answer(question, gold, answer, qtype, model)


# ── runners ────────────────────────────────────────────────────────
def run_hydra(client: HydraDBClient, q: dict, units: list[tuple[str, str]],
              wait: int) -> tuple[list[str], list[str]]:
    """Ingest units under sub_tenant=question_id, wait for indexing to actually
    settle (active poll, not a blind sleep), retrieve. Returns (texts, sids)."""
    qid = q["question_id"]
    # Guard against cross-run namespace pollution: other harnesses (lme_scale,
    # earlier runs) reuse the same question_ids as sub_tenant ids on the same
    # tenant, leaving stale sessions that silently join this run's haystack.
    # Don't wipe-and-reuse: a wiped namespace can end up search-dead (rows
    # store but never index — observed once in 35 wipes; same content in a
    # fresh namespace indexes fine). Walk to the first EMPTY namespace instead.
    for ns in [qid] + [f"{qid}-r{i}" for i in range(2, 10)]:
        if client.count(sub_tenant_id=ns) == 0:
            break
    else:
        raise RuntimeError(f"{qid}: no empty namespace found after 9 suffixes")
    if ns != qid:
        print(f"    namespace {qid} dirty — using fresh {ns}")
    for sid, txt in units:
        client.add_memory(txt, infer=True, sub_tenant_id=ns)
    # HydraDB indexes/graph-wires asynchronously after add_memory returns.
    # Two-stage readiness check (a blind sleep raced this; so did row-count
    # alone — rows appear in list_content before they are retrievable):
    #  1. row count reaches the ingested unit count and stops changing;
    #  2. the actual query returns a non-empty, stable result set.
    seen = wait_for_indexing(client, sub_tenant_id=ns, min_count=len(units),
                             timeout=wait)
    if seen < len(units):
        print(f"    warn: {ns} indexing timeout — {seen}/{len(units)} units visible")
    chunks = wait_for_retrievable(
        client, q["question"], ns,
        dict(max_results=TOP_K, graph_context=True,
             mode=config.HYDRA_RECALL_MODE, alpha=config.HYDRA_RECALL_ALPHA),
        timeout=wait,
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
    # ingest() chunks each session the way real gbrain does (300w/50w/6000c).
    # Previously each whole session was one unsplit doc — on the oracle split
    # (1-2 sessions/question, top-k=5) the baseline returned its entire corpus
    # and "won" recall by default. Chunking gives it the same real search
    # problem HydraDB solves.
    base.ingest([txt for _, txt in units])
    hits = base.search(q["question"], k=TOP_K)
    texts = [h.text for h in hits]
    # Chunks no longer exact-match a whole session's text — map each result
    # back to its source session by overlap, same as HydraDB's results.
    sids = [_best_session(t, units) for t in texts]
    return texts, sids


# ── main ────────────────────────────────────────────────────────────
def main(argv=None):
    try:  # line-buffer so progress is visible even when redirected to a file
        import sys as _sys
        _sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_DEFAULT))
    ap.add_argument("--limit", type=int, default=90,
                    help="questions to sample, balanced across the 6 types (default 90 = "
                         "~15/type; at 3/type a single flipped answer swings a category ~33pp)")
    ap.add_argument("--types", default="", help="comma-separated question_type filter")
    ap.add_argument("--hydra-wait", type=int, default=180,
                    help="TIMEOUT in seconds for HydraDB's async indexing per question — "
                         "the harness polls the namespace and proceeds as soon as the count "
                         "settles, so this is a safety cap, not a fixed sleep")
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--judge-model", default="claude-haiku-4-5-20251001",
                    help="Claude model id for answer generation + judging")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the checkpoint and rescore every question (default: "
                         "resume — completed questions are loaded from the checkpoint, "
                         "so a quota/API death doesn't lose finished work)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv or [])

    data_path = Path(args.data)
    if not data_path.exists() and data_path == DATA_DEFAULT:
        # Auto-download the oracle split (~15 MB) so the benchmark reproduces
        # from a fresh clone with one command.
        print(f"  {data_path.name} not found — downloading from Hugging Face…")
        data_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from huggingface_hub import hf_hub_download
            got = hf_hub_download(repo_id="xiaowu0162/longmemeval-cleaned",
                                  filename="longmemeval_oracle.json",
                                  repo_type="dataset",
                                  local_dir=str(data_path.parent))
            print(f"  downloaded → {got}")
        except Exception as e:
            raise SystemExit(
                f"auto-download failed ({repr(e)[:80]}). Fetch it manually:\n"
                "  pip install huggingface_hub\n"
                "  hf download xiaowu0162/longmemeval-cleaned longmemeval_oracle.json "
                "--repo-type dataset --local-dir bench/data")

    data = json.loads(data_path.read_text())
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

    # Resume from checkpoint: every completed question is one JSONL line, so a
    # quota exhaustion / API death mid-run doesn't lose (or re-pay for) finished
    # work. --fresh starts over. The first line is a config fingerprint —
    # resuming under a different data file / judge / --no-hydra would silently
    # merge rows scored under different conditions into one results file.
    run_config = {"_config": True, "data": Path(args.data).name,
                  "judge_model": args.judge_model, "no_hydra": bool(args.no_hydra),
                  "types": args.types, "top_k": TOP_K}
    done: dict[str, dict] = {}
    if CHECKPOINT_PATH.exists():
        if args.fresh:
            CHECKPOINT_PATH.unlink()
        else:
            lines = [l for l in CHECKPOINT_PATH.read_text().splitlines() if l.strip()]
            if lines:
                head = json.loads(lines[0])
                if head.get("_config"):
                    if head != run_config:
                        raise SystemExit(
                            f"checkpoint {CHECKPOINT_PATH.name} was written under a "
                            f"different configuration:\n  checkpoint: {head}\n  "
                            f"current:    {run_config}\nRe-run with --fresh to "
                            f"discard it, or restore the original flags to resume.")
                    lines = lines[1:]
                for line in lines:
                    r = json.loads(line)
                    done[r["question_id"]] = r
            if done:
                print(f"  resuming: {len(done)} questions already scored in "
                      f"{CHECKPOINT_PATH.name} (use --fresh to rescore)")
    if not CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.write_text(json.dumps(run_config) + "\n")

    rows = []

    for i, q in enumerate(sample, 1):
        qid = q["question_id"]
        qtype = q["question_type"]
        abstain = qid.endswith("_abs")
        if qid in done:
            rows.append(done[qid])
            continue
        units = build_units(q)
        print(f"  [{i:2}/{len(sample)}] {qtype[:22]:22} ingest {len(units)} sessions…")

        b_texts, b_sids = run_baseline(q, units)
        b_rec = is_evidence(b_sids, q["answer_session_ids"])
        b_ans = generate_answer(b_texts, q["question"], args.judge_model)
        b_qa = judge(q["question"], q["answer"], b_ans, qtype, abstain, args.judge_model)

        h_rec = h_qa = False
        h_ans = ""
        if client is not None:
            try:
                h_texts, h_sids = run_hydra(client, q, units, args.hydra_wait)
                h_rec = is_evidence(h_sids, q["answer_session_ids"])
                h_ans = generate_answer(h_texts, q["question"], args.judge_model)
                h_qa = judge(q["question"], q["answer"], h_ans, qtype, abstain, args.judge_model)
            except Exception as e:
                print(f"    HydraDB error on {qid}: {repr(e)[:80]}")

        row = {"question_id": qid, "type": qtype, "abstain": abstain,
               "question": q["question"], "gold": q["answer"],
               "hydra_recall": h_rec, "base_recall": b_rec,
               "hydra_qa": h_qa, "base_qa": b_qa,
               "hydra_answer": h_ans, "base_answer": b_ans}
        rows.append(row)
        with CHECKPOINT_PATH.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"  [{i:2}/{len(sample)}] {qtype[:22]:22} "
              f"QA H={'Y' if h_qa else '.'} B={'Y' if b_qa else '.'}  "
              f"evid H={'Y' if h_rec else '.'} B={'Y' if b_rec else '.'}")

    # Aggregate from rows (fresh + checkpoint-loaded alike).
    n = len(rows)
    agg = {"h_rec": sum(r["hydra_recall"] for r in rows),
           "b_rec": sum(r["base_recall"] for r in rows),
           "h_qa": sum(r["hydra_qa"] for r in rows),
           "b_qa": sum(r["base_qa"] for r in rows)}
    per_type = defaultdict(lambda: {"n": 0, "h_qa": 0, "b_qa": 0})
    for r in rows:
        pt = per_type[r["type"]]
        pt["n"] += 1; pt["h_qa"] += r["hydra_qa"]; pt["b_qa"] += r["base_qa"]

    # Surface silently-swallowed LLM failures: an answer of "[error: ...]" was
    # scored (judged wrong) — a run with many of these is measuring API health,
    # not memory quality, and must not be quoted as a benchmark result.
    answer_errors = sum(1 for r in rows
                        for a in (r["hydra_answer"], r["base_answer"])
                        if a.startswith("[error:"))
    summary = {
        "n": n, "data": Path(args.data).name, "top_k": TOP_K,
        "judge_model": args.judge_model, "hydra_wait_timeout": args.hydra_wait,
        "baseline_chunked": True,  # 300w/50w/6000c parity with real gbrain
        "answer_errors": answer_errors,
        "base_qa_acc": agg["b_qa"] / n, "base_evidence_recall": agg["b_rec"] / n,
        "type_mix": dict(Counter(r["type"] for r in rows)),
    }
    if answer_errors:
        print(f"\n  ⚠ {answer_errors} answers were LLM-call errors scored as wrong — "
              f"treat QA accuracy with suspicion (see rows with '[error:').")
    if client is not None:
        summary.update({"hydra_qa_acc": agg["h_qa"] / n,
                        "hydra_evidence_recall": agg["h_rec"] / n})
    summary["per_type"] = {t: {"n": v["n"],
                               "hydra_qa": v["h_qa"] / v["n"],
                               "base_qa": v["b_qa"] / v["n"]} for t, v in per_type.items()}

    out = {"summary": summary, "rows": rows}
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    # Remove the checkpoint only when every checkpointed row was banked into
    # this results file — a re-run with a smaller --limit must not delete rows
    # (paid LLM work) for questions outside the current sample.
    banked = {r["question_id"] for r in rows}
    if n >= len(sample) and all(qid in banked for qid in done):
        CHECKPOINT_PATH.unlink(missing_ok=True)

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
