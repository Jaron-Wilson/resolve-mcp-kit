"""Small shared helpers: ffmpeg, durations, the length setting, and a job log."""

import json
import os
import re
import subprocess
import time
import wave
from typing import List, Optional

FPS = 30
WIDTH, HEIGHT = 1920, 1080
# pages are laid out and recorded at a real 1920x1080 (the hand-made promos were; upscaled 720p looked soft)
VIEW_W, VIEW_H, SCALE = 1920, 1080, 1
HANDLE = 15       # spare frames before and after every clip, so the edit can dissolve across each cut
DISSOLVE = 14     # frames, centered on each cut
RATE = 48000      # audio sample rate everywhere


def ffmpeg_exe() -> str:
    """FFMPEG if set, else the static build that imageio-ffmpeg ships (so nothing else needs installing)."""
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ffmpeg(*args: str, cwd: Optional[str] = None) -> None:
    """Run ffmpeg quietly; raise with the end of its output when it fails."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        out = os.path.join(cwd or "", args[-1]) if args and (len(args) < 2 or args[-2] != "-i") else ""
        if out and os.path.isfile(out):
            os.unlink(out)          # a half-written file would pass for a finished segment next time
        raise RuntimeError("ffmpeg failed: " + (r.stderr or r.stdout).strip()[-800:])


def media_seconds(path: str) -> float:
    """Duration of an audio or video file. WAV is read directly; anything else asks ffmpeg."""
    if path.lower().endswith(".wav"):
        with wave.open(path) as w:
            return w.getnframes() / float(w.getframerate())
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise RuntimeError(f"could not read the duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def parse_length(text) -> Optional[int]:
    """'5min', '5m', '90s', '1:30', '2', 90 -> seconds; 'auto', '' or None -> None. A bare number is minutes."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text * 60) if text <= 30 else int(text)
    t = str(text).strip().lower().replace(" ", "")
    if t in ("", "auto"):
        return None
    m = re.fullmatch(r"(\d+):(\d{1,2})", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(s|sec|secs|seconds?|m|min|mins|minutes?|)", t)
    if not m:
        raise ValueError(f"length {text!r}: use something like 5min, 90s, 1:30 or auto")
    n, unit = float(m.group(1)), m.group(2)
    secs = n if unit.startswith("s") else n * 60
    if not 10 <= secs <= 30 * 60:
        raise ValueError("length must be between 10 seconds and 30 minutes")
    return int(secs)


def is_auto(text) -> bool:
    return text is None or str(text).strip().lower() in ("", "auto")


def frames(seconds: float) -> int:
    return max(1, int(round(seconds * FPS)))


class Log:
    """Appends timestamped lines to <job>/log.txt and remembers the last one for status displays."""

    def __init__(self, path: str):
        self.path = path
        self.last = ""

    def __call__(self, msg: str) -> None:
        self.last = msg
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


_LIVE: dict = {}


def live(job_dir: str, jpeg: bytes, every: float = 0.8) -> None:
    """The picture the job's browser shows right now, as <job>/live.jpg (at most every `every` seconds), so the
    page can show it while the job works. Read-only for the viewer: nothing goes back to the browser."""
    if not job_dir or time.time() - _LIVE.get(job_dir, 0) < every:
        return
    _LIVE[job_dir] = time.time()
    path = os.path.join(job_dir, "live.jpg")
    try:
        with open(path + ".tmp", "wb") as f:
            f.write(jpeg)
        os.replace(path + ".tmp", path)
    except OSError:                                  # being read at that moment (Windows): the next one goes
        pass


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def silence(path: str, seconds: float) -> None:
    ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", path)


def words(text: str) -> List[str]:
    return re.findall(r"\S+", text or "")
