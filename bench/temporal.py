"""Knowledge-update / temporal-contradiction head-to-head (Option C).

The regime where flat retrieval genuinely breaks: a fact about an entity CHANGES
over time across several dated notes, and the question asks for the CURRENT value.
A system that just returns the most semantically-similar chunks will surface all
stale values; a temporal/graph-aware store should put the latest fact on top.

Each person changes role+company K times over dated "sessions" (rich prose). The
latest dated note is ground truth. Both sides ingest the SAME prose; gbrain gets a
fair graph-ON setup (extract links --ner + extract timeline) with an integrity gate.

Metric (deterministic, no LLM judge):
  • current@1   — among the queried person's returned chunks, is the highest-ranked
                  one the LATEST value? (the fact the answer should reflect)
  • stale-rate  — fraction of that person's top-k chunks stating a SUPERSEDED value
A temporal-aware system maximizes current@1 and minimizes stale-rate.

  python3 -m bench.temporal                 # full head-to-head
  python3 -m bench.temporal --no-hydra       # gbrain only
  python3 -m bench.temporal --no-gbrain      # HydraDB only

Requires GEMINI_API_KEY (→ GOOGLE_GENERATIVE_AI_API_KEY) and HYDRADB_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

N_PEOPLE = 24
UPDATES = 4  # role changes per person → 4 dated notes each

ROLES = ["engineer", "senior engineer", "staff engineer", "engineering manager",
         "director", "vp engineering", "cto", "founder"]
ORGS = [f"company-{i:02d}" for i in range(12)]
# deterministic dates, oldest → newest; the LAST is "current"
DATES = ["2022-01-15", "2023-03-10", "2024-06-22", "2025-09-05"]

PEOPLE = [f"person-{i:02d}" for i in range(N_PEOPLE)]


def _history(pi: int) -> list[tuple[str, str, str]]:
    """(date, role, org) tuples oldest→newest for person pi — deterministic."""
    hist = []
    for u in range(UPDATES):
        role = ROLES[(pi + u * 2) % len(ROLES)]
        org = ORGS[(pi * 3 + u) % len(ORGS)]
        hist.append((DATES[u], role, org))
    return hist


def person_notes(pi: int) -> list[tuple[str, str]]:
    """One dated note per update. Returns (slug_suffix, body)."""
    p = PEOPLE[pi]
    notes = []
    for u, (date, role, org) in enumerate(_history(pi)):
        verb = "joined" if u == 0 else "became"
        body = (f"On {date}, {p} {verb} {role} at {org}. "
                f"As of {date}, {p}'s role is {role} and {p} works at {org}.")
        notes.append((f"{date}", body))
    return notes


def current_value(pi: int) -> tuple[str, str]:
    h = _history(pi)
    return h[-1][1], h[-1][2]  # (role, org) — newest


def superseded_values(pi: int) -> list[tuple[str, str]]:
    h = _history(pi)
    return [(r, o) for (_, r, o) in h[:-1]]


def build_questions() -> list[dict]:
    qs = []
    for pi, p in enumerate(PEOPLE):
        role, org = current_value(pi)
        qs.append({"person": p, "pi": pi, "query": f"what is {p}'s current role",
                   "current": role, "kind": "role"})
        qs.append({"person": p, "pi": pi, "query": f"where does {p} work now",
                   "current": org, "kind": "org"})
    return qs


def _value_in_chunk(text: str, pi: int) -> str | None:
    """Classify which dated value a returned chunk states: 'current', 'stale', or None.

    Classify by DATE, not role/org strings — roles share substrings ("engineer" ⊂
    "senior engineer"), but each update's date is unique and unambiguous. The newest
    date is the current truth; any older date is a superseded value."""
    low = text.lower()
    if PEOPLE[pi] not in low:
        return None
    hist = _history(pi)          # oldest → newest
    newest_date = hist[-1][0]
    if newest_date in low:
        return "current"
    if any(date in low for (date, _, _) in hist[:-1]):
        return "stale"
    return None


# ── gbrain driver (fair graph-ON + timeline) ─────────────────────────
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
    marker = home / ".temporal-ready"
    if marker.exists() and not force:
        print(f"  [gbrain] reusing prepared brain at {home}")
        return env
    print(f"  [gbrain] init PGLite + Gemini embeddings")
    _gb(["init", "--pglite", "--embedding-model", "google:gemini-embedding-001"], env, timeout=400)
    total = 0
    for pi, p in enumerate(PEOPLE):
        for suffix, body in person_notes(pi):
            _gb(["put", f"sessions/{p}/{suffix}"], env, inp=body, timeout=120)
            total += 1
    print(f"  [gbrain] put {total} dated notes")
    print("  [gbrain] extract links --ner + extract timeline (fair temporal setup)")
    _gb(["extract", "links", "--ner", "--source", "db"], env, timeout=400)
    _gb(["extract", "timeline", "--source", "db"], env, timeout=400)
    print("  [gbrain] embed --all")
    _gb(["embed", "--all"], env, timeout=400)
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok")
    return env


def gbrain_chunks(env, query, k):
    r = _gb(["call", "query", json.dumps({"query": query, "limit": k})], env, timeout=120)
    try:
        rows = json.loads(r.stdout)
    except Exception:
        return []
    return [(row.get("chunk_text") or row.get("title") or "") for row in rows
            if isinstance(row, dict)] if isinstance(rows, list) else []


# ── HydraDB driver ───────────────────────────────────────────────────
SRC = "temporal_bench"


def setup_hydra(wait=90):
    from hydrabrain.engine import BrainEngine
    eng = BrainEngine(source_id=SRC)
    if eng.client.count(sub_tenant_id=SRC) == 0:
        n = 0
        for pi, p in enumerate(PEOPLE):
            for suffix, body in person_notes(pi):
                eng.client.add_memory(body, title=f"sessions/{p}/{suffix}", infer=True, sub_tenant_id=SRC)
                n += 1
                time.sleep(0.2)
        print(f"  [HydraDB] ingested {n} dated notes; waiting {wait}s for wiring…")
        time.sleep(wait)
    else:
        print(f"  [HydraDB] reusing '{SRC}'")
    return eng


def hydra_chunks(eng, query, k):
    return [c.text for c in eng.search(query, k=k)]


# ── scoring ──────────────────────────────────────────────────────────
def score(chunks: list[str], pi: int) -> tuple[float, float]:
    """current@1 (is the first person-relevant chunk the current value?), stale-rate."""
    labels = [_value_in_chunk(t, pi) for t in chunks]
    rel = [l for l in labels if l is not None]
    if not rel:
        return 0.0, 0.0
    current_at_1 = 1.0 if rel[0] == "current" else 0.0
    stale_rate = sum(1 for l in rel if l == "stale") / len(rel)
    return current_at_1, stale_rate


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbrain-home", default=str(REPO / "bench" / ".gbrain-temporal"))
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
    print("=" * 74)
    print("  Temporal / knowledge-update head-to-head (Option C)")
    print(f"  {len(PEOPLE)} people × {UPDATES} dated updates · {len(qs)} 'current value' queries")
    print("=" * 74)

    genv = setup_gbrain(Path(args.gbrain_home), args.force_setup) if not args.no_gbrain else None
    heng = setup_hydra(args.hydra_wait) if not args.no_hydra else None
    print()

    agg = {"g_c1": 0.0, "g_st": 0.0, "h_c1": 0.0, "h_st": 0.0}
    rows = []
    for i, q in enumerate(qs, 1):
        gc = gbrain_chunks(genv, q["query"], args.k) if genv else []
        hc = hydra_chunks(heng, q["query"], args.k) if heng else []
        gc1, gst = score(gc, q["pi"])
        hc1, hst = score(hc, q["pi"])
        agg["g_c1"] += gc1; agg["g_st"] += gst; agg["h_c1"] += hc1; agg["h_st"] += hst
        rows.append({**{kk: q[kk] for kk in ("person", "query", "kind", "current")},
                     "gbrain_current@1": gc1, "gbrain_stale_rate": gst,
                     "hydra_current@1": hc1, "hydra_stale_rate": hst})
        if i % 12 == 0 or i == len(qs):
            print(f"  [{i:3}/{len(qs)}] current@1 g={gc1:.0f} h={hc1:.0f}  | {q['query']}")

    n = len(qs)
    summary = {
        "n": n, "k": args.k, "updates_per_person": UPDATES,
        "gbrain": {"current@1": agg["g_c1"]/n, "stale_rate": agg["g_st"]/n},
        "hydra": {"current@1": agg["h_c1"]/n, "stale_rate": agg["h_st"]/n},
    }
    (REPO / "bench" / "temporal_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    print("\n" + "=" * 74)
    print("  RESULTS — knowledge-update (higher current@1 / lower stale-rate is better)")
    print("=" * 74)
    print(f"  current@1   gbrain {summary['gbrain']['current@1']*100:5.1f}%   HydraDB {summary['hydra']['current@1']*100:5.1f}%")
    print(f"  stale-rate  gbrain {summary['gbrain']['stale_rate']*100:5.1f}%   HydraDB {summary['hydra']['stale_rate']*100:5.1f}%")
    print(f"\n  saved → bench/temporal_results.json")
    return 0


def _envkey(name):
    try:
        from hydrabrain import config
        return bool(getattr(config, name, None))
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
