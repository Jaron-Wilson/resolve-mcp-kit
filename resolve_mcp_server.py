"""Standalone MCP server for DaVinci Resolve.

Run on the machine that has Resolve open (the scripting API only attaches to
a Resolve on the same computer). Configuration is by environment variable:

  RESOLVE_MCP_TRANSPORT    stdio | sse | streamable-http   (default: sse)
  RESOLVE_MCP_HOST         bind address for sse/http       (default: 127.0.0.1)
  RESOLVE_MCP_PORT         port for sse/http               (default: 8930)
  RESOLVE_MCP_TOKEN        if set, require "Authorization: Bearer <token>"
  RESOLVE_MCP_ALLOW_WRITE  1 to register editing/render tools (default: 0)
  RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB  override Resolve's scripting paths
"""

import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from resolve_mcp import edit_tools, read_tools  # noqa: E402


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def build(allow_write=None) -> FastMCP:
    if allow_write is None:
        allow_write = _truthy(os.environ.get("RESOLVE_MCP_ALLOW_WRITE"))
    mcp = FastMCP("resolve")
    read_tools.register(mcp)
    if allow_write:
        edit_tools.register(mcp)
    return mcp


class BearerAuth:
    """ASGI middleware: reject requests without the right bearer token."""

    def __init__(self, app, token):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            hdrs = dict(scope.get("headers") or [])
            got = hdrs.get(b"authorization", b"")
            if not hmac.compare_digest(got, b"Bearer " + self.token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


def main():
    transport = os.environ.get("RESOLVE_MCP_TRANSPORT", "sse").lower()
    mcp = build()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport not in ("sse", "streamable-http"):
        raise SystemExit("RESOLVE_MCP_TRANSPORT must be stdio, sse or streamable-http")
    import uvicorn
    host = os.environ.get("RESOLVE_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("RESOLVE_MCP_PORT", "8930"))
    token = os.environ.get("RESOLVE_MCP_TOKEN", "")
    mcp.settings.host, mcp.settings.port = host, port
    app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()
    if token:
        app = BearerAuth(app, token)
    elif host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening beyond localhost with no RESOLVE_MCP_TOKEN. "
              "Anyone who can reach this port can drive Resolve.", flush=True)
    path = "/sse" if transport == "sse" else "/mcp"
    write = "on" if _truthy(os.environ.get("RESOLVE_MCP_ALLOW_WRITE")) else "off"
    print(f"resolve-mcp on http://{host}:{port}{path} ({transport}, "
          f"auth={'token' if token else 'none'}, write={write})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
