#!/usr/bin/env bash
# HydraBrain one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/iharnoor/hydrabrain/master/scripts/install.sh | bash
#
# or, from inside a clone:   bash scripts/install.sh
#
# Gets you from zero to a working HydraDB-backed brain: clones (if needed),
# installs deps, runs the guided key setup (Free mode = just a HydraDB key),
# verifies connectivity, and optionally registers the MCP server with Claude.
set -euo pipefail

REPO_URL="https://github.com/iharnoor/hydrabrain.git"
say() { printf "\033[1;35m▸\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; }

# 0) Python check
command -v python3 >/dev/null 2>&1 || { err "python3 not found — install Python 3.10+ first."; exit 1; }
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
say "Python $PYV detected"

# 1) Locate (or clone) the repo, then cd into it
if [ -f "hydrabrain/cli.py" ]; then
  ROOT="$(pwd)"
elif [ -f "$(dirname "$0")/../hydrabrain/cli.py" ]; then
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
else
  say "Cloning HydraBrain…"
  command -v git >/dev/null 2>&1 || { err "git not found."; exit 1; }
  git clone --depth 1 "$REPO_URL" hydrabrain-fork
  ROOT="$(pwd)/hydrabrain-fork"
fi
cd "$ROOT"
say "Installing into $ROOT"

# 2) Dependencies
say "Installing Python dependencies…"
python3 -m pip install -q -r requirements.txt
if [ "${HYDRABRAIN_WITH_YOUTUBE:-}" = "1" ]; then
  say "Installing optional YouTube transcript support…"
  python3 -m pip install -q youtube-transcript-api || true
fi

# 3) Guided key setup (writes ~/.hydrabrain/.env). Skip if already configured.
if python3 -m hydrabrain.cli status >/dev/null 2>&1; then
  say "Keys already configured — skipping setup."
else
  say "Let's set up your keys (Free mode needs only a HydraDB key)…"
  python3 -m hydrabrain.cli init
fi

# 4) Verify connectivity
say "Verifying…"
if python3 -m hydrabrain.cli status; then
  say "HydraBrain is live."
else
  err "Setup ran but status failed — check your HydraDB key / API health, then re-run: python3 -m hydrabrain.cli status"
fi

# 5) Optional: register the MCP server with Claude
if command -v claude >/dev/null 2>&1; then
  say "Registering the MCP server with Claude…"
  claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve 2>/dev/null \
    && say "MCP registered (tool: hydrabrain)" || say "(MCP registration skipped — add later: claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve)"
fi

echo
say "Done. Next:"
echo "    python3 -m hydrabrain.cli web --open      # creator UI: add a link, chat with citations"
echo "    python3 -m hydrabrain.cli read <url>       # ingest an article / tweet / YouTube video"
echo "    python3 -m hydrabrain.cli think \"…\"        # ask your brain"
