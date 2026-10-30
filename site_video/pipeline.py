"""One video, start to finish, in a job folder. Each stage keeps its output, so a stopped job picks up where it was.

prep(): crawl -> plan -> narration -> recording -> soundtrack   (several jobs can do this at once)
edit(): Resolve (or ffmpeg) -> <name>.mp4                         (one at a time: a Resolve renders one thing)
"""

import hashlib
import json
import os
import re
from typing import Callable, Dict, List, Optional

from . import assemble, brand, cards, deliver, explore, media as footage, plan as planner, session, voice
from . import review as checker
from .record import VERSION as REC_VERSION
from .util import Log, is_auto, parse_length, read_json, write_json

EDITORS = ("auto", "resolve", "ffmpeg")
MAX_MEDIA = 12
CURSORS = ("dot", "arrow", "hand", "ring", "none")    # the cursor drawn on website scenes (record.py)
CARDS_VERSION = 1     # bump when the cards or captions would be drawn differently


def _cursor(c) -> str:
    c = str(c or "dot").strip().lower()
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
            name: str = "", model: str = "", deliverables="video", media=None, cursor: str = "dot",
            changes: bool = False) -> Dict:
    """A checked job request (raises ValueError with a readable reason). A website link, the owner's videos
    (`media`), or both: with both, website scenes fill the length around the videos. `changes`: it is your own site,
    so the video may press buttons that save things (never delete, buy or sign out)."""
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
            "deliverables": deliver.parse(deliverables), "media": media, "cursor": _cursor(cursor),
            "changes": bool(changes) and bool(url)}


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
        step("exploring the site", 0.05)
        named = [u for u in re.findall(r"https?://[^\s)\]>\"']+", req.get("notes") or "")
                 if explore._same_site(u, req["url"])]
        signed = session.state_for(req["url"])
        if signed:
            log(f"signed in to {session.host(req['url'])} (saved sign-in)")
        cr = explore.explore(req["url"], log, brand_dir=job_dir, seeds=named, session=signed)
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
                          catalogue=footage.catalogue(known), changes=bool(req.get("changes")))
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
    cursor = req.get("cursor") or "dot"
    look = dict(brand.DEFAULT, **((cr or {}).get("brand") or {}))
    title_s = secs[0] * assemble.TITLE_S / (assemble.TITLE_S + assemble.PROBLEM_S) if assemble.opening(pl) else 0
    # each segment's file is named by everything that shapes it, so a revised plan reuses what did not change
    keys = [_key("open", pl["title"], pl.get("tagline", ""), pl.get("problem"), look, secs[0], CARDS_VERSION)]
    shot = lambda s: {k: v for k, v in s.items() if k not in ("caption", "captions", "narration")}   # the picture alone
    keys += [_key(shot(s), secs[i + 1], "" if "video" in s else (cursor, look["primary"], look.get("zoom", 1.0), REC_VERSION,
                                                       bool(session.state_for(req.get("url") or "")),
                                                       bool(req.get("changes"))))
             for i, s in enumerate(pl["scenes"])]
    keys.append(_key("close", pl["outro"].get("call_to_action"), pl["outro"].get("small"), pl["url"], look, secs[-1],
                     CARDS_VERSION))
    clips = [os.path.join(cdir, f"seg_{i:03d}_{k}.mp4") for i, k in enumerate(keys)]
    own = [None] * len(secs)                # the sound of the owner's video shown in a segment
    for i, s in enumerate(pl["scenes"]):
        if "video" in s and has_sound.get(s["video"]):
            own[i + 1] = clips[i + 1][:-4] + "_own.wav"
    caps = assemble.caption_times(pl, secs)
    for c in caps:
        c["png"] = os.path.join(cdir, f"cap_{_key(c['text'], look, CARDS_VERSION)}.png")
    done = lambda i: os.path.exists(clips[i]) and (not own[i] or os.path.exists(own[i]))
    todo = [i for i in range(len(clips)) if not done(i)]
    if todo or not all(os.path.exists(c["png"]) for c in caps):
        if len(todo) < len(clips):
            log(f"redoing {len(todo)} of {len(clips)} segments; the rest are unchanged")
        from .record import Recorder
        rec = Recorder(cdir, log, cursor, look["primary"], look.get("zoom", 1.0),
                       session.state_for(req.get("url") or ""), bool(req.get("changes")))
        try:
            paint = cards.painter(rec.browser, req.get("url") or "", look, job_dir, log)
            for n, i in enumerate(x for x in todo if 0 < x < len(clips) - 1):
                s = pl["scenes"][i - 1]
                step(f"{'cutting' if 'video' in s else 'recording'} scene {i}/{len(pl['scenes'])}",
                     0.35 + 0.45 * n / len(todo))
                if "video" in s:
                    footage.cut(source[s["video"]], s["from"], secs[i], clips[i], own[i] or "")
                else:
                    speed = rec.scene(s, secs[i], clips[i])
                    if speed >= 2.39:
                        log(f"  scene {i} has more going on than its {secs[i]:.1f} s; give it more time or fewer steps")
            step("drawing the cards and captions", 0.8)
            if not os.path.exists(clips[0]):
                pngs = [paint.title(pl["title"], pl.get("tagline", ""), clips[0][:-4] + "_title.png")]
                if assemble.opening(pl):
                    pngs.append(paint.problem(pl["problem"]["statement"], pl["problem"].get("solution", ""),
                                              clips[0][:-4] + "_problem.png"))
                cards.card_clip(pngs, secs[0], clips[0], title_s)
            if not os.path.exists(clips[-1]):
                png = paint.close(pl["outro"].get("call_to_action") or pl["title"], pl["url"] or "",
                                  pl["outro"].get("small", ""), clips[-1][:-4] + "_close.png")
                cards.card_clip([png], secs[-1], clips[-1])
            for c in caps:
                if not os.path.exists(c["png"]):
                    paint.caption(c["text"], c["png"])
        finally:
            rec.close()
    keep = {os.path.basename(c)[:-4] for c in clips} | {os.path.basename(c["png"]) for c in caps}
    for f in os.listdir(cdir):              # files of an older plan (clips, their sound, card and caption images)
        stem = f.split(".")[0]
        for tail in ("_own", "_title", "_problem", "_close"):
            stem = stem.removesuffix(tail)
        if (f.startswith("seg_") and stem not in keep) or (f.startswith("cap_") and f not in keep):
            os.unlink(os.path.join(cdir, f))

    mix = os.path.join(job_dir, "soundtrack.wav")
    mix_key = _key(vinfo["wavs"], secs, own, req.get("music") or "")
    if not os.path.exists(mix) or read_json(os.path.join(job_dir, "soundtrack.json"), {}).get("key") != mix_key:
        step("mixing the soundtrack", 0.82)
        assemble.soundtrack(job_dir, vinfo["wavs"], secs, req.get("music") or None, mix, own)
        write_json(os.path.join(job_dir, "soundtrack.json"), {"key": mix_key})
    log(f"ready to edit: {len(clips)} clips, {sum(secs):.1f} s")
    ready = {"plan": pl, "clips": clips, "mix": mix, "secs": secs, "name": _name(job_dir, pl, req),
             "captions": [{k: c[k] for k in ("png", "start", "end", "text")} for c in caps]}
    if checker.enabled() and pl["scenes"]:
        # does each recorded scene show what the script and the voice say? Failed scenes are rewritten by the
        # script model from what was really recorded, and made again, once
        step("checking the scenes against the script", 0.88)
        try:
            verdicts = checker.review(job_dir, pl, clips, secs, log)
            ready["review"] = verdicts
            change = checker.fix_request(verdicts)
            if change and not req.get("_reviewed"):
                from . import revise
                step("fixing the scenes that did not match", 0.9)
                fixed = revise.suggest(job_dir, change, model=req.get("model") or "", log=log)
                log("fix: " + "; ".join(fixed["changes"]))
                revise.apply(job_dir, fixed["plan"])
                return prep(job_dir, dict(req, _reviewed=True), step)
        except Exception as e:
            log(f"review skipped: {type(e).__name__}: {e}")
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
            res = resolve_edit.edit(job_dir, ready["name"], ready["clips"], ready["mix"], ready["secs"],
                                    ready.get("captions") or [], job_dir, log, exports)
        finally:
            resolve_edit.close_if_started(log)
    else:
        res = {"video": assemble.edit_ffmpeg(job_dir, ready["clips"], ready["mix"],
                                             os.path.join(job_dir, ready["name"] + ".mp4"), ready["secs"],
                                             ready.get("captions") or [])}
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
