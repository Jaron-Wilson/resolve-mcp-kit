"""One video, start to finish, in a job folder. Each stage keeps its output, so a stopped job picks up where it was.

prep(): crawl -> plan -> narration -> recording -> soundtrack   (several jobs can do this at once)
edit(): Resolve (or ffmpeg) -> <name>.mp4                         (one at a time: a Resolve renders one thing)
"""

import os
import re
from typing import Callable, Dict, Optional

from . import assemble, crawl, deliver, plan as planner, voice
from .util import Log, is_auto, parse_length, read_json, write_json

EDITORS = ("auto", "resolve", "ffmpeg")


def request(url: str, length="auto", notes="auto", voice_spec="none", editor="auto", music: str = "",
            name: str = "", model: str = "", deliverables="video") -> Dict:
    """A checked job request (raises ValueError with a readable reason)."""
    if not re.match(r"^https?://", url or ""):
        raise ValueError("the link must start with http:// or https://")
    seconds = parse_length(length)
    voice.parse(voice_spec)
    if editor not in EDITORS:
        raise ValueError(f"editor must be one of {', '.join(EDITORS)}")
    if music and not os.path.isfile(music):
        raise ValueError(f"music file not found: {music}")
    model = str(model or "").strip()
    if len(model) > 120 or any(ch.isspace() for ch in model):
        raise ValueError("model: one model id, like qwen3:8b")
    return {"url": url, "length": "auto" if seconds is None else seconds, "notes": "auto" if is_auto(notes) else notes,
            "voice": voice_spec or "none", "editor": editor, "music": music or "", "name": name or "", "model": model,
            "deliverables": deliver.parse(deliverables)}


def _name(job_dir: str, plan: Dict, req: Dict) -> str:
    base = req.get("name") or plan.get("title") or "site video"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-")[:40] or "site-video"
    return f"{slug}-{os.path.basename(job_dir)[-6:]}"


def prep(job_dir: str, req: Dict, step: Callable[[str, float], None] = lambda s, f: None) -> Dict:
    log = Log(os.path.join(job_dir, "log.txt"))
    seconds = None if req["length"] == "auto" else int(req["length"])

    cr = read_json(os.path.join(job_dir, "crawl.json"))
    if not cr:
        step("reading the site", 0.02)
        cr = crawl.crawl(req["url"], crawl.pages_for(seconds), log)
        write_json(os.path.join(job_dir, "crawl.json"), cr)

    pl = read_json(os.path.join(job_dir, "plan.json"))
    if not pl:
        step("writing the script", 0.1)
        if req.get("model"):
            log(f"script model: {req['model']}")
        pl = planner.make(cr, seconds, req["notes"], log, model=req.get("model") or "")
        write_json(os.path.join(job_dir, "plan.json"), pl)
        log("plan: " + planner.summary(pl))

    vdir = os.path.join(job_dir, "voice")
    os.makedirs(vdir, exist_ok=True)
    texts = [pl["intro"]["narration"]] + [s["narration"] for s in pl["scenes"]] + [pl["outro"]["narration"]]
    vinfo = read_json(os.path.join(vdir, "voice.json"), {})
    if vinfo.get("voice") != req["voice"] or len(vinfo.get("secs", [])) != len(texts):
        vinfo = {"voice": req["voice"], "secs": [], "wavs": []}
        for i, t in enumerate(texts):
            step(f"narration {i + 1}/{len(texts)}", 0.2 + 0.15 * i / len(texts))
            wav = os.path.join(vdir, f"seg_{i:03d}.wav")
            secs = voice.speak(req["voice"], t, wav)
            vinfo["secs"].append(secs)
            vinfo["wavs"].append(wav if secs else None)
        write_json(os.path.join(vdir, "voice.json"), vinfo)
    secs = assemble.durations(pl, vinfo["secs"])

    cdir = os.path.join(job_dir, "clips")
    os.makedirs(cdir, exist_ok=True)
    clips = [os.path.join(cdir, f"seg_{i:03d}.mp4") for i in range(len(secs))]
    timing = read_json(os.path.join(cdir, "timing.json"), {})
    if timing.get("secs") != secs:          # different timings: the old clips do not fit
        for cl in clips:
            if os.path.exists(cl):
                os.unlink(cl)
    if not all(os.path.exists(cl) for cl in clips):
        from .record import Recorder
        rec = Recorder(cdir, log)
        try:
            hero = os.path.join(cdir, "hero.png")
            if not os.path.exists(hero):
                rec.hero(req["url"], hero)
            for i, s in enumerate(pl["scenes"]):
                if not os.path.exists(clips[i + 1]):
                    step(f"recording scene {i + 1}/{len(pl['scenes'])}", 0.35 + 0.45 * i / len(pl["scenes"]))
                    rec.scene(s, secs[i + 1], clips[i + 1])
            if not os.path.exists(clips[0]):
                rec.card("", pl["title"], pl.get("tagline", ""), hero, secs[0], clips[0])
            if not os.path.exists(clips[-1]):
                rec.card("", pl["outro"].get("call_to_action") or pl["url"], pl["url"], hero, secs[-1], clips[-1])
        finally:
            rec.close()
        write_json(os.path.join(cdir, "timing.json"), {"secs": secs})

    mix = os.path.join(job_dir, "soundtrack.wav")
    if not os.path.exists(mix):
        step("mixing the soundtrack", 0.82)
        assemble.soundtrack(job_dir, vinfo["wavs"], secs, req.get("music") or None, mix)
    log(f"ready to edit: {len(clips)} clips, {sum(secs):.1f} s")
    ready = {"plan": pl, "clips": clips, "mix": mix, "secs": secs, "name": _name(job_dir, pl, req)}
    write_json(os.path.join(job_dir, "ready.json"), ready)
    return ready


