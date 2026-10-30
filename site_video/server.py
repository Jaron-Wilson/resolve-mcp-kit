"""The queue over HTTP, with a small page to use it from a browser.

GET  /                         the page: a form and the queue
GET  /api/jobs                 every job, newest first
POST /api/jobs                 {"url", "length", "notes", "voice", "editor", "name", "model"} -> the new job
GET  /api/jobs/<id>            one job
POST /api/jobs/<id>/cancel     stop it
POST /api/jobs/<id>/retry      run a failed or cancelled job again (finished stages are kept)
GET  /api/jobs/<id>/video      the finished MP4 (supports Range, so browsers can seek)
GET  /api/jobs/<id>/log        the job's log
GET  /api/info                 voices, script models and editors this server offers

If SITE_VIDEO_TOKEN is set, every request needs "Authorization: Bearer <token>" (or ?token=<token> once in a browser,
which sets a cookie).
"""

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import pipeline
from .queue import Queue

TOKEN = os.environ.get("SITE_VIDEO_TOKEN", "")


def info() -> dict:
    voices = ["none"]
    if os.environ.get("SITE_VIDEO_TTS_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("SITE_VIDEO_TTS_URL"):
        voices.append("openai")
    if os.environ.get("ELEVENLABS_API_KEY"):
        voices.append("elevenlabs")
    if os.environ.get("SITE_VIDEO_ODYSSEUS_URL"):
        voices.append("odysseus")
    from . import llm, resolve_edit
    return {"voices": voices, "default_voice": os.environ.get("SITE_VIDEO_DEFAULT_VOICE", voices[-1]),
            "models": llm.models(), "default_model": llm.settings()["model"],
            "editors": list(pipeline.EDITORS), "resolve": resolve_edit.available(),
            "elevenlabs_voice": os.environ.get("SITE_VIDEO_ELEVENLABS_VOICE", ""),
            "openai_voice": os.environ.get("SITE_VIDEO_OPENAI_VOICE", "alloy")}


def make_handler(q: Queue):
    class H(BaseHTTPRequestHandler):
        server_version = "site-video"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(b)

        def _authed(self, qs) -> bool:
            if not TOKEN:
                return True
            got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            cookie = re.search(r"(?:^|;\s*)sv_token=([^;]+)", self.headers.get("Cookie") or "")
            for cand in (got, (qs.get("token") or [""])[0], cookie.group(1) if cookie else ""):
                if cand and hmac.compare_digest(cand, TOKEN):
                    return True
            return False

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _video(self, path):
            size = os.path.getsize(path)
            rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            start, end = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = int(rng.group(2)) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                end = min(end, size - 1)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Content-Disposition", f'inline; filename="{os.path.basename(path)}"')
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def _route(self, method):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            if not self._authed(qs):
                return self._send(401, {"error": "token required"})
            extra = {}
            if TOKEN and qs.get("token"):
                extra["Set-Cookie"] = f"sv_token={qs['token'][0]}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
            parts = [p for p in u.path.split("/") if p]
            try:
                if method == "GET" and u.path == "/":
                    from .page import PAGE
                    return self._send(200, PAGE, "text/html; charset=utf-8", extra)
                if parts[:2] != ["api", "jobs"] and u.path != "/api/info":
                    return self._send(404, {"error": "not found"})
                if u.path == "/api/info":
                    return self._send(200, info())
                if len(parts) == 2:
                    if method == "GET":
                        return self._send(200, q.list())
                    b = self._body()
                    req = pipeline.request(str(b.get("url") or "").strip(), b.get("length") or "auto",
                                           b.get("notes") or "auto", b.get("voice") or "none",
                                           b.get("editor") or "auto", "", str(b.get("name") or "")[:60],
                                           str(b.get("model") or ""))
                    return self._send(201, q.submit(req))
                jid = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._send(200, q.get(jid))
                if len(parts) == 4 and method == "POST" and parts[3] == "cancel":
                    return self._send(200, q.cancel(jid))
                if len(parts) == 4 and method == "POST" and parts[3] == "retry":
                    return self._send(200, q.retry(jid))
                if len(parts) == 4 and method in ("GET", "HEAD") and parts[3] == "video":
                    path = q.video_path(jid)
                    return self._video(path) if path else self._send(404, {"error": "no video yet"})
                if len(parts) == 4 and method == "GET" and parts[3] == "log":
                    try:
                        with open(os.path.join(q.jobs_dir, jid, "log.txt"), encoding="utf-8") as f:
                            return self._send(200, f.read()[-20000:], "text/plain; charset=utf-8")
                    except OSError:
                        return self._send(200, "", "text/plain; charset=utf-8")
                return self._send(404, {"error": "not found"})
            except KeyError:
                return self._send(404, {"error": "no such job"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})

        def do_GET(self):
            self._route("GET")

        def do_HEAD(self):
            self._route("HEAD")

        def do_POST(self):
            self._route("POST")
    return H


def serve(home: str, host: str = "127.0.0.1", port: int = 8940, parallel: int = 2) -> None:
    q = Queue(home, parallel)
    q.start()
    srv = ThreadingHTTPServer((host, port), make_handler(q))
    print(f"site-video on http://{host}:{port}  (jobs in {q.jobs_dir}, {parallel} at a time)", flush=True)
    srv.serve_forever()
