"""Hard-retrieval head-to-head at scale (Option B).

Scales the categories where the v1 timeline benchmark showed HydraDB wins but at
n=2 (anecdote): NEGATION, GEOGRAPHIC FILTERING, and AGGREGATION. These are
set-membership questions with deterministic gold — no LLM judge needed — so a per-
category win here is statistical, not a coin flip.

Design: M subjects, each with a small event log — mostly events at a HOME location,
a few AWAY, and a few of a SPECIAL type. Queries are scoped per subject so gold sets
stay small (≤ k), which keeps R@5 informative:
  • negation:    "which of <subject>'s trips were NOT in <home>"   → the away events
  • geo filter:  "which of <subject>'s events were in <away-loc>"  → events there
  • aggregation: "list all of <subject>'s <type> events"          → events of a type

Metric: R@5 and P@5 over event identifiers (returned chunk → event id). Both sides
ingest identical prose; gbrain runs default balanced mode (graph + reranker on).

Multi-session SYNTHESIS (the 4th v1 category) is deliberately NOT here — it needs an
LLM judge; run `python3 -m bench.run_bench --judge` for that. This module covers only
the deterministic set-membership categories.

  python3 -m bench.hardcases [--no-hydra | --no-gbrain]

Requires GEMINI_API_KEY (→ GOOGLE_GENERATIVE_AI_API_KEY) and HYDRADB_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

M_SUBJECTS = 12
LOCATIONS = ["miami", "denver", "tokyo", "lisbon", "austin", "oslo"]
TYPES = ["conference", "wedding", "hike", "concert", "retreat"]


def subject_events(si: int) -> list[dict]:
    """Deterministic event log for subject si. Each event: id, subject, loc, type, date."""
    subj = f"subject-{si:02d}"
    home = LOCATIONS[si % len(LOCATIONS)]
    events = []
    eid = 0
    # 6 home events
    for j in range(6):
        events.append({"id": f"{subj}-e{eid:02d}", "subject": subj, "loc": home,
                       "type": TYPES[(si + j) % len(TYPES)], "date": f"2024-{(j%12)+1:02d}-05"})
        eid += 1
    # 3 away events (distinct non-home locations)
    aways = [l for l in LOCATIONS if l != home][:3]
    for j, loc in enumerate(aways):
        events.append({"id": f"{subj}-e{eid:02d}", "subject": subj, "loc": loc,
                       "type": TYPES[(si + j + 2) % len(TYPES)], "date": f"2024-{(j+7):02d}-12"})
        eid += 1
    return events


def event_body(ev: dict) -> str:
    return (f"On {ev['date']}, {ev['subject']} attended a {ev['type']} in {ev['loc']}. "
            f"It was one of {ev['subject']}'s {ev['type']} events, held in {ev['loc']}.")


def all_events() -> list[dict]:
    out = []
    for si in range(M_SUBJECTS):
        out.extend(subject_events(si))
    return out


def build_questions() -> list[dict]:
    qs = []
    for si in range(M_SUBJECTS):
        subj = f"subject-{si:02d}"
        evs = subject_events(si)
        home = LOCATIONS[si % len(LOCATIONS)]
        # negation: trips NOT in home → away events
        away = [e["id"] for e in evs if e["loc"] != home]
        if away:
            qs.append({"query": f"which of {subj}'s events were NOT in {home}",
                       "relevant": away, "cat": "negation"})
        # geo filter: events in a specific away location
        for loc in sorted({e["loc"] for e in evs if e["loc"] != home}):
            rel = [e["id"] for e in evs if e["loc"] == loc]
            qs.append({"query": f"which of {subj}'s events were in {loc}",
                       "relevant": rel, "cat": "geo_filter"})
        # aggregation: all events of a given type (pick the subject's most common type)
        by_type = defaultdict(list)
        for e in evs:
            by_type[e["type"]].append(e["id"])
        top_type = max(by_type, key=lambda t: len(by_type[t]))
        qs.append({"query": f"list all of {subj}'s {top_type} events",
                   "relevant": by_type[top_type], "cat": "aggregation"})
    return qs


def p_at_k(found, relevant, k):
    top = found[:k]
    return sum(1 for e in top if e in relevant) / k if k else 0.0


def r_at_k(found, relevant, k):
    if not relevant:
        return 0.0
    top = set(found[:k])
    return sum(1 for e in relevant if e in top) / len(relevant)


# ── gbrain driver ────────────────────────────────────────────────────
def _genv(home: Path) -> dict:
    env = dict(os.environ)
    env["GBRAIN_HOME"] = str(home)
    key = os.environ.get("GEMINI_API_KEY", "")
    try:
        from hydrabrain import config
        key = config.GEMINI_API_KEY or key
    except Exception:
        pass
    env["GOOGLE_GENERATIVE_AI_API_KEY"] = key
    env["GBRAIN_SKIP_STARTUP_HOOKS"] = "1"
    env["GBRAIN_NO_SANITY"] = "1"
    return env


def _gb(args, env, inp=None, timeout=240):
    return subprocess.run(["bun", "src/cli.ts", *args], cwd=str(REPO), env=env,
                          input=inp, capture_output=True, text=True, timeout=timeout)


def setup_gbrain(home: Path, force=False) -> dict:
    env = _genv(home)
    marker = home / ".hardcases-ready"
    if marker.exists() and not force:
        print(f"  [gbrain] reusing {home}")
        return env
    _gb(["init", "--pglite", "--embedding-model", "google:gemini-embedding-001"], env, timeout=400)
    evs = all_events()
    for e in evs:
        _gb(["put", f"events/{e['id']}"], env, inp=event_body(e), timeout=120)
    print(f"  [gbrain] put {len(evs)} event pages; embed --all")
    _gb(["embed", "--all"], env, timeout=400)
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok")
    return env


def gbrain_events(env, query, k):
    r = _gb(["call", "query", json.dumps({"query": query, "limit": k})], env, timeout=120)
    try:
        rows = json.loads(r.stdout)
    except Exception:
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        slug = (row.get("slug") or "") if isinstance(row, dict) else ""
        out.append(slug.split("/")[-1] if "/" in slug else slug)
    return out


# ── HydraDB driver ───────────────────────────────────────────────────
SRC = "hardcases_bench"
_EVENT_IDS = [e["id"] for e in all_events()]


def setup_hydra(wait=90):
    from hydrabrain.engine import BrainEngine
    eng = BrainEngine(source_id=SRC)
    if eng.client.count(sub_tenant_id=SRC) == 0:
        evs = all_events()
        for e in evs:
            eng.client.add_memory(event_body(e), title=f"events/{e['id']}", infer=True, sub_tenant_id=SRC)
            time.sleep(0.2)
        print(f"  [HydraDB] ingested {len(evs)} events; waiting {wait}s…")
        time.sleep(wait)
    else:
        print(f"  [HydraDB] reusing '{SRC}'")
    return eng


def hydra_events(eng, query, k):
    out = []
    for c in eng.search(query, k=k):
        low = c.text.lower()
        hit = next((eid for eid in _EVENT_IDS if eid in low), "")
        out.append(hit)
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbrain-home", default=str(REPO / "bench" / ".gbrain-hardcases"))
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--no-gbrain", action="store_true")
    ap.add_argument("--force-setup", action="store_true")
    ap.add_argument("--hydra-wait", type=int, default=90)
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv or [])

    need = []
    if not args.no_gbrain and not (os.environ.get("GEMINI_API_KEY") or _envkey("GEMINI_API_KEY")):
        need.append("GEMINI_API_KEY")
    if not args.no_hydra and not (os.environ.get("HYDRADB_API_KEY") or _envkey("HYDRADB_API_KEY")):
        need.append("HYDRADB_API_KEY")
    if need:
        print("ERROR: missing keys (set in .env or env): " + ", ".join(need))
        return 2

    qs = build_questions()
    cats = defaultdict(int)
    for q in qs:
        cats[q["cat"]] += 1
    print("=" * 74)
    print("  Hard-retrieval head-to-head at scale (Option B)")
    print(f"  {len(all_events())} events · {len(qs)} queries {dict(cats)} · P@{args.k} / R@{args.k}")
    print("=" * 74)

    genv = setup_gbrain(Path(args.gbrain_home), args.force_setup) if not args.no_gbrain else None
    heng = setup_hydra(args.hydra_wait) if not args.no_hydra else None
    print()

    per_cat = defaultdict(lambda: {"n": 0, "g_r": 0.0, "h_r": 0.0, "g_p": 0.0, "h_p": 0.0})
    agg = {"g_p": 0.0, "g_r": 0.0, "h_p": 0.0, "h_r": 0.0}
    rows = []
    for i, q in enumerate(qs, 1):
        g = gbrain_events(genv, q["query"], args.k) if genv else []
        h = hydra_events(heng, q["query"], args.k) if heng else []
        gp, gr = p_at_k(g, q["relevant"], args.k), r_at_k(g, q["relevant"], args.k)
        hp, hr = p_at_k(h, q["relevant"], args.k), r_at_k(h, q["relevant"], args.k)
        agg["g_p"] += gp; agg["g_r"] += gr; agg["h_p"] += hp; agg["h_r"] += hr
        c = per_cat[q["cat"]]
        c["n"] += 1; c["g_r"] += gr; c["h_r"] += hr; c["g_p"] += gp; c["h_p"] += hp
        rows.append({**q, "gbrain_p": gp, "gbrain_r": gr, "hydra_p": hp, "hydra_r": hr})
        if i % 12 == 0 or i == len(qs):
            print(f"  [{i:3}/{len(qs)}] {q['cat']:12} R g={gr:.2f} h={hr:.2f}  | {q['query'][:42]}")

    n = len(qs)
    summary = {
        "n": n, "k": args.k,
        "gbrain": {"P@k": agg["g_p"]/n, "R@k": agg["g_r"]/n},
        "hydra": {"P@k": agg["h_p"]/n, "R@k": agg["h_r"]/n},
        "per_category": {c: {"n": v["n"], "gbrain_R@k": v["g_r"]/v["n"], "hydra_R@k": v["h_r"]/v["n"],
                             "gbrain_P@k": v["g_p"]/v["n"], "hydra_P@k": v["h_p"]/v["n"]}
                         for c, v in per_cat.items()},
    }
    (REPO / "bench" / "hardcases_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("\n" + "=" * 74)
    print("  RESULTS — hard retrieval at scale")
    print("=" * 74)
    print(f"  R@{args.k}   gbrain {summary['gbrain']['R@k']*100:5.1f}%   HydraDB {summary['hydra']['R@k']*100:5.1f}%")
    print(f"  P@{args.k}   gbrain {summary['gbrain']['P@k']*100:5.1f}%   HydraDB {summary['hydra']['P@k']*100:5.1f}%")
    print(f"\n  by category (R@{args.k}):")
    for c, v in summary["per_category"].items():
        print(f"    {c:14} n={v['n']:3}  gbrain={v['gbrain_R@k']*100:5.1f}%  hydra={v['hydra_R@k']*100:5.1f}%")
    print(f"\n  saved → bench/hardcases_results.json")
    return 0


def _envkey(name):
    try:
        from hydrabrain import config
        return bool(getattr(config, name, None))
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
