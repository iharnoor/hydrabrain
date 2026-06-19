"""Relational head-to-head — mirrors gbrain's PUBLISHED claim, fairly.

gbrain's headline: a self-wiring typed-edge graph answering "who works at X?",
"who invested in Y?" — benchmarked P@5 49.1 / R@5 97.9 on a 240-page *rich-prose*
corpus. Their internal unit fixture (test/fixtures/.../relational) seeds edges
EXPLICITLY with lexically-invisible bodies — that isolates gbrain's edge arm but is
unfair to any system that infers edges from text (HydraDB's `infer=True`), which
would score ~0 for lack of any relationship in the prose.

So this mirrors the *published* setup instead: the SAME entity graph (reused from
gbrain's fixture for principled gold answers), but **rich-prose bodies that STATE the
relationships**, so BOTH systems extract them their own way. Reports P@5 AND R@5 —
gbrain's own metrics — per relation type.

  python3 -m bench.relational --no-hydra        # gbrain side only (HydraDB pending)
  python3 -m bench.relational                    # full head-to-head
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── entity graph (reused from gbrain's fixture; member → company edges) ──
INVESTMENTS = {
    "widget-co": ["alice", "bob", "fund-a"], "acme-co": ["carol", "alice", "fund-b"],
    "novapay": ["bob", "fund-a"], "mindbridge": ["dave", "carol"],
    "helio": ["erin", "fund-b"], "quanta": ["frank", "alice"],
    "zenith": ["grace", "heidi"], "orbital": ["ivan", "alice"],
}
EMPLOYMENT = {
    "widget-co": ["erin", "grace"], "acme-co": ["dave", "frank"],
    "novapay": ["grace"], "helio": ["heidi"], "zenith": ["ivan"],
}
FOUNDED = {"mindbridge": ["carol"], "quanta": ["frank"], "widget-co": ["ivan"], "orbital": ["grace"]}
ADVISES = {"novapay": ["frank"], "helio": ["alice"]}

PEOPLE = sorted({p for m in (INVESTMENTS, EMPLOYMENT, FOUNDED, ADVISES) for v in m.values() for p in v})
COMPANIES = sorted(INVESTMENTS)


def _rels_for(person: str) -> list[str]:
    """Rich-prose sentences stating this person's relationships (the edges, in text)."""
    s = []
    inv = [c for c, m in INVESTMENTS.items() if person in m]
    emp = [c for c, m in EMPLOYMENT.items() if person in m]
    fnd = [c for c, m in FOUNDED.items() if person in m]
    adv = [c for c, m in ADVISES.items() if person in m]
    if inv: s.append(f"{person} invested in {', '.join(inv)}.")
    if emp: s.append(f"{person} works at {', '.join(emp)}.")
    if fnd: s.append(f"{person} founded {', '.join(fnd)}.")
    if adv: s.append(f"{person} advises {', '.join(adv)}.")
    return s


def person_body(person: str) -> str:
    rels = _rels_for(person)
    fund = "venture fund" if person.startswith("fund-") else "operator and angel investor"
    return (f"{person} is an {fund} in the startup network. "
            + " ".join(rels) + " Background details are otherwise sparse.")


def company_body(c: str) -> str:
    return f"{c} is a privately held company operating in its sector. Founded some years ago."


def build_questions() -> list[dict]:
    qs = []
    for mp, verb in [(INVESTMENTS, "invested in"), (EMPLOYMENT, "works at"),
                     (FOUNDED, "founded"), (ADVISES, "advises")]:
        rel = verb.split()[0] if verb != "works at" else "works_at"
        for company, members in mp.items():
            qs.append({"query": f"who {verb} {company}", "relevant": list(members), "rel": rel})
    # multi-hop: what connects two companies (shared related entity)
    def related(c):
        s = set()
        for mp in (INVESTMENTS, EMPLOYMENT, FOUNDED, ADVISES):
            s |= set(mp.get(c, []))
        return s
    for i in range(len(COMPANIES)):
        for j in range(i + 1, len(COMPANIES)):
            a, b = COMPANIES[i], COMPANIES[j]
            shared = sorted(related(a) & related(b))
            if shared:
                qs.append({"query": f"what connects {a} and {b}", "relevant": shared, "rel": "connects"})
    return qs


# ── metrics: P@k and R@k (gbrain's own metrics) ─────────────────────
def p_at_k(found_entities: list[str], relevant: list[str], k: int) -> float:
    top = found_entities[:k]
    hit = sum(1 for e in top if e in relevant)
    return hit / k


