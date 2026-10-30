"""One video, start to finish, in a job folder. Each stage keeps its output, so a stopped job picks up where it was.

prep(): crawl -> plan -> narration -> recording -> soundtrack   (several jobs can do this at once)
edit(): Resolve (or ffmpeg) -> <name>.mp4                         (one at a time: a Resolve renders one thing)
"""

import hashlib
import json
import os
import re
from typing import Callable, Dict, List, Optional

from . import assemble, crawl, deliver, media as footage, plan as planner, voice
from .util import Log, is_auto, parse_length, read_json, write_json

EDITORS = ("auto", "resolve", "ffmpeg")
MAX_MEDIA = 12
CURSORS = ("arrow", "hand", "ring", "none")     # the cursor drawn on website scenes (record.py)


def _cursor(c) -> str:
    c = str(c or "arrow").strip().lower()
    if c not in CURSORS:
        raise ValueError(f"cursor must be one of {', '.join(CURSORS)}")
    return c


def media_list(items) -> List[Dict]:
    """The owner's videos as [{"file": path, "note": text}] (raises ValueError with a readable reason)."""
    out = []
    for it in items or []:
        it = {"file": it} if isinstance(it, str) else dict(it or {})
        path = os.path.abspath(str(it.get("file") or ""))
        if not os.path.isfile(path):
            raise ValueError(f"video not found: {it.get('file')}")
        if not path.lower().endswith(footage.VIDEO_EXT):
            raise ValueError(f"{os.path.basename(path)}: use a video file ({', '.join(footage.VIDEO_EXT)})")
        out.append({"file": path, "note": str(it.get("note") or "").strip()[:500]})
    if len(out) > MAX_MEDIA:
        raise ValueError(f"at most {MAX_MEDIA} videos per job")
    if len({os.path.basename(m["file"]).lower() for m in out}) != len(out):
        raise ValueError("two videos have the same file name: rename one")
    return out


def request(url: str, length="auto", notes="auto", voice_spec="none", editor="auto", music: str = "",
            name: str = "", model: str = "", deliverables="video", media=None, cursor: str = "arrow") -> Dict:
    """A checked job request (raises ValueError with a readable reason). A website link, the owner's videos
    (`media`), or both: with both, website scenes fill the length around the videos."""
    media = media_list(media)
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url):
        raise ValueError("the link must start with http:// or https://")
    if not url and not media:
        raise ValueError("give a website link, your own videos, or both")
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
            "deliverables": deliver.parse(deliverables), "media": media, "cursor": _cursor(cursor)}


def _name(job_dir: str, plan: Dict, req: Dict) -> str:
    base = req.get("name") or plan.get("title") or "video"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-")[:40] or "site-video"
    return f"{slug}-{os.path.basename(job_dir)[-6:]}"


