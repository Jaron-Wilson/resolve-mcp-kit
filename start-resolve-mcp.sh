#!/usr/bin/env bash
# Starts the Resolve MCP server (macOS / Linux). Creates a venv on first run.
set -e
cd "$(dirname "$0")"

export RESOLVE_MCP_TRANSPORT="${RESOLVE_MCP_TRANSPORT:-sse}"
export RESOLVE_MCP_HOST="${RESOLVE_MCP_HOST:-127.0.0.1}"
export RESOLVE_MCP_PORT="${RESOLVE_MCP_PORT:-8930}"
# 1 lets the agent import media, build timelines and render.
export RESOLVE_MCP_ALLOW_WRITE="${RESOLVE_MCP_ALLOW_WRITE:-1}"
# Optional: export RESOLVE_MCP_TOKEN=pick-a-long-random-string

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python resolve_mcp_server.py
