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
           "url": r.get("url"), "videos": [m.get("file") for m in r.get("media") or []], "length": r.get("length"),
           "voice": r.get("voice"), "model": r.get("model") or "default"}
    for k in ("error", "video", "editor", "seconds"):
        if j.get(k):
            out[k] = j[k]
    if j.get("files"):
        out["files"] = [{"name": f["name"], "kind": f["kind"], "download": f"{SERVER}/api/jobs/{j['id']}/files/{f['name']}"}
                        for f in j["files"]]
    if j["status"] == "done":
        out["download"] = f"{SERVER}/api/jobs/{j['id']}/video"
    return out


def register(mcp):
    @mcp.tool()
    def make_site_video(url: str = "", length: str = "auto", notes: str = "auto", voice: str = "",
                        editor: str = "auto", name: str = "", model: str = "",
                        deliverables: List[str] = (), videos: List[Dict[str, str]] = (),
                        cursor: str = "arrow") -> Dict[str, Any]:
        """Queue a promo video of a website, of the user's own videos, or of both. It reads the site, watches the
        videos, writes a script, records the site in a browser, adds a voiceover, and edits and renders it in DaVinci
        Resolve (ffmpeg if Resolve is closed). Takes a few minutes; returns a job id at once, then check it with
        site_video_status.

        url: the website, or "" for videos only. videos: [{"file": path, "note": "what it is, what to use"}], files
        the queue already has (uploaded on its page, or in its SITE_VIDEO_MEDIA_DIRS folders); with a url too, website
        scenes fill the length around them.

        length: "5min", "90s", "1:30" or "auto". notes: what the video must do or show, in plain words ("show the
        pricing page, end on sign-up, upbeat"), or "auto". voice: "none", "openai[:voice]", "elevenlabs:<voice id>",
        "odysseus", or "" for the queue's default. editor: "auto", "resolve" or "ffmpeg". model: the model that writes
        the script (one of the queue's models, see /api/info), or "" for its default. deliverables: what to hand
        back besides the video: script, voiceover, clips, timeline (.drt/.fcpxml/.edl), resolve_project (.drp),
        package (all of it zipped)."""
        body = {"url": url or "", "media": list(videos or []), "cursor": cursor or "arrow", "length": length or "auto", "notes": notes or "auto", "editor": editor or "auto",
                "name": name, "model": model or "", "deliverables": list(deliverables) or ["video"]}
        if voice:
            body["voice"] = voice
        else:
            body["voice"] = _call("GET", "/api/info").get("default_voice", "none")
        return _short(_call("POST", "/api/jobs", body))

    @mcp.tool()
    def edit_site_video(job_id: str, change: str, cursor: str = "") -> Dict[str, Any]:
        """Change a finished (or failed) site video and make it again. `change` is the person's words: "in scene 3
        point the cursor at the Pro plan instead", "make the intro shorter", "swap scenes 4 and 5". The script model
        applies it to the video's script; only the scenes that change are recorded again. cursor: arrow, hand, ring
        or none, only if they asked for a different cursor. Returns the job (with "changes"); follow it with
        site_video_status."""
        got = _call("POST", f"/api/jobs/{job_id}/suggest", {"change": change})
        body = {"plan": got["plan"]}
        if cursor:
            body["cursor"] = cursor
        out = _short(_call("POST", f"/api/jobs/{job_id}/revise", body))
        out["changes"] = got["changes"]
        return out

    @mcp.tool()
    def site_video_status(job_id: str) -> Dict[str, Any]:
        """Where a queued site video is: queued, preparing (with its current step), waiting for the editor,
        editing, done (with the file and a download link), failed (with why) or cancelled."""
        return _short(_call("GET", f"/api/jobs/{job_id}"))

    @mcp.tool()
    def list_site_videos(limit: int = 10) -> List[Dict[str, Any]]:
        """The newest site videos in the queue, newest first."""
        return [_short(j) for j in _call("GET", "/api/jobs")[: max(1, int(limit))]]
