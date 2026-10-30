"""The user's own videos: what is in them (so the script can pick moments), and cutting a moment into a clip that
matches the rest of the edit.

Analysis, kept in <job>/media/<file>.json:
- length, size, whether it has sound;
- a frame every few seconds described by a vision model (SITE_VIDEO_VISION_MODEL on the SITE_VIDEO_LLM_URL endpoint,
  e.g. a qwen2.5vl; without one, only the user's note and the length are known);
- what is said, with times, from speech to text in 15 second pieces: SITE_VIDEO_STT=openai (SITE_VIDEO_STT_URL /
  SITE_VIDEO_STT_KEY / SITE_VIDEO_STT_MODEL, an OpenAI-compatible /audio/transcriptions) or odysseus (the Odysseus
  server of the odysseus voice).
"""

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import uuid
from typing import Dict, List

from . import llm
from .util import FPS, HANDLE, HEIGHT, RATE, WIDTH, ffmpeg, ffmpeg_exe, frames, read_json, write_json

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
CHUNK = 15.0


def probe(path: str) -> Dict:
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True)
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise ValueError(f"{os.path.basename(path)} is not a video ffmpeg can read")
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not size:
        raise ValueError(f"{os.path.basename(path)} has no video stream")
    return {"seconds": round(secs, 2), "width": int(size.group(1)), "height": int(size.group(2)),
            "audio": " Audio:" in err}