def r_at_k(found_entities: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(found_entities[:k])
    return sum(1 for e in relevant if e in top) / len(relevant)


# ── gbrain driver ───────────────────────────────────────────────────
def _genv(home: Path) -> dict:
    import os
    from hydrabrain import config
    env = dict(os.environ)
    env["GBRAIN_HOME"] = str(home)
    env["GOOGLE_GENERATIVE_AI_API_KEY"] = config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    env["GBRAIN_SKIP_STARTUP_HOOKS"] = "1"; env["GBRAIN_NO_SANITY"] = "1"
    return env


def _gb(args, env, inp=None, timeout=180):
    return subprocess.run(["bun", "src/cli.ts", *args], cwd=str(REPO), env=env,
                          input=inp, capture_output=True, text=True, timeout=timeout)


def setup_gbrain(home: Path) -> dict:
    env = _genv(home)
    if (home / ".rel-ready").exists():
        print(f"  [gbrain] reusing {home}"); return env
    print(f"  [gbrain] init + import {len(PEOPLE)+len(COMPANIES)} entity pages")
    _gb(["init", "--pglite", "--embedding-model", "google:gemini-embedding-001"], env, timeout=400)
    for p in PEOPLE:
        _gb(["put", f"people/{p}"], env, inp=person_body(p), timeout=120)
    for c in COMPANIES:
        _gb(["put", f"companies/{c}"], env, inp=company_body(c), timeout=120)
    _gb(["embed", "--all"], env, timeout=400)
    home.mkdir(parents=True, exist_ok=True); (home / ".rel-ready").write_text("ok")
    return env


def gbrain_entities(env, query, k):
    r = _gb(["call", "query", json.dumps({"query": query, "limit": k})], env, timeout=120)
    try:
        rows = json.loads(r.stdout)
    except Exception:
        return []
    out = []
    for row in rows:
        slug = row.get("slug", "")
        out.append(slug.split("/")[-1] if "/" in slug else slug)
    return out


# ── HydraDB driver ──────────────────────────────────────────────────
REL_SOURCE = "relbench"  # isolated HydraDB namespace so this corpus can't collide with other benchmarks


def setup_hydra():
    from hydrabrain.engine import BrainEngine
    eng = BrainEngine(source_id=REL_SOURCE)  # scopes both ingest + search to this namespace
    if eng.client.count(sub_tenant_id=REL_SOURCE) == 0:
        print(f"  [HydraDB] ingesting {len(PEOPLE)+len(COMPANIES)} entity pages into '{REL_SOURCE}' (infer=True)")
        for p in PEOPLE:
            eng.client.add_memory(person_body(p), title=f"people/{p}", infer=True, sub_tenant_id=REL_SOURCE); time.sleep(0.3)
        for c in COMPANIES:
            eng.client.add_memory(company_body(c), title=f"companies/{c}", infer=True, sub_tenant_id=REL_SOURCE); time.sleep(0.3)
        print("  [HydraDB] waiting 60s for graph wiring…"); time.sleep(60)
    else:
        print(f"  [HydraDB] reusing existing '{REL_SOURCE}' namespace")
    return eng


def hydra_entities(eng, query, k):
    chunks = eng.search(query, k=k)
    out = []
    for c in chunks:
        low = c.text.lower()
        # map a returned chunk back to whichever entity name it names
        hit = next((p for p in PEOPLE if p in low), None) or next((co for co in COMPANIES if co in low), "")
        out.append(hit)
    return out


# ── main ────────────────────────────────────────────────────────────
def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbrain-home", default=str(REPO / "bench" / ".gbrain-rel"))
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--no-gbrain", action="store_true")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv or [])

    qs = build_questions()
    print("=" * 70)
    print("  Relational head-to-head — rich-prose entity corpus (mirrors gbrain's claim)")
    print(f"  {len(PEOPLE)+len(COMPANIES)} entities · {len(qs)} relational queries · P@{args.k} / R@{args.k}")
    print("=" * 70)

    genv = setup_gbrain(Path(args.gbrain_home)) if not args.no_gbrain else None
    heng = setup_hydra() if not args.no_hydra else None

    agg = {"g_p": 0.0, "g_r": 0.0, "h_p": 0.0, "h_r": 0.0}
    for i, q in enumerate(qs, 1):
        g = gbrain_entities(genv, q["query"], args.k) if genv else []
        h = hydra_entities(heng, q["query"], args.k) if heng else []
        gp, gr = p_at_k(g, q["relevant"], args.k), r_at_k(g, q["relevant"], args.k)
        hp, hr = p_at_k(h, q["relevant"], args.k), r_at_k(h, q["relevant"], args.k)
        agg["g_p"] += gp; agg["g_r"] += gr; agg["h_p"] += hp; agg["h_r"] += hr
        print(f"  [{i:2}/{len(qs)}] {q['rel']:9} P@{args.k} g={gp:.2f} h={hp:.2f}  R@{args.k} g={gr:.2f} h={hr:.2f}  | {q['query']}")

    n = len(qs)
    print("\n" + "=" * 70)
    print("  RESULTS — relational (gbrain's own metrics)")
    print("=" * 70)
    print(f"  P@{args.k}   gbrain {agg['g_p']/n*100:5.1f}%   HydraDB {agg['h_p']/n*100:5.1f}%")
    print(f"  R@{args.k}   gbrain {agg['g_r']/n*100:5.1f}%   HydraDB {agg['h_r']/n*100:5.1f}%")
    out = {"n": n, "k": args.k,
           "gbrain": {"P@k": agg["g_p"]/n, "R@k": agg["g_r"]/n},
           "hydra": {"P@k": agg["h_p"]/n, "R@k": agg["h_r"]/n}}
    (REPO / "bench" / "relational_results.json").write_text(json.dumps(out, indent=2))
    print("  saved → bench/relational_results.json")


if __name__ == "__main__":
    main(sys.argv[1:])
