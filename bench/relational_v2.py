"""Relational head-to-head v2 — FAIR, graph-ON, at scale.

The honest fight for the "HydraDB vs gbrain" relational claim. Three things this
fixes versus bench/relational.py:

  1. gbrain's graph is actually BUILT.  gbrain extracts typed edges from prose via a
     separate `extract links --ner` pass (deterministic schema-pack regex, no LLM) —
     `put` alone only wires [[wikilinks]]/frontmatter. The v1 harness skipped it, so
     real gbrain queried an EMPTY graph. Here we run extract --ner and then ASSERT the
     typed-edge count is > 0 before we let gbrain be scored. No edges ⇒ no number.

  2. Scale.  ~50 entities, 200+ queries spanning 1-hop and 2-hop, vs v1's 8 companies
     / 38 queries — so a per-category win is statistical, not anecdote.

  3. Both sides build their graph their OWN documented way, from the SAME prose:
     HydraDB via infer=True, gbrain via extract --ner over the gbrain-base schema pack
     (which ships invested_in / works_at / founded / advises regexes). A win here is
     attributable to "HydraDB vs gbrain with its graph genuinely ON."

Metrics: P@5 and R@5 (gbrain's own pair) + MRR, broken down by hop depth.

  python3 -m bench.relational_v2                 # full head-to-head
  python3 -m bench.relational_v2 --no-hydra      # gbrain side only
  python3 -m bench.relational_v2 --no-gbrain     # HydraDB side only
  python3 -m bench.relational_v2 --report        # also write bench/relational_v2_report.html

Requires GEMINI_API_KEY (→ GOOGLE_GENERATIVE_AI_API_KEY for gbrain embeddings) and
HYDRADB_API_KEY. gbrain runs via `bun src/cli.ts`.
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


# ════════════════════════════════════════════════════════════════════
#  CORPUS — a deterministic synthetic VC/startup network (~50 entities)
#  Built programmatically so every gold answer is correct by construction.
#  Phrasing matches gbrain-base's inference regexes AND is plain-prose enough
#  for HydraDB's infer=True — neither side gets a lexical gift the other lacks.
# ════════════════════════════════════════════════════════════════════

N_COMPANIES = 16
N_PEOPLE = 30
N_FUNDS = 4

COMPANIES = [f"company-{i:02d}" for i in range(N_COMPANIES)]
PEOPLE = [f"person-{i:02d}" for i in range(N_PEOPLE)]
FUNDS = [f"fund-{chr(ord('a') + i)}" for i in range(N_FUNDS)]
INVESTORS = PEOPLE + FUNDS  # funds and angels both invest


def _build_network():
    """Deterministic edge assignment via modular arithmetic (no RNG → reproducible)."""
    INVESTMENTS: dict[str, list[str]] = {c: [] for c in COMPANIES}
    EMPLOYMENT: dict[str, list[str]] = {c: [] for c in COMPANIES}
    FOUNDED: dict[str, list[str]] = {c: [] for c in COMPANIES}
    ADVISES: dict[str, list[str]] = {c: [] for c in COMPANIES}

    for ci, c in enumerate(COMPANIES):
        # 1 founder (a person), spread across the people pool
        founder = PEOPLE[(ci * 7) % N_PEOPLE]
        FOUNDED[c].append(founder)
        # 2-3 employees (people), distinct from founder
        for j in range(2 + (ci % 2)):
            emp = PEOPLE[(ci * 3 + j * 5 + 1) % N_PEOPLE]
            if emp != founder and emp not in EMPLOYMENT[c]:
                EMPLOYMENT[c].append(emp)
        # 2-3 investors: mix of funds and angels
        for j in range(2 + (ci % 2)):
            inv = INVESTORS[(ci * 5 + j * 11) % len(INVESTORS)]
            if inv not in INVESTMENTS[c]:
                INVESTMENTS[c].append(inv)
        # ~half the companies have 1 advisor (a person)
        if ci % 2 == 0:
            adv = PEOPLE[(ci * 13 + 2) % N_PEOPLE]
            ADVISES[c].append(adv)

    return INVESTMENTS, EMPLOYMENT, FOUNDED, ADVISES


INVESTMENTS, EMPLOYMENT, FOUNDED, ADVISES = _build_network()
RELMAPS = [(INVESTMENTS, "invested in", "invested_in"),
           (EMPLOYMENT, "works at", "works_at"),
           (FOUNDED, "founded", "founded"),
           (ADVISES, "advises", "advises")]


def _sentences_for(entity: str) -> list[str]:
    """Prose sentences stating this entity's outgoing relationships."""
    s = []
    for mp, verb, _ in RELMAPS:
        targets = [c for c, members in mp.items() if entity in members]
        if targets:
            s.append(f"{entity} {verb} {', '.join(targets)}.")
    return s


