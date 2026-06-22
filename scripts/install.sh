#!/usr/bin/env bash
# HydraBrain one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/iharnoor/hydrabrain/master/scripts/install.sh | bash
#
# or, from inside a clone:   bash scripts/install.sh
#
# Gets you from zero to a working HydraDB-backed brain: clones (if needed),
# installs deps into a local virtualenv (avoids PEP 668 / Homebrew "externally
# managed" errors), runs the guided key setup (Free mode = just a HydraDB key),
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

# 2) Virtualenv — modern macOS/Linux Python is "externally managed" (PEP 668),
#    so installing into a venv is the portable way that always works.
VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating virtualenv at .venv…"
  python3 -m venv "$VENV" || { err "could not create venv — on Debian/Ubuntu: apt install python3-venv"; exit 1; }
fi
PY="$VENV/bin/python"

# 3) Dependencies (into the venv — no PEP 668 error, no sudo, no system pollution)
say "Installing dependencies into .venv…"
"$PY" -m pip install -q --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install -q -r requirements.txt
if [ "${HYDRABRAIN_WITH_YOUTUBE:-}" = "1" ]; then
  say "Installing optional YouTube transcript support…"
  "$PY" -m pip install -q youtube-transcript-api || true
fi

# 4) Guided key setup (writes ~/.hydrabrain/.env). Skip if already configured.
if "$PY" -m hydrabrain.cli status >/dev/null 2>&1; then
  say "Keys already configured — skipping setup."
else
  say "Let's set up your keys (Free mode needs only a HydraDB key)…"
  "$PY" -m hydrabrain.cli init
fi

# 5) Verify connectivity
say "Verifying…"
if "$PY" -m hydrabrain.cli status; then
  say "HydraBrain is live."
else
  err "Setup ran but status failed — check your HydraDB key / API health, then re-run: $PY -m hydrabrain.cli status"
fi

# 6) Optional: register the MCP server with Claude (using the venv's python)
if command -v claude >/dev/null 2>&1; then
  say "Registering the MCP server with Claude…"
  claude mcp add hydrabrain -- "$PY" -m hydrabrain.cli serve 2>/dev/null \
    && say "MCP registered (tool: hydrabrain)" || say "(MCP registration skipped — add later: claude mcp add hydrabrain -- $PY -m hydrabrain.cli serve)"
fi

echo
say "Done. Activate the venv, then use HydraBrain:"
echo "    source .venv/bin/activate                  # then plain 'python3 -m hydrabrain.cli …' works"
echo "    python3 -m hydrabrain.cli web --open       # creator UI: add a link, chat with citations"
echo "    python3 -m hydrabrain.cli read <url>        # ingest an article / tweet / YouTube video"
echo
say "Or without activating, call the venv directly:"
echo "    $VENV/bin/python -m hydrabrain.cli web --open"
