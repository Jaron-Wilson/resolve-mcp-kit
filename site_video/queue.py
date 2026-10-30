"""A queue of videos. Up to `parallel` jobs prepare at once (read, script, voice, record, mix); edits take turns,
since one DaVinci Resolve renders one thing at a time. Each stage runs in its own process, so a cancel stops it at
once and one bad site cannot take the queue down. Jobs live in <home>/jobs/<id>/ and survive a restart: anything that
was running starts again from its last finished stage.

job.json: {id, created, request, status, step, progress, error, video, editor, seconds, started, finished}
status:   queued -> preparing -> waiting -> editing -> done   (or failed / cancelled)
"""

import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from .util import read_json, write_json

ACTIVE = ("preparing", "waiting", "editing")


class Queue:
    def __init__(self, home: str, parallel: int = 2):
        self.home = os.path.abspath(home)
        self.jobs_dir = os.path.join(self.home, "jobs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        self.parallel = max(1, int(parallel))
        self._lock = threading.Lock()
        self._edit = threading.Lock()
        self._procs: Dict[str, subprocess.Popen] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._wake = threading.Event()
        for j in self.list():                       # interrupted by a restart: queue again, stages resume
            if j["status"] in ACTIVE:
                self._update(j["id"], status="queued", step="queued again after a restart")

    # ── jobs on disk ──
    def _path(self, jid: str) -> str:
        if not jid or "/" in jid or "\\" in jid or jid.startswith("."):
            raise KeyError(jid)
        return os.path.join(self.jobs_dir, jid)

    def get(self, jid: str) -> Dict:
        j = read_json(os.path.join(self._path(jid), "job.json"))
        if not j:
            raise KeyError(jid)
        prog = read_json(os.path.join(self._path(jid), "progress.json"))
        if prog and j["status"] in ACTIVE:
            j.update(step=prog.get("step", j.get("step")), progress=prog.get("progress", j.get("progress")))
        return j

    def list(self) -> List[Dict]:
        out = []
        for jid in os.listdir(self.jobs_dir):
            try:
                out.append(self.get(jid))
            except KeyError:
                pass
        return sorted(out, key=lambda j: j["created"], reverse=True)

    def _update(self, jid: str, **kw) -> Dict:
        with self._lock:
            p = os.path.join(self._path(jid), "job.json")
            j = read_json(p) or {}
            j.update(kw)
            write_json(p, j)
            return j

    # ── uploads: the owner's videos, sent before the job that uses them ──
    @property
    def uploads_dir(self) -> str:
        return os.path.join(self.home, "uploads")

    def save_upload(self, name: str, stream, size: int) -> str:
        """Write `size` bytes from `stream` as a new upload; its path goes in a job's media list."""
        base = os.path.basename(str(name or "").replace("\\", "/")).strip()
        base = "".join(ch if ch.isalnum() or ch in " ._-()" else "_" for ch in base)[:100].strip(" .") or "video.mp4"
        folder = os.path.join(self.uploads_dir, secrets.token_hex(6))
        os.makedirs(folder)
        path = os.path.join(folder, base)
        left = size
        with open(path, "wb") as f:
            while left > 0:
                chunk = stream.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            shutil.rmtree(folder, ignore_errors=True)
            raise ValueError("the upload stopped before the end")
        return path

    def is_upload(self, path: str) -> bool:
        up = os.path.realpath(self.uploads_dir) + os.sep
        return os.path.realpath(path).startswith(up)

    def submit(self, req: Dict) -> Dict:
        jid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        os.makedirs(self._path(jid))
        moved = []
        for m in req.get("media") or []:        # uploads move into the job, so removing the job removes them
            if self.is_upload(m["file"]):
                dest = os.path.join(self._path(jid), "media", os.path.basename(m["file"]))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(m["file"], dest)
                shutil.rmtree(os.path.dirname(m["file"]), ignore_errors=True)
                moved.append(dict(m, file=dest))
            else:
                moved.append(m)
        if req.get("media"):
            req = dict(req, media=moved)
        j = {"id": jid, "created": time.time(), "request": req, "status": "queued", "step": "waiting for a free slot",
             "progress": 0.0, "error": None, "video": None}
        write_json(os.path.join(self._path(jid), "job.json"), j)
        self._wake.set()
        return j

    def cancel(self, jid: str) -> Dict:
        j = self.get(jid)
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        self._update(jid, status="cancelled", step="cancelled", finished=time.time())
        proc = self._procs.get(jid)
        if proc and proc.poll() is None:
            proc.terminate()
        return self.get(jid)

    def retry(self, jid: str) -> Dict:
        j = self.get(jid)
        if j["status"] not in ("failed", "cancelled"):
            raise ValueError(f"job is {j['status']}; only failed or cancelled jobs can be retried")
        self._update(jid, status="queued", step="queued again", error=None, progress=0.0)
        self._wake.set()
        return self.get(jid)

    def revise(self, jid: str, plan: Dict, cursor: Optional[str] = None) -> Dict:
        """Make an edited script the job's script (and, if given, change its cursor), then make the video again.
        Only what changed is redone."""
        from . import pipeline, revise
        j = self.get(jid)
        if j["status"] in ACTIVE or j["status"] == "queued":
            raise ValueError(f"the job is {j['status']}; wait for it to finish, or cancel it first")
        req = dict(j["request"])
        if cursor is not None:
            req["cursor"] = pipeline._cursor(cursor)
        done = revise.apply(self._path(jid), plan)
        self._update(jid, request=req, status="queued", step="queued with your changes", error=None, progress=0.0,
                     revisions=int(j.get("revisions") or 0) + 1, changes=done["changes"][:40])
        self._wake.set()
        return self.get(jid)

    def remove(self, jid: str) -> Dict:
        """Delete a job that is not running, with its files. (Its Resolve project, if any, stays in Resolve.)"""
        import shutil
        j = self.get(jid)
        if j["status"] in ACTIVE or jid in self._threads:
            raise ValueError(f"the job is {j['status']}; cancel it first")
        with self._lock:
            shutil.rmtree(self._path(jid), ignore_errors=True)
        return {"id": jid, "removed": True}

    def file_path(self, jid: str, name: str) -> Optional[str]:
        """A deliverable of a finished job, by its name in job["files"] (only those, so nothing else can be read)."""
        j = self.get(jid)
        if not any(f.get("name") == name for f in j.get("files") or []):
            return None
        base = os.path.realpath(os.path.join(self._path(jid), "deliverables"))
        path = os.path.realpath(os.path.join(base, *name.split("/")))
        return path if path.startswith(base + os.sep) and os.path.isfile(path) else None

    def video_path(self, jid: str) -> Optional[str]:
        v = self.get(jid).get("video")
        return v if v and os.path.isfile(v) else None

    # ── running ──
    def _stage(self, jid: str, stage: str) -> None:
        cmd = [sys.executable, "-m", "site_video", "_stage", stage, self._path(jid)]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.environ.get("PYTHONPATH")])))
        with open(os.path.join(self._path(jid), "stage.out"), "ab") as out:
            proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
            self._procs[jid] = proc
            code = proc.wait()
        self._procs.pop(jid, None)
        if self.get(jid)["status"] == "cancelled":
            raise InterruptedError
        if code != 0:
            err = read_json(os.path.join(self._path(jid), "error.json"), {}).get("error")
            raise RuntimeError(err or f"the {stage} stage stopped (exit {code}); see stage.out")

    def _run(self, jid: str) -> None:
        try:
            self._update(jid, status="preparing", started=time.time(), error=None)
            self._stage(jid, "prep")
            self._update(jid, status="waiting", step="waiting for the editor", progress=0.85)
            with self._edit:
                if self.get(jid)["status"] == "cancelled":
                    return
                self._update(jid, status="editing")
                self._stage(jid, "edit")
            res = read_json(os.path.join(self._path(jid), "result.json"), {})
            self._update(jid, status="done", step="done", progress=1.0, finished=time.time(), **res)
        except InterruptedError:
            pass
        except Exception as e:
            if self.get(jid)["status"] != "cancelled":
                self._update(jid, status="failed", step="failed", error=str(e)[:600], finished=time.time())
        finally:
            self._threads.pop(jid, None)
            self._wake.set()

    def _dispatch(self) -> None:
        while True:
            preparing = sum(1 for j in self.list() if j["status"] == "preparing")
            waiting = sorted((j for j in self.list() if j["status"] == "queued"), key=lambda j: j["created"])
            for j in waiting[: max(0, self.parallel - preparing)]:
                if j["id"] not in self._threads:
                    t = threading.Thread(target=self._run, args=(j["id"],), daemon=True)
                    self._threads[j["id"]] = t
                    t.start()
                    time.sleep(0.2)
            self._wake.wait(5)
            self._wake.clear()

    def start(self) -> None:
        threading.Thread(target=self._dispatch, daemon=True).start()


def run_stage(stage: str, job_dir: str) -> int:
    """Runs in the child process: one stage of one job, reporting progress to progress.json."""
    import traceback
    from . import pipeline
    req = read_json(os.path.join(job_dir, "job.json"))["request"]

    def step(s, f):
        write_json(os.path.join(job_dir, "progress.json"), {"step": s, "progress": round(f, 3), "at": time.time()})
    if os.path.exists(os.path.join(job_dir, "error.json")):
        os.unlink(os.path.join(job_dir, "error.json"))
    try:
        if stage == "prep":
            pipeline.prep(job_dir, req, step)
        else:
            ready = read_json(os.path.join(job_dir, "ready.json"))
            if not ready:
                raise RuntimeError("nothing to edit: the prep stage has not finished")
            write_json(os.path.join(job_dir, "result.json"), pipeline.edit(job_dir, req, ready, step))
        return 0
    except Exception as e:
        traceback.print_exc()
        write_json(os.path.join(job_dir, "error.json"), {"error": f"{type(e).__name__}: {e}"})
        return 1