def entity_body(entity: str) -> str:
    """One relationship per paragraph, well-separated, so gbrain's NER context
    window doesn't bleed a neighbouring verb onto the wrong entity mention. Both
    systems read the SAME prose; this just removes an adversarial packing artifact."""
    rels = _sentences_for(entity)
    if entity in FUNDS:
        head = f"{entity} is an early-stage venture fund that writes first checks."
    elif entity in PEOPLE:
        head = f"{entity} is an operator and angel investor in the startup network."
    else:
        head = f"{entity} is a privately held company operating in its sector."
    # blank lines between each relationship clause → clean per-mention windows
    body = head
    for s in rels:
        body += "\n\n" + s
    if not rels:
        body += "\n\nBackground details are otherwise sparse."
    return body


def company_body(c: str) -> str:
    return f"{c} is a privately held company operating in its sector. Founded some years ago; details are sparse."


# ── queries with correct-by-construction gold + hop depth ────────────
def _related(c: str) -> set[str]:
    out: set[str] = set()
    for mp, _, _ in RELMAPS:
        out |= set(mp.get(c, []))
    return out


def build_questions() -> list[dict]:
    qs: list[dict] = []
    # 1-hop: direct relation lookups
    for mp, verb, rel in RELMAPS:
        for company, members in mp.items():
            if members:
                qs.append({"query": f"who {verb} {company}", "relevant": list(members),
                           "rel": rel, "hop": 1})
    # 2-hop: what connects two companies (shared related entity)
    for i in range(len(COMPANIES)):
        for j in range(i + 1, len(COMPANIES)):
            a, b = COMPANIES[i], COMPANIES[j]
            shared = sorted(_related(a) & _related(b))
            if shared:
                qs.append({"query": f"what connects {a} and {b}", "relevant": shared,
                           "rel": "connects", "hop": 2})
    # 2-hop: what else did the founder of X invest in
    for c, founders in FOUNDED.items():
        for f in founders:
            also = sorted([co for co, members in INVESTMENTS.items() if f in members])
            if also:
                qs.append({"query": f"what companies did the founder of {c} invest in",
                           "relevant": also, "rel": "founder_invest", "hop": 2})
    return qs


# ── metrics ──────────────────────────────────────────────────────────
def p_at_k(found: list[str], relevant: list[str], k: int) -> float:
    top = found[:k]
    return sum(1 for e in top if e in relevant) / k if k else 0.0


