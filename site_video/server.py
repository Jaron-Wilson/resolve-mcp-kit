"""The queue over HTTP, with a small page to use it from a browser.

GET  /                         the page: a form and the queue
GET  /api/jobs                 every job, newest first
POST /api/jobs                 {"url", "length", "notes", "voice", "editor", "name", "model", "deliverables", "media"}
                               -> the new job. A url, media, or both. media: [{"file": <path from /api/uploads>,
                               "note": "what it is / what to use"}]
POST /api/uploads?name=<file>  the raw bytes of one of your videos -> {"file": path to put in "media"}
                               (at most SITE_VIDEO_MAX_UPLOAD_MB, default 4096)
                               deliverables: a list from video, script, voiceover, clips, timeline, resolve_project,
                               package (see deliver.py); "all" for every one
GET  /api/jobs/<id>            one job
POST /api/jobs/<id>/cancel     stop it
POST /api/jobs/<id>/retry      run a failed or cancelled job again (finished stages are kept)
POST /api/jobs/<id>/remove     delete a job that is not running, and its files
GET  /api/jobs/<id>/plan       its script, what it may point at (pages, headings, buttons, your videos) and its cursor
POST /api/jobs/<id>/suggest    {"change": "in scene 3 point at the Pro plan"} -> {"plan", "changes"}: the script with
                               the change made by the script model, for review (nothing is saved)
POST /api/jobs/<id>/revise     {"plan", "cursor"} -> the job, queued again; only what changed is redone
GET  /api/jobs/<id>/video      the finished MP4 (supports Range, so browsers can seek)
GET  /api/jobs/<id>/files/<name> one of the job's deliverables (names are in job["files"])
GET  /api/jobs/<id>/log        the job's log
GET  /cursors                  the cursor looks and how they move, live
GET  /api/jobs/<id>/live.jpg   what the job's browser shows right now (while it explores or records)
POST /api/signin               {"url"} open a sign-in window on THIS computer's screen (see session.py); GET ?url= its status,
                               DELETE forgets the saved sign-in
POST /api/signin/import        {"url", "state"} save a sign-in sent by the browser extension
GET  /api/signin/extension.zip the browser extension; its config.js holds this server's own address (from the request)
GET  /api/info                 voices, script models and editors this server offers

Over HTTP a job's media must be uploads, or files inside the folders in SITE_VIDEO_MEDIA_DIRS (separated by the
system's path separator), so a request cannot reach other files on this computer.

If SITE_VIDEO_TOKEN is set, every request needs "Authorization: Bearer <token>" (or ?token=<token> once in a browser,
which sets a cookie).
"""

import hmac
import json
import os
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import pipeline
from .deliver import KINDS
from .queue import Queue
from .util import read_json

TOKEN = os.environ.get("SITE_VIDEO_TOKEN", "")
MAX_UPLOAD = int(os.environ.get("SITE_VIDEO_MAX_UPLOAD_MB", "4096")) << 20


EXTENSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_extension")
FALLBACK_ADDRESS = "http://127.0.0.1:8940"


def own_address(host_header, proto_header=None) -> str:
    """This queue's address as the caller reached it, like http://HOST:8940, from the Host header (and
    X-Forwarded-Proto behind a proxy). Anything that is not a plain host[:port] gives the loopback fallback, so a
    forged header cannot put text into the extension's settings."""
    host = (host_header or "").strip()
    if not re.fullmatch(r"(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:\d{1,5})?", host):
        return FALLBACK_ADDRESS
    host = re.sub(r"^0\.0\.0\.0(?=:|$)", "127.0.0.1", host)        # 0.0.0.0 is where a server listens, not where to go
    proto = (proto_header or "").split(",")[0].strip().lower()
    return f"{proto if proto in ('http', 'https') else 'http'}://{host}"


