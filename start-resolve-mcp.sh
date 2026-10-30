#!/usr/bin/env bash
# Starts the Resolve MCP server (macOS / Linux). Creates a venv and installs what it needs on first run.
#   RESOLVE_MCP_SKIP_VIDEO=1   skip the site_video packages and the Chromium download (Resolve MCP tools only)
#   RESOLVE_MCP_REINSTALL=1    install the requirements again (after updating this folder)
set -e
cd "$(dirname "$0")"

export RESOLVE_MCP_TRANSPORT="${RESOLVE_MCP_TRANSPORT:-sse}"
export RESOLVE_MCP_HOST="${RESOLVE_MCP_HOST:-127.0.0.1}"
export RESOLVE_MCP_PORT="${RESOLVE_MCP_PORT:-8930}"
# 1 lets the agent import media, build timelines and render.
export RESOLVE_MCP_ALLOW_WRITE="${RESOLVE_MCP_ALLOW_WRITE:-1}"
# Optional: export RESOLVE_MCP_TOKEN=pick-a-long-random-string

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "Python 3.10 or newer is needed. Install it, or run: PYTHON=/path/to/python3.12 ./start-resolve-mcp.sh" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating the virtual environment in .venv ..."
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.deps-ok ] || [ -n "$RESOLVE_MCP_REINSTALL" ]; then
  echo "Installing requirements ..."
  .venv/bin/python -m pip install -r requirements.txt
  if [ -z "$RESOLVE_MCP_SKIP_VIDEO" ]; then
    .venv/bin/python -m pip install -r requirements-video.txt
    echo "Downloading Chromium for site_video (about 150 MB, once) ..."
    .venv/bin/python -m playwright install chromium
  fi
  touch .venv/.deps-ok
fi
exec .venv/bin/python resolve_mcp_server.py