def edit(job_dir: str, req: Dict, ready: Dict, step: Callable[[str, float], None] = lambda s, f: None) -> Dict:
    log = Log(os.path.join(job_dir, "log.txt"))
    editor = req["editor"]
    if editor in ("auto", "resolve"):
        from . import resolve_edit
        up = resolve_edit.start_if_needed(log)
        if editor == "resolve" and not up:
            raise RuntimeError("DaVinci Resolve is not running here (and SITE_VIDEO_START_RESOLVE could not open it); "
                               "open it, or use the ffmpeg editor")
        editor = "resolve" if up else "ffmpeg"
        log(f"editor: {editor}" + ("" if editor == "resolve" else " (DaVinci Resolve is not reachable here)"))
    step("editing in DaVinci Resolve" if editor == "resolve" else "joining with ffmpeg", 0.86)
    kinds = req.get("deliverables") or ["video"]
    if editor == "resolve":
        from . import resolve_edit
        exports = [k for k, want in (("timeline", "timeline"), ("project", "resolve_project")) if want in kinds]
        res = resolve_edit.edit(job_dir, ready["name"], ready["clips"], ready["mix"],
                                [s["caption"] for s in ready["plan"]["scenes"]], job_dir, log, exports)
    else:
        res = {"video": assemble.edit_ffmpeg(job_dir, ready["clips"], ready["mix"],
                                             os.path.join(job_dir, ready["name"] + ".mp4"))}
    res["editor"] = editor
    step("gathering the deliverables", 0.97)
    wavs = (read_json(os.path.join(job_dir, "voice", "voice.json"), {}) or {}).get("wavs") or []
    files = deliver.collect(job_dir, kinds, ready, res, wavs, log)
    video = os.path.join(job_dir, "deliverables", os.path.basename(res["video"]))
    log(f"done: {video}")
    return {"video": video, "editor": editor, "seconds": round(sum(ready["secs"]), 1), "files": files}


def run(job_dir: str, req: Dict, step: Optional[Callable] = None) -> Dict:
    step = step or (lambda s, f: print(f"[{int(f * 100):3d}%] {s}", flush=True))
    os.makedirs(job_dir, exist_ok=True)
    ready = prep(job_dir, req, step)
    return edit(job_dir, req, ready, step)