def extension_zip(address: str) -> bytes:
    """The browser extension as a zip, with `address` written into config.js as the queue it talks to by default."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(EXTENSION_DIR)):
            if n != "config.js":
                z.write(os.path.join(EXTENSION_DIR, n), "site-video-signin/" + n)
        z.writestr("site-video-signin/config.js",
                   "// Written by the queue that served this zip. It is only the starting value: change it in the popup.\n"
                   f"self.SITE_VIDEO_DEFAULT_SERVER = {json.dumps(address)};\n")
    return buf.getvalue()


def _allowed_media(q: Queue, items) -> list:
    dirs = [os.path.realpath(d) + os.sep for d in os.environ.get("SITE_VIDEO_MEDIA_DIRS", "").split(os.pathsep) if d]
    out = []
    for it in items or []:
        it = {"file": it} if isinstance(it, str) else dict(it or {})
        path = str(it.get("file") or "")
        real = os.path.realpath(path)
        if not (q.is_upload(path) or any(real.startswith(d) for d in dirs)):
            raise ValueError(f"{os.path.basename(path) or 'a video'}: upload it first (POST /api/uploads)")
        out.append({"file": path, "note": str(it.get("note") or "")})
    return out


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
            "models": llm.models(), "default_model": llm.settings()["model"], "deliverables": list(KINDS),
            "editors": list(pipeline.EDITORS), "resolve": resolve_edit.available(),
            "elevenlabs_voice": os.environ.get("SITE_VIDEO_ELEVENLABS_VOICE", ""),
            "openai_voice": os.environ.get("SITE_VIDEO_OPENAI_VOICE", "alloy"),
            "vision_model": os.environ.get("SITE_VIDEO_VISION_MODEL", ""), "stt": os.environ.get("SITE_VIDEO_STT", ""),
            "max_upload_mb": MAX_UPLOAD >> 20}


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

        def _file(self, path):
            types = {".mp4": "video/mp4", ".wav": "audio/wav", ".zip": "application/zip", ".md": "text/markdown",
                     ".json": "application/json", ".png": "image/png"}
            ext = os.path.splitext(path)[1].lower()
            if ext == ".mp4":
                return self._video(path)
            self.send_response(200)
            self.send_header("Content-Type", types.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
            self.end_headers()
            if self.command != "HEAD":
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)

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
                if method == "GET" and u.path == "/cursors":
                    # the cursor looks and how they move, live, for choosing one
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cursors.html"), encoding="utf-8") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if method == "GET" and u.path == "/":
                    from .page import PAGE
                    return self._send(200, PAGE, "text/html; charset=utf-8", extra)
                if u.path == "/api/uploads" and method == "POST":
                    size = int(self.headers.get("Content-Length") or 0)
                    if size <= 0:
                        return self._send(400, {"error": "send the video as the request body"})
                    if size > MAX_UPLOAD:
                        return self._send(413, {"error": f"too big: at most {MAX_UPLOAD >> 20} MB"})
                    from urllib.parse import unquote
                    name = unquote((qs.get("name") or [""])[0])
                    path = q.save_upload(name, self.rfile, size)
                    return self._send(201, {"file": path, "name": os.path.basename(path), "bytes": size})
                if u.path == "/api/signin/import" and method == "POST":
                    # the site-video browser extension sends the sign-in the person's own browser already has
                    from . import session
                    b = self._body()
                    return self._send(200, session.save_from_browser(str(b.get("url") or ""), b.get("state")))
                if u.path == "/api/signin/extension.zip" and method == "GET":
                    # the extension points at the queue it was downloaded from: this request's own address
                    address = own_address(self.headers.get("Host"), self.headers.get("X-Forwarded-Proto"))
                    return self._send(200, extension_zip(address), "application/zip",
                                      {"Content-Disposition": 'attachment; filename="site-video-signin.zip"'})
                if u.path == "/api/signin":
                    # a sign-in window opens on this computer's screen; the person logs in there and closes it
                    from . import session
                    site = (qs.get("url") or [""])[0] if method == "GET" else str(self._body().get("url") or "")
                    if method == "GET":
                        return self._send(200, session.status(site))
                    if method == "DELETE":
                        return self._send(200, {"forgot": session.forget(site), **session.status(site)})
                    if method == "POST":
                        session.host(site)                       # a readable error for a bad address
                        import threading
                        threading.Thread(target=session.signin, args=(site,), daemon=True).start()
                        return self._send(202, {"opened": True, **session.status(site)})
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
                                           str(b.get("model") or ""), b.get("deliverables") or "video",
                                           _allowed_media(q, b.get("media")), b.get("cursor") or "dot",
                                           bool(b.get("changes")))
                    return self._send(201, q.submit(req))
                jid = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._send(200, q.get(jid))
                if len(parts) == 4 and method == "POST" and parts[3] == "cancel":
                    return self._send(200, q.cancel(jid))
                if len(parts) == 4 and method == "POST" and parts[3] == "retry":
                    return self._send(200, q.retry(jid))
                if len(parts) == 4 and method == "POST" and parts[3] == "remove":
                    return self._send(200, q.remove(jid))
                if len(parts) == 4 and method == "GET" and parts[3] == "plan":
                    from . import revise
                    j = q.get(jid)
                    pl = read_json(os.path.join(q._path(jid), "plan.json"))
                    if not pl:
                        return self._send(404, {"error": "this job has no script yet"})
                    return self._send(200, {"plan": pl, "targets": revise.context(q._path(jid)),
                                            "cursor": (j.get("request") or {}).get("cursor") or "dot",
                                            "cursors": list(pipeline.CURSORS)})
                if len(parts) == 4 and method == "POST" and parts[3] == "suggest":
                    from . import revise
                    b = self._body()
                    j = q.get(jid)
                    try:
                        return self._send(200, revise.suggest(q._path(jid), str(b.get("change") or ""),
                                                              (j.get("request") or {}).get("model") or ""))
                    except RuntimeError as e:
                        return self._send(502, {"error": str(e)})
                if len(parts) == 4 and method == "POST" and parts[3] == "revise":
                    b = self._body()
                    return self._send(200, q.revise(jid, b.get("plan"), b.get("cursor")))
                if len(parts) == 4 and method in ("GET", "HEAD") and parts[3] == "video":
                    path = q.video_path(jid)
                    return self._video(path) if path else self._send(404, {"error": "no video yet"})
                if len(parts) >= 5 and method in ("GET", "HEAD") and parts[3] == "files":
                    from urllib.parse import unquote
                    path = q.file_path(jid, unquote("/".join(parts[4:])))
                    return self._file(path) if path else self._send(404, {"error": "no such file"})
                if len(parts) == 4 and method == "GET" and parts[3] == "live.jpg" and re.fullmatch(r"[\w-]+", jid):
                    # what the job's browser shows now (explore and record write it), for the page's live view
                    try:
                        with open(os.path.join(q.jobs_dir, jid, "live.jpg"), "rb") as f:
                            return self._send(200, f.read(), "image/jpeg")
                    except OSError:
                        return self._send(404, {"error": "nothing to show yet"})
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

        def do_DELETE(self):
            self._route("DELETE")
    return H


def serve(home: str, host: str = "127.0.0.1", port: int = 8940, parallel: int = 2) -> None:
    q = Queue(home, parallel)
    q.start()
    srv = ThreadingHTTPServer((host, port), make_handler(q))
    print(f"site-video on http://{host}:{port}  (jobs in {q.jobs_dir}, {parallel} at a time)", flush=True)
    srv.serve_forever()