def r_at_k(found: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(found[:k])
    return sum(1 for e in relevant if e in top) / len(relevant)


def mrr(found: list[str], relevant: list[str]) -> float:
    for i, e in enumerate(found, 1):
        if e in relevant:
            return 1.0 / i
    return 0.0


# ════════════════════════════════════════════════════════════════════
#  gbrain driver — FAIR graph-ON setup with an edge-count gate
# ════════════════════════════════════════════════════════════════════
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


TYPED = ("invested_in", "works_at", "founded", "advises")


def _expected_edges(entity: str) -> set[tuple[str, str]]:
    """Ground-truth (target_company, link_type) pairs for this entity."""
    out: set[tuple[str, str]] = set()
    for mp, _, rel in RELMAPS:
        for company, members in mp.items():
            if entity in members:
                out.add((company, rel))
    return out


def _count_typed_edges(env: dict) -> tuple[int, int, int]:
    """Verify gbrain built typed edges AND that they're the RIGHT type. Returns
    (total_typed, correct_typed, expected_total) over a sample of seed entities.
    A mis-typed edge (works_at labelled founded) counts toward total but NOT correct."""
    total = correct = expected = 0
    sample = PEOPLE[:10] + FUNDS
    for ent in sample:
        exp = _expected_edges(ent)
        expected += len(exp)
        r = _gb(["call", "get_links", json.dumps({"slug": f"people/{ent}"})], env, timeout=60)
        try:
            rows = json.loads(r.stdout)
        except Exception:
            continue
        if isinstance(rows, dict):
            rows = rows.get("links") or rows.get("rows") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            lt = row.get("link_type")
            to = (row.get("to_slug") or row.get("to_page") or "")
            comp = to.split("/")[-1] if "/" in to else to
            if lt in TYPED:
                total += 1
                if (comp, lt) in exp:
                    correct += 1
    return total, correct, expected


def _seed_gold_edges(env: dict) -> int:
    """Seed gbrain's typed-edge graph DIRECTLY from ground truth via the add_link op
    (member → company), exactly as gbrain's own published relational fixture does
    (engine.addLink(..., 'manual')). This gives gbrain a PERFECT graph — no NER, no
    handicap — so a HydraDB win here can't be blamed on gbrain's extraction."""
    n = 0
    for mp, _, rel in RELMAPS:
        for company, members in mp.items():
            for m in members:
                payload = {"from": f"people/{m}", "to": f"companies/{company}", "link_type": rel}
                _gb(["call", "add_link", json.dumps(payload)], env, timeout=60)
                n += 1
    return n


def setup_gbrain(home: Path, force: bool = False, seed_edges: bool = False) -> tuple[dict, tuple[int, int, int]]:
    env = _genv(home)
    marker = home / ".relv2-ready"
    if marker.exists() and not force:
        print(f"  [gbrain] reusing prepared brain at {home}")
        return env, _count_typed_edges(env)
    print(f"  [gbrain] init PGLite + Gemini embeddings at {home}")
    _gb(["init", "--pglite", "--embedding-model", "google:gemini-embedding-001"], env, timeout=400)
    # gbrain-base-v2 (default) has NO link_types[].inference.regex → NER builds 0 edges.
    # Activate gbrain-base (v1), which ships invested_in/works_at/founded/advises regexes.
    print("  [gbrain] schema use gbrain-base  (v1 pack has NER inference regexes)")
    _gb(["schema", "use", "gbrain-base"], env, timeout=60)
    print(f"  [gbrain] put {len(PEOPLE)+len(FUNDS)+len(COMPANIES)} entity pages (prose)")
    for p in PEOPLE:
        _gb(["put", f"people/{p}"], env, inp=entity_body(p), timeout=120)
    for f in FUNDS:
        _gb(["put", f"people/{f}"], env, inp=entity_body(f), timeout=120)
    for c in COMPANIES:
        _gb(["put", f"companies/{c}"], env, inp=company_body(c), timeout=120)
    if seed_edges:
        # ── CORRECT-EDGES MODE: hand gbrain a perfect graph (its published method) ──
        print("  [gbrain] seeding gold edges via add_link (perfect graph, no NER handicap)")
        seeded = _seed_gold_edges(env)
        print(f"           seeded {seeded} ground-truth edges")
    else:
        # ── NER MODE: build typed edges from prose via gbrain's own NER pass ──
        print("  [gbrain] extract links --ner --source db  (build typed edges from prose)")
        r = _gb(["extract", "links", "--ner", "--source", "db"], env, timeout=400)
        for line in (r.stdout + r.stderr).strip().splitlines()[-3:]:
            print(f"           {line}")
    print("  [gbrain] embed --all")
    _gb(["embed", "--all"], env, timeout=400)
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok")
    return env, _count_typed_edges(env)


def gbrain_entities(env, query, k):
    # relational=true forces gbrain's typed-edge graph arm to engage — without it the
    # query is vector/BM25-dominant and graph-only answers (e.g. a non-lexical investor)
    # are missed, UNDER-measuring gbrain. Give it its best relational shot.
    r = _gb(["call", "query", json.dumps({"query": query, "limit": k, "relational": True})], env, timeout=120)
    try:
        rows = json.loads(r.stdout)
    except Exception:
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        slug = (row.get("slug") or "") if isinstance(row, dict) else ""
        out.append(slug.split("/")[-1] if "/" in slug else slug)
    return out


# ════════════════════════════════════════════════════════════════════
#  HydraDB driver
# ════════════════════════════════════════════════════════════════════
REL_SOURCE = "relbench_v2"
ALL_ENTITIES = PEOPLE + FUNDS + COMPANIES


def setup_hydra(wait: int = 90):
    from hydrabrain.engine import BrainEngine
    eng = BrainEngine(source_id=REL_SOURCE)
    if eng.client.count(sub_tenant_id=REL_SOURCE) == 0:
        print(f"  [HydraDB] ingest {len(ALL_ENTITIES)} entity pages into '{REL_SOURCE}' (infer=True)")
        for p in PEOPLE + FUNDS:
            eng.client.add_memory(entity_body(p), title=f"people/{p}", infer=True, sub_tenant_id=REL_SOURCE)
            time.sleep(0.25)
        for c in COMPANIES:
            eng.client.add_memory(company_body(c), title=f"companies/{c}", infer=True, sub_tenant_id=REL_SOURCE)
            time.sleep(0.25)
        print(f"  [HydraDB] waiting {wait}s for graph wiring…")
        time.sleep(wait)
    else:
        print(f"  [HydraDB] reusing existing '{REL_SOURCE}' namespace")
    return eng


def hydra_entities(eng, query, k):
    chunks = eng.search(query, k=k)
    out = []
    for c in chunks:
        low = c.text.lower()
        hit = (next((e for e in ALL_ENTITIES if e in low), ""))
        out.append(hit)
    return out


# ════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════
def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbrain-home", default="")
    ap.add_argument("--no-hydra", action="store_true")
    ap.add_argument("--no-gbrain", action="store_true")
    ap.add_argument("--force-setup", action="store_true", help="rebuild gbrain brain from scratch")
    ap.add_argument("--seed-edges", action="store_true",
                    help="hand gbrain a PERFECT graph via add_link (its published method) — "
                         "rebuttal-proof: a HydraDB win can't be blamed on gbrain's NER")
    ap.add_argument("--hydra-wait", type=int, default=90)
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv or [])
    # distinct brain dir per mode so NER vs seeded runs never reuse each other's graph
    if not args.gbrain_home:
        args.gbrain_home = str(REPO / "bench" / (".gbrain-relv2-seeded" if args.seed_edges else ".gbrain-relv2"))

    # preflight: keys (gbrain embeddings + HydraDB both need them)
    need_keys = []
    if not args.no_gbrain and not (os.environ.get("GEMINI_API_KEY") or _has_env_key("GEMINI_API_KEY")):
        need_keys.append("GEMINI_API_KEY (gbrain embeddings)")
    if not args.no_hydra and not (os.environ.get("HYDRADB_API_KEY") or _has_env_key("HYDRADB_API_KEY")):
        need_keys.append("HYDRADB_API_KEY (HydraDB API)")
    if need_keys:
        print("ERROR: missing required keys — set them in .env or the environment:")
        for k in need_keys:
            print(f"  - {k}")
        return 2

    qs = build_questions()
    hop_counts = defaultdict(int)
    for q in qs:
        hop_counts[q["hop"]] += 1
    print("=" * 74)
    mode = "CORRECT-EDGES (gbrain perfect graph)" if args.seed_edges else "NER (gbrain self-wires from prose)"
    print(f"  Relational head-to-head v2 — FAIR graph-ON, at scale · mode: {mode}")
    print(f"  {len(ALL_ENTITIES)} entities · {len(qs)} queries "
          f"(1-hop={hop_counts[1]}, 2-hop={hop_counts[2]}) · P@{args.k} / R@{args.k} / MRR")
    print("=" * 74)

    genv = None
    g_edges = (0, 0, 0)
    if not args.no_gbrain:
        genv, g_edges = setup_gbrain(Path(args.gbrain_home), force=args.force_setup, seed_edges=args.seed_edges)
        total, correct, expected = g_edges
        acc = (correct / total * 100) if total else 0.0
        cov = (correct / expected * 100) if expected else 0.0
        print(f"  [gbrain] typed edges (sampled): {total} built, {correct} correct-type "
              f"(type-accuracy {acc:.0f}%, gold coverage {cov:.0f}% of {expected})")
        if total == 0:
            print("\n  ✗ INTEGRITY GATE FAILED: gbrain built ZERO typed edges from the prose.")
            print("    Its relational arm would walk an empty graph — scoring it now would")
            print("    repeat the graph-OFF overclaim. Aborting. Check the active schema pack.")
            return 3
        if cov < 50.0:
            print(f"\n  ⚠ WARNING: gbrain's NER recovered only {cov:.0f}% of gold edges with the")
            print("    correct type. The number below understates gbrain (extraction noise, not")
            print("    retrieval). Reported, but flagged — do NOT headline a win off this alone.")
        print()

    heng = setup_hydra(args.hydra_wait) if not args.no_hydra else None
    if heng:
        print()

    agg = {"g_p": 0.0, "g_r": 0.0, "g_m": 0.0, "h_p": 0.0, "h_r": 0.0, "h_m": 0.0}
    per_hop = defaultdict(lambda: {"n": 0, "g_r": 0.0, "h_r": 0.0, "g_p": 0.0, "h_p": 0.0})
    rows = []
    for i, q in enumerate(qs, 1):
        g = gbrain_entities(genv, q["query"], args.k) if genv else []
        h = hydra_entities(heng, q["query"], args.k) if heng else []
        gp, gr, gm = p_at_k(g, q["relevant"], args.k), r_at_k(g, q["relevant"], args.k), mrr(g, q["relevant"])
        hp, hr, hm = p_at_k(h, q["relevant"], args.k), r_at_k(h, q["relevant"], args.k), mrr(h, q["relevant"])
        for key, val in (("g_p", gp), ("g_r", gr), ("g_m", gm), ("h_p", hp), ("h_r", hr), ("h_m", hm)):
            agg[key] += val
        c = per_hop[q["hop"]]
        c["n"] += 1; c["g_r"] += gr; c["h_r"] += hr; c["g_p"] += gp; c["h_p"] += hp
        rows.append({**q, "gbrain_p": gp, "gbrain_r": gr, "hydra_p": hp, "hydra_r": hr})
        if i % 20 == 0 or i == len(qs):
            print(f"  [{i:3}/{len(qs)}] {q['rel']:14} hop={q['hop']} "
                  f"P g={gp:.2f} h={hp:.2f}  R g={gr:.2f} h={hr:.2f}")

    n = len(qs)
    summary = {
        "n": n, "k": args.k,
        "gbrain_edges_sampled": {"built": g_edges[0], "correct_type": g_edges[1], "gold_expected": g_edges[2]},
        "gbrain": {"P@k": agg["g_p"]/n, "R@k": agg["g_r"]/n, "MRR": agg["g_m"]/n},
        "hydra": {"P@k": agg["h_p"]/n, "R@k": agg["h_r"]/n, "MRR": agg["h_m"]/n},
        "per_hop": {h: {"n": v["n"], "gbrain_R@k": v["g_r"]/v["n"], "hydra_R@k": v["h_r"]/v["n"],
                        "gbrain_P@k": v["g_p"]/v["n"], "hydra_P@k": v["h_p"]/v["n"]}
                    for h, v in sorted(per_hop.items())},
    }
    summary["mode"] = "correct_edges" if args.seed_edges else "ner"
    out = {"summary": summary, "rows": rows}
    fname = "relational_v2_seeded_results.json" if args.seed_edges else "relational_v2_results.json"
    (REPO / "bench" / fname).write_text(json.dumps(out, indent=2))

    print("\n" + "=" * 74)
    print("  RESULTS — relational v2 (real gbrain, graph ON) vs HydraDB")
    print("=" * 74)
    print(f"  P@{args.k}   gbrain {summary['gbrain']['P@k']*100:5.1f}%   HydraDB {summary['hydra']['P@k']*100:5.1f}%")
    print(f"  R@{args.k}   gbrain {summary['gbrain']['R@k']*100:5.1f}%   HydraDB {summary['hydra']['R@k']*100:5.1f}%")
    print(f"  MRR    gbrain {summary['gbrain']['MRR']:.3f}   HydraDB {summary['hydra']['MRR']:.3f}")
    print(f"\n  by hop depth (R@{args.k}):")
    for h, v in summary["per_hop"].items():
        print(f"    {h}-hop  n={v['n']:3}  gbrain={v['gbrain_R@k']*100:5.1f}%  hydra={v['hydra_R@k']*100:5.1f}%")
    print(f"\n  saved → bench/{fname}")
    return 0


def _has_env_key(name: str) -> bool:
    try:
        from hydrabrain import config
        return bool(getattr(config, name, None))
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
