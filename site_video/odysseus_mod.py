"""site-video as an Odysseus mod (odysseus-mod.json at the repo root): a tab with the queue page, and chat tools.

Two ways to run, chosen in the mod's settings:
- remote: "Queue address" points at a site-video queue on another machine (the one with DaVinci Resolve); the page,
  its API and the tools go there.
- local:  no address; the mod runs a queue itself on a loopback port (ffmpeg edits unless Resolve is on this machine).

Every request except /health must carry the core's signed identity (X-Odysseus-User/-Ts/-Sig).
"""

import hashlib
import hmac
import http.client
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .util import read_json, write_json

MOD_ID = os.environ.get("ODYSSEUS_MOD_ID", "site-video")
TOKEN = os.environ.get("ODYSSEUS_MOD_TOKEN", "")
DATA = os.environ.get("MOD_DATA_DIR", os.path.join(os.path.expanduser("~"), "site-videos"))
SETTINGS = os.path.join(DATA, "settings.json")

TOOLS = [
    {"type": "function", "function": {
        "name": "make_site_video",
        "description": ("Make a narrated promo video of a website: it reads the site, writes a script, records the site "
                        "in a browser and edits it in DaVinci Resolve. Takes minutes; returns a job id. Use when asked "
                        "to make a video of a site or go through a website and make a video."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "The website's link"},
            "length": {"type": "string", "description": "e.g. 5min, 90s, 1:30, or auto (default)"},
            "notes": {"type": "string", "description": "What the video must do or show, in the user's words; auto if nothing"},
            "voice": {"type": "string", "description": "none, odysseus, openai[:voice], elevenlabs:<voice id>; leave out for the default"},
            "editor": {"type": "string", "enum": ["auto", "resolve", "ffmpeg"]},
            "model": {"type": "string", "description": "The model that writes the script, if the user named one; leave out for the default"},
            "deliverables": {"type": "array", "items": {"type": "string", "enum": ["video", "script", "voiceover", "clips", "timeline", "resolve_project", "package"]},
                             "description": "What to hand back besides the video, if the user asked: script, voiceover files, clips, the timeline (.drt/.fcpxml/.edl), the Resolve project (.drp), or package (all of it zipped)"}},
            "required": ["url"]}},
     "x-odysseus": {"keywords": ["video", "promo", "walkthrough"], "read_only": False}},
    {"type": "function", "function": {
        "name": "site_video_status",
        "description": "How a site video job is going (status, current step, error), or the finished video's link.",
        "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
     "x-odysseus": {"keywords": ["video"], "read_only": True}},
    {"type": "function", "function": {
        "name": "list_site_videos",
        "description": "The newest site videos: queued, in progress and finished.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
     "x-odysseus": {"keywords": ["videos"], "read_only": True}},
]


def settings():
    s = read_json(SETTINGS, {}) or {}
    return {"queue_url": str(s.get("queue_url") or "").rstrip("/"), "queue_token": str(s.get("queue_token") or "")}


class Backend:
    """Where requests go: the remote queue from the settings, or a local one started on demand."""

    def __init__(self):
        self._local = None
        self._lock = threading.Lock()

    def target(self):
        s = settings()
        if s["queue_url"]:
            return s["queue_url"], s["queue_token"]
        with self._lock:
            if not self._local:
                from .server import make_handler
                from .queue import Queue
                q = Queue(DATA, 2)
                q.start()
                srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(q))
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                self._local = f"http://127.0.0.1:{srv.server_address[1]}"
        return self._local, ""

    def call(self, method, path, body=None, headers=None):
        base, tok = self.target()
        u = urlparse(base)
        conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(
            u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=60)
        h = dict(headers or {})
        if tok:
            h["Authorization"] = "Bearer " + tok
        conn.request(method, (u.path or "") + path, body=body, headers=h)
        return conn, conn.getresponse()

    def json(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        conn, r = self.call(method, path, data, {"Content-Type": "application/json"} if data else {})
        try:
            out = json.loads(r.read() or b"{}")
        finally:
            conn.close()
        if r.status >= 400:
            raise RuntimeError(out.get("error") if isinstance(out, dict) else f"HTTP {r.status}")
        return out


BACKEND = Backend()


def _job_text(j, base):
    r = j.get("request") or {}
    line = f"Job {j['id']}: {j['status']}"
    if j["status"] in ("queued", "preparing", "waiting", "editing"):
        line += f" ({j.get('step')}, {int((j.get('progress') or 0) * 100)}%)"
    line += f". {r.get('url')}, length {r.get('length')}, voice {r.get('voice')}, script model {r.get('model') or 'default'}"
    if r.get("notes") and r["notes"] != "auto":
        line += f", notes: {r['notes'][:200]}"
    if j.get("error"):
        line += f". Error: {j['error']}"
    if j["status"] == "done":
        kinds = sorted({f.get("kind") for f in j.get("files") or []})
        line += (f". Finished: {j.get('seconds')} s, edited with {j.get('editor')}"
                 + (f"; deliverables: {', '.join(kinds)}" if kinds else "")
                 + f". Watch or download it on the Site videos tab ({base}/).")
    return line


def tool(name, args):
    base = os.environ.get("ODYSSEUS_MOD_BASE", f"/mods/{MOD_ID}")
    if name == "make_site_video":
        body = {"url": str(args.get("url") or "").strip(), "length": args.get("length") or "auto",
                "notes": args.get("notes") or "auto", "editor": args.get("editor") or "auto",
                "model": args.get("model") or "", "deliverables": args.get("deliverables") or ["video"]}
        body["voice"] = args.get("voice") or BACKEND.json("GET", "/api/info").get("default_voice", "none")
        j = BACKEND.json("POST", "/api/jobs", body)
        return {"output": _job_text(j, base) + " It takes a few minutes; check it with site_video_status.", "data": j}
    if name == "site_video_status":
        j = BACKEND.json("GET", f"/api/jobs/{args.get('job_id')}")
        return {"output": _job_text(j, base), "data": j}
    if name == "list_site_videos":
        js = BACKEND.json("GET", "/api/jobs")[: max(1, int(args.get("limit") or 8))]
        return {"output": "\n".join(_job_text(j, base) for j in js) or "No site videos yet.", "data": {"jobs": js}}
    return {"error": f"no tool {name}"}


SETTINGS_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Site videos settings</title><style>
:root{color-scheme:dark}body{margin:0;font:14px/1.5 system-ui,sans-serif;background:#14161a;color:#e7e9ec}main{max-width:640px;margin:0 auto;padding:20px 16px}
label{display:block;font-size:12px;color:#959ca5;text-transform:uppercase;letter-spacing:.05em;margin:14px 0 6px}
input{font:inherit;color:inherit;background:#191c21;border:1px solid #2c3036;border-radius:9px;padding:9px 11px;width:100%}
p{color:#959ca5}button{font:inherit;margin-top:16px;background:#4f9dff;border:0;border-radius:8px;padding:9px 18px;color:#081221;font-weight:650;cursor:pointer}
#m{margin-left:10px;color:#959ca5}</style></head><body><main><h2>Site videos</h2>
<p>Where videos are made. Leave the address empty to make them on this server (edited with ffmpeg unless DaVinci Resolve
runs here). To edit in Resolve on another computer, run <code>python -m site_video serve</code> there and give its address.</p>
<label for="u">Queue address</label><input id="u" placeholder="http://100.x.y.z:8940">
<label for="t">Queue token (if it has one)</label><input id="t" type="password" placeholder="leave empty to keep">
<button id="s">Save</button><span id="m"></span>
<script>
fetch('settings/data').then(r=>r.json()).then(d=>{document.getElementById('u').value=d.queue_url||'';document.getElementById('m').textContent=d.status||''});
document.getElementById('s').onclick=async()=>{const r=await fetch('settings/data',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({queue_url:document.getElementById('u').value.trim(),queue_token:document.getElementById('t').value})});
  const d=await r.json();document.getElementById('m').textContent=d.status||d.error||'saved'};
</script></main></body></html>"""


def _signed(h) -> bool:
    if not TOKEN:
        return True
    user, ts, sig = h.get("X-Odysseus-User", ""), h.get("X-Odysseus-Ts", ""), h.get("X-Odysseus-Sig", "")
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except ValueError:
        return False
    want = hmac.new(TOKEN.encode(), f"v1\n{MOD_ID}\n{user}\n{ts}".encode(), hashlib.sha256).hexdigest()
    return bool(user) and hmac.compare_digest(want, sig)


class Handler(BaseHTTPRequestHandler):
    server_version = "site-video-mod"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _proxy(self, method):
        body = self._body() if method == "POST" else None
        fwd = {k: v for k, v in self.headers.items() if k.lower() in ("content-type", "range", "accept")}
        try:
            conn, r = BACKEND.call(method, self.path, body, fwd)
        except (OSError, socket.timeout) as e:
            where = settings()["queue_url"] or "the local queue"
            return self._send(502, {"error": f"the video queue at {where} is not reachable ({e.__class__.__name__}). "
                                             "If it runs on a PC, is the PC on and the queue started?"})
        try:
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges",
                                 "content-disposition", "cache-control"):
                    self.send_header(k, v)
            if not r.getheader("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            conn.close()

    def _route(self, method):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True})
        if not _signed(self.headers):
            return self._send(401, {"error": "not signed by Odysseus"})
        if path == "/mod/tools" and method == "GET":
            return self._send(200, {"tools": TOOLS})
        if path.startswith("/mod/tools/") and method == "POST":
            try:
                args = json.loads(self._body() or b"{}")
                return self._send(200, tool(path.rsplit("/", 1)[1], args))
            except Exception as e:
                return self._send(200, {"error": str(e)[:500]})
        if path == "/settings" and method == "GET":
            return self._send(200, SETTINGS_PAGE, "text/html; charset=utf-8")
        if path == "/settings/data":
            if method == "POST":
                b = json.loads(self._body() or b"{}")
                s = read_json(SETTINGS, {}) or {}
                s["queue_url"] = str(b.get("queue_url") or "").strip().rstrip("/")
                if b.get("queue_token"):
                    s["queue_token"] = str(b["queue_token"])
                os.makedirs(DATA, exist_ok=True)
                write_json(SETTINGS, s)
            s = settings()
            try:
                info = BACKEND.json("GET", "/api/info")
                status = f"connected: voices {', '.join(info.get('voices', []))}; Resolve {'open' if info.get('resolve') else 'closed'}"
            except Exception as e:
                status = f"not reachable: {e}"
            return self._send(200, {"queue_url": s["queue_url"], "status": status})
        if method in ("GET", "HEAD", "POST"):
            return self._proxy("GET" if method == "HEAD" else method)
        return self._send(405, {"error": "method not allowed"})

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("HEAD")

    def do_POST(self):
        self._route("POST")


def main():
    os.makedirs(DATA, exist_ok=True)
    host, port = os.environ.get("MOD_HOST", "127.0.0.1"), int(os.environ.get("MOD_PORT", "8945"))
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"site-video mod on {host}:{port} ({settings()['queue_url'] or 'local queue'})", flush=True)
    srv.serve_forever()
