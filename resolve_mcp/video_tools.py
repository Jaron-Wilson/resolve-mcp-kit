"""Website promo videos through a site-video queue (see site_video/). The queue does the work; these tools add a job,
and report on jobs. Registered when RESOLVE_MCP_ALLOW_WRITE=1 or SITE_VIDEO_SERVER is set.

SITE_VIDEO_SERVER  the queue's address (default http://127.0.0.1:8940); start one with `python -m site_video serve`
SITE_VIDEO_TOKEN   its token, if it has one
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

SERVER = os.environ.get("SITE_VIDEO_SERVER", "http://127.0.0.1:8940").rstrip("/")


def _call(method: str, path: str, body=None):
    headers = {"Content-Type": "application/json"}
    if os.environ.get("SITE_VIDEO_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["SITE_VIDEO_TOKEN"]
    req = urllib.request.Request(SERVER + path, json.dumps(body).encode() if body is not None else None, headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error")
        except Exception:
            msg = str(e)
        raise RuntimeError(f"site-video queue: {msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"No site-video queue at {SERVER} ({e.reason}). Start one on the Resolve machine with "
                           "`python -m site_video serve`, or set SITE_VIDEO_SERVER.")


def _short(j: Dict[str, Any]) -> Dict[str, Any]:
    r = j.get("request") or {}
    out = {"id": j["id"], "status": j["status"], "step": j.get("step"), "progress": j.get("progress"),
           "url": r.get("url"), "length": r.get("length"), "voice": r.get("voice")}
    for k in ("error", "video", "editor", "seconds"):
        if j.get(k):
            out[k] = j[k]
    if j["status"] == "done":
        out["download"] = f"{SERVER}/api/jobs/{j['id']}/video"
    return out


def register(mcp):
    @mcp.tool()
    def make_site_video(url: str, length: str = "auto", notes: str = "auto", voice: str = "",
                        editor: str = "auto", name: str = "") -> Dict[str, Any]:
        """Queue a promo video of a website. It reads the site, writes a script, records the site in a browser,
        adds a voiceover, and edits and renders it in DaVinci Resolve (ffmpeg if Resolve is closed). Takes a few
        minutes; returns a job id at once, then check it with site_video_status.

        length: "5min", "90s", "1:30" or "auto". notes: what the video must do or show, in plain words ("show the
        pricing page, end on sign-up, upbeat"), or "auto". voice: "none", "openai[:voice]", "elevenlabs:<voice id>",
        "odysseus", or "" for the queue's default. editor: "auto", "resolve" or "ffmpeg"."""
        body = {"url": url, "length": length or "auto", "notes": notes or "auto", "editor": editor or "auto",
                "name": name}
        if voice:
            body["voice"] = voice
        else:
            body["voice"] = _call("GET", "/api/info").get("default_voice", "none")
        return _short(_call("POST", "/api/jobs", body))

    @mcp.tool()
    def site_video_status(job_id: str) -> Dict[str, Any]:
        """Where a queued site video is: queued, preparing (with its current step), waiting for the editor,
        editing, done (with the file and a download link), failed (with why) or cancelled."""
        return _short(_call("GET", f"/api/jobs/{job_id}"))

    @mcp.tool()
    def list_site_videos(limit: int = 10) -> List[Dict[str, Any]]:
        """The newest site videos in the queue, newest first."""
        return [_short(j) for j in _call("GET", "/api/jobs")[: max(1, int(limit))]]