def _describe(jpg: str, note: str, ask: str = "", max_tokens: int = 120) -> str:
    model = os.environ.get("SITE_VIDEO_VISION_MODEL", "")
    if not model:
        return ""
    with open(jpg, "rb") as f:
        url = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    s = llm.settings()
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0.2, "stream": False, "messages": [{"role": "user", "content": [
        {"type": "text", "text": ask or ("Describe this video frame in one short sentence for a video editor: what is on "
                                         "screen (app screens, text, people, products). "
                                         + (f"The owner says the video is: {note}" if note else ""))},
        {"type": "image_url", "image_url": {"url": url}}]}]}
    headers = {"Content-Type": "application/json"}
    if s["key"]:
        headers["Authorization"] = "Bearer " + s["key"]
    req = urllib.request.Request(s["url"] + "/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.load(r)["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip().replace("\n", " ")[:max(220, max_tokens * 4)]


def _multipart(field: str, filename: str, data: bytes, extra: Dict[str, str]) -> tuple:
    b = "----sv" + uuid.uuid4().hex
    parts = [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in extra.items()]
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: audio/wav\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{b}--\r\n".encode(), "multipart/form-data; boundary=" + b


def _stt(wav: str) -> str:
    kind = os.environ.get("SITE_VIDEO_STT", "").lower()
    with open(wav, "rb") as f:
        data = f.read()
    if kind == "openai":
        base = os.environ.get("SITE_VIDEO_STT_URL", "https://api.openai.com/v1").rstrip("/")
        key = os.environ.get("SITE_VIDEO_STT_KEY") or os.environ.get("OPENAI_API_KEY", "")
        body, ctype = _multipart("file", "a.wav", data, {"model": os.environ.get("SITE_VIDEO_STT_MODEL", "whisper-1")})
        req = urllib.request.Request(base + "/audio/transcriptions", body, {"Content-Type": ctype,
                                                                           **({"Authorization": "Bearer " + key} if key else {})})
    elif kind == "odysseus":
        base = os.environ.get("SITE_VIDEO_ODYSSEUS_URL", "").rstrip("/")
        tok = os.environ.get("SITE_VIDEO_ODYSSEUS_TOKEN", "")
        body, ctype = _multipart("file", "a.wav", data, {})
        req = urllib.request.Request(base + "/api/stt/transcribe", body, {"Content-Type": ctype,
                                                                         **({"Authorization": "Bearer " + tok} if tok else {})})
    else:
        return ""
    with urllib.request.urlopen(req, timeout=300) as r:
        return (json.load(r).get("text") or "").strip()


def analyze(path: str, note: str, out_json: str, log=print) -> Dict:
    """What is in a video, kept in out_json (a second call returns it from there)."""
    have = read_json(out_json)
    if have:
        return have
    info = probe(path)
    info.update(file=os.path.basename(path), note=note or "", shots=[], speech=[])
    step = min(10.0, max(3.0, info["seconds"] / 24))
    with tempfile.TemporaryDirectory() as tmp:
        if os.environ.get("SITE_VIDEO_VISION_MODEL"):
            t = min(1.0, info["seconds"] / 2)
            while t < info["seconds"]:
                jpg = os.path.join(tmp, "f.jpg")
                try:
                    ffmpeg("-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "4", jpg)
                    info["shots"].append({"t": round(t, 1), "what": _describe(jpg, note)})
                except Exception as e:
                    log(f"  frame at {t:.0f}s of {info['file']}: {type(e).__name__}")
                t += step
            log(f"  {info['file']}: {len(info['shots'])} frames described")
        if info["audio"] and os.environ.get("SITE_VIDEO_STT"):
            t = 0.0
            while t < info["seconds"]:
                wav = os.path.join(tmp, "a.wav")
                try:
                    ffmpeg("-ss", f"{t:.2f}", "-t", f"{CHUNK}", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav)
                    text = _stt(wav)
                    if text and len(text) > 2:
                        info["speech"].append({"from": round(t, 1), "to": round(min(info["seconds"], t + CHUNK), 1),
                                               "text": text[:600]})
                except Exception as e:
                    log(f"  speech at {t:.0f}s of {info['file']}: {type(e).__name__}")
                t += CHUNK
            log(f"  {info['file']}: speech in {len(info['speech'])} of {int(info['seconds'] // CHUNK) + 1} pieces")
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    write_json(out_json, info)
    return info


def catalogue(items: List[Dict]) -> str:
    """The user's videos as text for the script model."""
    out = []
    for m in items:
        out.append(f"VIDEO {m['file']}: {m['seconds']:.1f} s, {m['width']}x{m['height']}, "
                   f"{'has sound' if m['audio'] else 'no sound'}" + (f". The owner says: {m['note']}" if m.get("note") else ""))
        for s in m.get("shots") or []:
            out.append(f"  at {s['t']:.1f}s: {s['what']}")
        for s in m.get("speech") or []:
            out.append(f"  said {s['from']:.0f}-{s['to']:.0f}s: \"{s['text']}\"")
    return "\n".join(out)


def frame_png(path: str, at: float, out_png: str) -> None:
    """One frame of a video at full HD, e.g. as the title cards' background when there is no website."""
    ffmpeg("-ss", f"{at:.2f}", "-i", path, "-frames:v", "1",
           "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}", out_png)


def cut(path: str, start: float, seconds: float, out_mp4: str, out_wav: str = "") -> None:
    """[start, start+seconds) of a video as a 1920x1080 30 fps clip of exact length (the last frame held if the
    video ends first) plus HANDLE frames each side for the dissolves, and its sound (the exact length, no handles)
    as a 48 kHz WAV when out_wav is given. Captions go over it in the edit."""
    n = frames(seconds)
    fit = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
           f"setsar=1,fps={FPS},tpad=stop_mode=clone:stop_duration={seconds + 1:.2f},trim=end_frame={n},"
           f"tpad=start_mode=clone:start={HANDLE}:stop_mode=clone:stop={HANDLE},format=yuv420p")
    ffmpeg("-ss", f"{start:.3f}", "-i", path, "-an", "-vf", fit,
           "-frames:v", str(n + 2 * HANDLE), "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
           "-movflags", "+faststart", out_mp4)
    if out_wav:
        ffmpeg("-ss", f"{start:.3f}", "-i", path, "-t", f"{n / FPS:.4f}", "-vn", "-af", "apad", "-ar", str(RATE),
               "-ac", "2", "-c:a", "pcm_s16le", "-t", f"{n / FPS:.4f}", out_wav)
