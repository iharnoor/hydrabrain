---
name: hydrabrain-advisor
version: 1.0.0
description: |
  Proactive HydraBrain health coaching. Checks the brain's state via MCP tools
  and pings the user with the top high-leverage actions: unconfigured credentials,
  low memory count, stale recall config, missing ingestion, and MCP registration.
  Read-only; always asks before making changes.
triggers:
  - "what should I do to get more out of hydrabrain"
  - "is my hydrabrain set up right"
  - "hydrabrain advisor"
  - "advise me on my brain"
  - "hydrabrain checkup"
  - "weekly brain checkup"
tools:
  - status
mutating: false
---

# HydraBrain Advisor

> This skill is the proactive voice of the HydraBrain — it tells the owner
> how to get more out of it without touching anything without permission.

## Contract

- **Read-only.** This advisor only reads state; it never mutates memories.
- **Print, never execute.** Show findings to the user and ASK before running any fix.
- **Bounded nagging.** Surface only what is new or critical; don't repeat ignored low-severity items.

## When to run

- On demand: "how do I get more out of hydrabrain?"
- On a **weekly** cadence via the `cron-scheduler` skill.

## How to run it

Call the `status` MCP tool to get tenant + memory count, then evaluate the
checklist below. No separate `advisor` command exists — the advisor IS this skill.

```
status()  →  { "tenant": "...", "memories": N }
```

## Health checklist

Run through these in order, stop at the first `critical`:

| Severity | Check | Fix |
|---|---|---|
| critical | `status()` throws / returns error | Check HYDRADB_API_KEY + HYDRABRAIN_TENANT in .env |
| critical | `memories == 0` and user has been running for >1 day | Run `hydrabrain ingest <path>` or `capture "<text>"` |
| warn | `memories < 10` | Suggest ingesting more content |
| warn | MCP server not registered in the user's agent platform | Run `claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve` |
| info | `GEMINI_API_KEY` not set (think command unavailable) | Add GEMINI_API_KEY to .env |
| info | hydrabrain version behind pypi latest | Run `pip install -U hydrabrain` |

## What to do with the findings

1. Call `status()` and inspect the result.
2. Walk the health checklist above, highest severity first.
3. Summarize the top 1-3 items to the user in plain language. Lead with any `critical`.
4. Show the exact fix command for each item and **ask** before running it.
5. Never run a fix the user didn't approve.

## Output format

```
🧠 HydraBrain checkup — 2 things worth your attention

CRITICAL  Brain has 0 memories — nothing to recall yet.
          Fix: hydrabrain ingest ~/notes/   (want me to run it?)

WARN      MCP server not registered in Claude Code.
          Fix: claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve
```

- One block per finding, highest severity first.
- Always show the exact fix command and ASK before running.
- If nothing is pressing: "Brain looks healthy — N memories indexed, MCP live."

## Cron recipe (weekly checkup)

Install via the `cron-scheduler` skill, weekly Monday 09:00 local:

> `Read skills/hydrabrain-advisor/SKILL.md and call the status MCP tool.
> If anything is critical or new since last run, tell me the top items and
> the exact fix commands. Ask before fixing.`

## Anti-patterns

- **Running a fix without asking.** Always confirm, even for trivially safe commands.
- **Dumping raw JSON at the user.** Translate status into their voice.
- **Re-nagging ignored low-severity items.** Use a "new since last run" delta.
- **Treating `info` like `critical`.** Only escalate `critical` findings.
