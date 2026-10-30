"""site-video: make a promo video of a website.

  site-video make URL [--length 5min|90s|auto] [--notes "show pricing"|auto] [--voice none|openai:alloy|elevenlabs:ID|odysseus]
                      [--editor auto|resolve|ffmpeg] [--music track.mp3] [--name NAME] [--out DIR]
  site-video serve [--host 127.0.0.1] [--port 8940] [--parallel 2] [--home DIR]
  site-video add URL [same options as make] [--server http://host:8940]
  site-video list | status ID | cancel ID | retry ID | get ID [-o file.mp4]     [--server ...]

The model that writes the script, and the voices, are set with environment variables: see README.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

DEFAULT_SERVER = os.environ.get("SITE_VIDEO_SERVER", "http://127.0.0.1:8940")
DEFAULT_HOME = os.environ.get("SITE_VIDEO_HOME", os.path.join(os.path.expanduser("~"), "site-videos"))


def _http(server, method, path, body=None, raw=False):
    headers = {"Content-Type": "application/json"}
    tok = os.environ.get("SITE_VIDEO_TOKEN")
    if tok:
        headers["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(server.rstrip("/") + path, json.dumps(body).encode() if body is not None else None,
                                 headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r if raw else json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error")
        except Exception:
            msg = str(e)
        sys.exit(f"error: {msg}")


def _show(j):
    r = j.get("request", {})
    pct = f"{int((j.get('progress') or 0) * 100)}%"
    print(f"{j['id']}  {j['status']:<9} {pct:>4}  {r.get('url')}  ({j.get('step') or ''})")
    if j.get("error"):
        print("    error:", j["error"])
    if j.get("video"):
        print("    video:", j["video"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="site-video", description="Make a promo video of a website.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def job_args(p):
        p.add_argument("url")
        p.add_argument("--length", default="auto", help="5min, 90s, 1:30 or auto (default)")
        p.add_argument("--notes", default="auto", help='what the video must do, e.g. "show pricing, end on sign-up"')
        p.add_argument("--voice", default=os.environ.get("SITE_VIDEO_DEFAULT_VOICE", "none"),
                       help="none, openai[:voice], elevenlabs:<voice id>, odysseus")
        p.add_argument("--editor", default="auto", choices=["auto", "resolve", "ffmpeg"])
        p.add_argument("--name", default="")

    p = sub.add_parser("make", help="make one video now, in this terminal")
    job_args(p)
    p.add_argument("--music", default="", help="an audio file to play under the narration")
    p.add_argument("--out", default="", help="job folder (default under ~/site-videos/jobs)")
    p = sub.add_parser("serve", help="run the queue and its web page")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8940)
    p.add_argument("--parallel", type=int, default=2, help="videos prepared at the same time (edits take turns)")
    p.add_argument("--home", default=DEFAULT_HOME)
    p = sub.add_parser("add", help="queue a video on a running server")
    job_args(p)
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--wait", action="store_true", help="wait until it is done")
    for name in ("list", "status", "cancel", "retry", "get"):
        p = sub.add_parser(name)
        if name != "list":
            p.add_argument("id")
        if name == "get":
            p.add_argument("-o", "--output", default="")
        p.add_argument("--server", default=DEFAULT_SERVER)
    p = sub.add_parser("_stage")      # internal: one stage of a queued job, in its own process
    p.add_argument("stage", choices=["prep", "edit"])
    p.add_argument("job_dir")
    a = ap.parse_args(argv)

    if a.cmd == "_stage":
        from .queue import run_stage
        sys.exit(run_stage(a.stage, a.job_dir))
    if a.cmd == "make":
        from . import pipeline
        try:
            req = pipeline.request(a.url, a.length, a.notes, a.voice, a.editor, a.music, a.name)
        except ValueError as e:
            sys.exit(f"error: {e}")
        out = a.out or os.path.join(DEFAULT_HOME, "jobs", time.strftime("%Y%m%d-%H%M%S-cli"))
        res = pipeline.run(out, req)
        print(json.dumps(res, indent=2))
        return
    if a.cmd == "serve":
        from .server import serve
        serve(a.home, a.host, a.port, a.parallel)
        return
    if a.cmd == "add":
        j = _http(a.server, "POST", "/api/jobs", {"url": a.url, "length": a.length, "notes": a.notes, "voice": a.voice,
                                                    "editor": a.editor, "name": a.name})
        _show(j)
        while a.wait and j["status"] not in ("done", "failed", "cancelled"):
            time.sleep(5)
            j = _http(a.server, "GET", f"/api/jobs/{j['id']}")
            print(f"  {int((j.get('progress') or 0) * 100):3d}%  {j.get('step')}", flush=True)
        if a.wait:
            _show(j)
        return
    if a.cmd == "list":
        for j in _http(a.server, "GET", "/api/jobs"):
            _show(j)
        return
    if a.cmd == "status":
        _show(_http(a.server, "GET", f"/api/jobs/{a.id}"))
        return
    if a.cmd in ("cancel", "retry"):
        _show(_http(a.server, "POST", f"/api/jobs/{a.id}/{a.cmd}"))
        return
    if a.cmd == "get":
        r = _http(a.server, "GET", f"/api/jobs/{a.id}/video", raw=True)
        name = a.output or (r.headers.get("Content-Disposition", "").split('filename="')[-1].rstrip('"') or a.id + ".mp4")
        with open(name, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        print(name)


if __name__ == "__main__":
    main()
