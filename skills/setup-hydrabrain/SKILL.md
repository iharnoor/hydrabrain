---
name: setup-hydrabrain
description: Set up HydraBrain (HydraDB v2-backed memory) for a coding agent in one line — install deps, configure keys (Free mode = HydraDB key only), verify, register MCP.
triggers:
  - "set up hydrabrain"
  - "set up hydradb"
  - "install hydrabrain"
  - "hydradb v2 setup"
  - "connect hydradb"
tools:
  - status
  - capture
  - search
  - think
  - serve
---

# Setup HydraBrain (HydraDB v2)

Get a fresh machine from zero to a working HydraDB-backed brain. The whole thing
is one line; everything below is what that line does, so you can run it manually
if a step needs attention.

## The one line

```bash
curl -fsSL https://raw.githubusercontent.com/iharnoor/hydrabrain/master/scripts/install.sh | bash
```

From inside a clone: `bash scripts/install.sh`. To include YouTube ingestion:
`HYDRABRAIN_WITH_YOUTUBE=1 bash scripts/install.sh`.

## What it does (and how to do each step by hand)

1. **Python check** — needs Python 3.10+.
2. **Clone (if needed)** + `pip install -r requirements.txt`.
3. **Key setup** — runs `python3 -m hydrabrain.cli init`:
   - **Free mode** (recommended to start): just a HydraDB key — unlocks capture, sync,
     `read <url>`, and search. Get one free at <https://hydradb.com>.
   - **Full**: add a free Gemini key (<https://aistudio.google.com/apikey>) to unlock
     synthesized, cited answers (`think` / `briefing` / `enrich`).
   - Keys are written to `~/.hydrabrain/.env` (chmod 600), never committed.
   - Prefer a browser? `python3 -m hydrabrain.cli web` serves a guided setup screen instead.
4. **Verify** — `python3 -m hydrabrain.cli status` (prints tenant + memory count).
5. **MCP register** (if the `claude` CLI is present):
   `claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve`
   exposes capture/read_url/search/think/briefing/enrich/graph/status as MCP tools.

## Verify it worked

```bash
python3 -m hydrabrain.cli status                       # tenant + memory count
python3 -m hydrabrain.cli capture "first memory: espresso 1:2 in 28s"
python3 -m hydrabrain.cli think "what coffee setup did I save?"
```

## Use it

```bash
python3 -m hydrabrain.cli web --open      # creator UI: paste a link, chat with citations
python3 -m hydrabrain.cli read <url>       # ingest an article / tweet / YouTube transcript
python3 -m hydrabrain.cli sync ~/notes     # bulk, incremental file ingest
```

## Troubleshooting

- **`status` fails with a 500 / `INTERNAL_ERROR`** → the HydraDB API/backend is unreachable.
  Check `curl -s -o /dev/null -w '%{http_code}' https://api.hydradb.com/health` (200 = server up).
  If health is 200 but data routes 500, it's a backend/datastore outage, not your key —
  rotating the key won't help.
- **"isn't set up yet"** → run `python3 -m hydrabrain.cli init` (or `web`).
- **YouTube `read` fails** → `pip install youtube-transcript-api`.
