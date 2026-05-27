---
name: skill-optimizer
version: 0.1.0
description: Self-evolving skill optimization via SkillOpt-paper-grounded text-space optimizer.
triggers:
  - "optimize this skill"
  - "tune the skill against the benchmark"
  - "make the skill better"
  - "run skillopt"
  - "skillopt for"
mutating: true
brain_first: exempt
---

# Skill Optimizer

Self-evolving skill optimization. Treats SKILL.md as the trainable parameters
of a frozen agent. Validation-gated, budget-capped, atomic-versioned.

Based on SkillOpt (arXiv 2605.23904, Microsoft Research, May 2026).

## When to invoke this skill

The user wants to:
- Improve an existing skill's execution quality against a benchmark
- Bootstrap a benchmark file for a new skill
- Re-tune a skill after switching target models

## Iron Law

- **Validation gating is MANDATORY.** Every candidate must clear median-of-3
  + epsilon=0.05 margin against the sel-set before SKILL.md gets rewritten.
- **Frontmatter mutation is FORBIDDEN.** The optimizer only edits the body.
  Routing surface (`triggers:`, `brain_first:`) stays invariant.
- **Bundled skills require explicit opt-in.** Skills shipping with gbrain
  cannot be auto-mutated; user passes `--allow-mutate-bundled` or
  `--no-mutate` (default for the dream-cycle phase) writes proposed.md
  for review.
- **Bootstrap output requires human review.** `--bootstrap-from-routing`
  writes a sentinel; user must hand-review + delete the sentinel +
  re-run with `--bootstrap-reviewed` before optimization can use it.

## The pipeline

```
gbrain skillopt <skill-name> [flags]
  │
  ├── Pre-flight gates
  │     ├── working tree clean (or --force)
  │     ├── benchmark valid + D_sel >= 5 (D17)
  │     ├── cost preflight (D3) — refuses over --max-cost-usd
  │     └── per-skill DB lock (D14)
  │
  ├── Baseline eval on D_sel (sets best_sel_score)
  │
  ├── for epoch in 1..N:
  │     for step in 1..steps_per_epoch:
  │       ├── forward pass: rollouts on D_train batch
  │       ├── backward pass: reflect × 2 (failures + successes per D7)
  │       ├── rank + clip via LR cosine schedule
  │       ├── apply edits (body-only per D5, tagged result per D9)
  │       ├── validation gate: median-of-3 + epsilon=0.05 (D12)
  │       └── if accept: commit via D8 history-intent-first
  │     │
  │     └── slow update (D6) if no improvement this epoch
  │
  └── Final test eval on D_test → run receipt
```

## Decision tree

| Situation | Action |
|---|---|
| New skill, no benchmark yet | `gbrain skillopt foo --bootstrap-from-routing` → review → `--bootstrap-reviewed` |
| Iterating on an existing skill | `gbrain skillopt foo --benchmark skills/foo/skillopt-benchmark.jsonl` |
| Costly run, want preview | Add `--dry-run` |
| Bundled skill (skills/ in gbrain repo) | Default writes proposed.md; add `--allow-mutate-bundled` to commit |
| Want to review changes before applying | Add `--no-mutate` |
| Mid-run crash | `gbrain skillopt foo --resume <run-id>` |

## Output Format

When invoked, this skill produces:

- Updated `skills/<name>/SKILL.md` (when mutation is allowed)
- `skills/<name>/skillopt/best.md` — pointer copy of current best
- `skills/<name>/skillopt/versions/vNNNN_eN_sN.md` — per-step snapshots
- `skills/<name>/skillopt/history.json` — append-only run record
- `skills/<name>/skillopt/rejected.json` — bounded LRU of rejected edits
- `~/.gbrain/audit/skillopt-YYYY-Www.jsonl` — ISO-week-rotated audit trail

## Anti-patterns

- **Don't bypass the validation gate.** The median-of-3 + epsilon=0.05 is
  load-bearing; without it, the optimizer accepts noise as improvement.
- **Don't optimize bundled skills without `--allow-mutate-bundled`.** They
  ship with gbrain and are load-bearing for downstream agents.
- **Don't use `--bootstrap-from-routing` output without review.** The
  optimizer model invents success criteria; a human must sanity-check
  before SkillOpt optimizes against them.

## Contract

`runSkillOpt(opts)` returns:
```
{
  outcome: 'accepted' | 'no_improvement' | 'aborted' | 'errored',
  receipt: { run_id, skill_sha8, benchmark_sha8, models, scores, cost },
  finalText: string,
  mutatedSkillFile: boolean,
  proposedPath?: string
}
```

## Related skills

- `skillify` — scaffolds a new skill (use BEFORE skillopt)
- `skillpack-check` — audits skill conformance (item 13 surfaces skillopt status)
- `conventions/quality.md` — output quality standards skillopt enforces via judges