def prep(job_dir: str, req: Dict, step: Callable[[str, float], None] = lambda s, f: None) -> Dict:
    log = Log(os.path.join(job_dir, "log.txt"))
    seconds = None if req["length"] == "auto" else int(req["length"])

    cr = read_json(os.path.join(job_dir, "crawl.json")) if req.get("url") else None
    if req.get("url") and not cr:
        step("reading the site", 0.02)
        cr = crawl.crawl(req["url"], crawl.pages_for(seconds), log)
        write_json(os.path.join(job_dir, "crawl.json"), cr)

    vids = req.get("media") or []
    known = []
    for i, m in enumerate(vids):
        step(f"watching your video {i + 1}/{len(vids)}", 0.04 + 0.05 * i / len(vids))
        known.append(footage.analyze(m["file"], m.get("note", ""), os.path.join(job_dir, "media", f"{i:02d}.json"), log))
    source = {k["file"]: v["file"] for k, v in zip(known, vids)}
    has_sound = {k["file"]: k["audio"] for k in known}

    pl = read_json(os.path.join(job_dir, "plan.json"))
    if not pl:
        step("writing the script", 0.1)
        if req.get("model"):
            log(f"script model: {req['model']}")
        pl = planner.make(cr, seconds, req["notes"], log, model=req.get("model") or "", media=known,
                          catalogue=footage.catalogue(known))
        write_json(os.path.join(job_dir, "plan.json"), pl)
        log("plan: " + planner.summary(pl))
        planned = sum(s["seconds"] for s in pl["scenes"]) + 10
        if seconds and not req.get("url") and planned < seconds * 0.85:
            log(f"note: your videos fill about {planned:.0f} s of the {seconds} s asked for; add a website or more "
                "footage for a longer video")

    vdir = os.path.join(job_dir, "voice")
    os.makedirs(vdir, exist_ok=True)
    texts = [pl["intro"]["narration"]] + [s["narration"] for s in pl["scenes"]] + [pl["outro"]["narration"]]
    known_voice = read_json(os.path.join(vdir, "voice.json"), {}).get("lines") or {}
    vinfo = {"voice": req["voice"], "secs": [], "wavs": [], "lines": {}}
    for i, t in enumerate(texts):         # one WAV per line, kept by voice and words: a change redoes only its lines
        key = _key(req["voice"], t)
        wav = os.path.join(vdir, f"line_{key}.wav")
        if key in known_voice and (not known_voice[key] or os.path.exists(wav)):
            secs_i = known_voice[key]
        else:
            step(f"narration {i + 1}/{len(texts)}", 0.2 + 0.15 * i / len(texts))
            secs_i = voice.speak(req["voice"], t, wav)
        vinfo["lines"][key] = secs_i
        vinfo["secs"].append(secs_i)
        vinfo["wavs"].append(wav if secs_i else None)
    write_json(os.path.join(vdir, "voice.json"), vinfo)
    secs = assemble.durations(pl, vinfo["secs"])

    cdir = os.path.join(job_dir, "clips")
    os.makedirs(cdir, exist_ok=True)
    cursor = req.get("cursor") or "arrow"
    hero = os.path.join(cdir, "hero.png")
    # each segment's file is named by everything that shapes it, so a revised plan reuses what did not change
    keys = [_key("card", pl["title"], pl.get("tagline", ""), secs[0])]
    keys += [_key(s, secs[i + 1], "" if "video" in s else cursor) for i, s in enumerate(pl["scenes"])]
    keys.append(_key("end", pl["outro"].get("call_to_action"), pl["url"], pl["title"], secs[-1]))
    clips = [os.path.join(cdir, f"seg_{i:03d}_{k}.mp4") for i, k in enumerate(keys)]
    own = [None] * len(secs)                # the sound of the owner's video shown in a segment
    for i, s in enumerate(pl["scenes"]):
        if "video" in s and has_sound.get(s["video"]):
            own[i + 1] = clips[i + 1][:-4] + "_own.wav"
    done = lambda i: os.path.exists(clips[i]) and (not own[i] or os.path.exists(own[i]))
    todo = [i for i in range(len(clips)) if not done(i)]
    if todo:
        if len(todo) < len(clips):
            log(f"redoing {len(todo)} of {len(clips)} segments; the rest are unchanged")
        from .record import Recorder
        rec = Recorder(cdir, log, cursor)
        try:
            if not os.path.exists(hero):
                if req.get("url"):
                    rec.hero(req["url"], hero)
                else:                       # no website: a frame of the first video behind the title cards
                    first = next(s for s in pl["scenes"] if "video" in s)
                    footage.frame_png(source[first["video"]], (first["from"] + first["to"]) / 2, hero)
            for n, i in enumerate(x for x in todo if 0 < x < len(clips) - 1):
                s = pl["scenes"][i - 1]
                step(f"{'cutting' if 'video' in s else 'recording'} scene {i}/{len(pl['scenes'])}",
                     0.35 + 0.45 * n / len(todo))
                if "video" in s:
                    cap = ""
                    if s["caption"]:
                        cap = clips[i][:-4] + "_cap.png"
                        rec.caption_png(s["caption"], cap)
                    footage.cut(source[s["video"]], s["from"], secs[i], clips[i], own[i] or "", cap)
                else:
                    rec.scene(s, secs[i], clips[i])
            if not os.path.exists(clips[0]):
                rec.card("", pl["title"], pl.get("tagline", ""), hero, secs[0], clips[0])
            if not os.path.exists(clips[-1]):
                rec.card("", pl["outro"].get("call_to_action") or pl["url"] or pl["title"], pl["url"], hero,
                         secs[-1], clips[-1])
        finally:
            rec.close()
    keep = {os.path.basename(c)[:-4] for c in clips}
    for f in os.listdir(cdir):              # segments of an older plan (clips, their sound and caption images)
        if f.startswith("seg_") and f.split(".")[0].removesuffix("_own").removesuffix("_cap") not in keep:
            os.unlink(os.path.join(cdir, f))

    mix = os.path.join(job_dir, "soundtrack.wav")
    mix_key = _key(vinfo["wavs"], secs, own, req.get("music") or "")
    if not os.path.exists(mix) or read_json(os.path.join(job_dir, "soundtrack.json"), {}).get("key") != mix_key:
        step("mixing the soundtrack", 0.82)
        assemble.soundtrack(job_dir, vinfo["wavs"], secs, req.get("music") or None, mix, own)
        write_json(os.path.join(job_dir, "soundtrack.json"), {"key": mix_key})
    log(f"ready to edit: {len(clips)} clips, {sum(secs):.1f} s")
    ready = {"plan": pl, "clips": clips, "mix": mix, "secs": secs, "name": _name(job_dir, pl, req)}
    write_json(os.path.join(job_dir, "ready.json"), ready)
    return ready


def _key(*parts) -> str:
    """A short fingerprint of what shapes a file."""
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


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
        try:
            res = resolve_edit.edit(job_dir, ready["name"], ready["clips"], ready["mix"],
                                    [s["caption"] for s in ready["plan"]["scenes"]], job_dir, log, exports)
        finally:
            resolve_edit.close_if_started(log)
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
