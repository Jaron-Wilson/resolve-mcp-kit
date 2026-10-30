"""The shot list: a model reads the crawl and/or the owner's own videos and writes the video, scene by scene,
fitted to the length and notes.

A plan is JSON:
{"title", "tagline", "intro": {"narration"}, "outro": {"narration", "call_to_action"},
 "scenes": [{"url", "caption", "narration", "seconds",
             "actions": [{"do": "scroll", "to": "<heading text>|top|bottom|0.0-1.0"},
                         {"do": "hover", "text": "<visible text>"},
                         {"do": "click", "text": "<visible text>"},
                         {"do": "pause", "seconds": n}]},
            {"video": "<file>", "from": s, "to": s, "sound": "keep"|"voice", "caption", "narration", "seconds"}]}

A scene with "video" plays part of one of the owner's videos instead of the site. With a site and videos, the
videos' scenes keep their length and the site's scenes stretch to fill the rest of the time.
"""

import json
import os
from typing import Dict, List, Optional

from . import llm
from .util import is_auto, words

WORDS_PER_SECOND = 2.4      # a calm narration pace

SYSTEM = """You write promotional videos as a JSON shot list. You may get a crawl of a website (pages, headings,
buttons), the owner's own videos (with what is on screen and what is said, by time), or both. A browser plays each
website scene on the real site, and a video scene plays the chosen part of the owner's video, while a narrator reads
your narration, with your caption as a lower-third title. Rules:
- Only use URLs from the crawl. Only point at headings and button/link text that appear in the crawl for that page.
- Each scene shows one idea. A website scene's actions must fit its seconds: a scroll takes about 2 seconds, a hover 1.5.
- Video scenes: "video" is the file name exactly as given, "from"/"to" are seconds inside that video. Pick the
  moments that matter. "sound": "keep" when the video's own sound must be heard (someone speaking, a demo with sound;
  then the narration is empty), "voice" when the narrator talks over it.
- Narration is spoken English, warm and concrete, no lists, no URLs read aloud, no "In this video".
- Captions are 2 to 6 words.
- Never click anything that logs in, buys, deletes, submits a form or leaves the site.
Reply with only the JSON object."""

SITE_SCENE = ('{"url": "...", "caption": "...", "narration": "...", "seconds": 8, '
              '"actions": [{"do": "scroll", "to": "Heading text"}, {"do": "hover", "text": "Button text"}]}')
VIDEO_SCENE = '{"video": "demo.mp4", "from": 12, "to": 27, "sound": "voice", "caption": "...", "narration": "..."}'


def schema(site: bool, videos: bool) -> str:
    kinds = ",\n             ".join(([SITE_SCENE] if site else []) + ([VIDEO_SCENE] if videos else []))
    return ('{"title": "...", "tagline": "...",\n "intro": {"narration": "..."},\n'
            f' "scenes": [{kinds}],\n "outro": {{"narration": "...", "call_to_action": "..."}}}}')


def _crawl_text(crawl: Dict) -> str:
    out = []
    for p in crawl["pages"]:
        out.append(f"PAGE {p['url']}\ntitle: {p.get('title')}\ndescription: {p.get('description')}")
        out.append("headings: " + " | ".join(f"{h['text']} (at {h['at']})" for h in p.get("headings", [])))
        out.append("buttons/links: " + " | ".join(p.get("buttons", [])[:30]))
        out.append("text: " + (p.get("text") or "")[:1200])
    return "\n".join(out)[:24000]


def prompt(crawl: Optional[Dict], seconds: Optional[int], notes: Optional[str], media: Optional[List[Dict]] = None,
           catalogue: str = "") -> str:
    media = media or []
    site = bool(crawl and crawl.get("pages"))
    if seconds:
        target = (f"The whole video must last about {seconds} seconds: intro and outro about 5 seconds each, scene "
                  f"seconds adding up to about {max(10, seconds - 10)}. Total narration about "
                  f"{int(seconds * WORDS_PER_SECOND)} words, spread over the scenes in proportion to their seconds.")
    else:
        target = ("Choose the length that suits the material: usually 60 to 120 seconds, longer only for a big site "
                  f"or long videos. Narration at about {WORDS_PER_SECOND} words a second of scene.")
    footage = sum(m["seconds"] for m in media)
    if media and site:
        target += (f"\nUse every one of the owner's videos at least once (their best moments; {footage:.0f} s of "
                   "footage in all) and fill the rest of the time with website scenes. Put the videos where they fit "
                   "the story, not all at the start.")
    elif media:
        target += (f"\nThere is no website: every scene is a video scene. The owner's videos last {footage:.0f} s in "
                   "all; use every one, and never show a moment twice. If that is less than the length asked for, "
                   "make the video as long as the footage allows.")
    if not is_auto(notes):
        want = "Requirements from the person who asked (follow them exactly):\n" + notes.strip()
    elif site:
        want = "No special requirements: show what the site is for, its best features, and how to get started."
    else:
        want = "No special requirements: tell the story of what the videos show, best moments first."
    out = f"{target}\n\n{want}\n\nReply in this shape:\n{schema(site, bool(media))}"
    if media:
        out += "\n\nThe owner's videos:\n" + (catalogue or "")[:12000]
    if site:
        out += f"\n\nThe crawl:\n{_crawl_text(crawl)}"
    return out


def make(crawl: Optional[Dict], seconds: Optional[int], notes: Optional[str], log=print, model: str = "",
         media: Optional[List[Dict]] = None, catalogue: str = "") -> Dict:
    last = None
    for attempt in range(3):
        reply = llm.chat(SYSTEM, prompt(crawl, seconds, notes, media, catalogue) + (
            f"\n\nYour last reply could not be used ({last}). Reply with only valid JSON." if last else ""),
            model=model)
        try:
            return check(llm.json_from(reply), crawl, seconds, media)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:300]
            log(f"plan attempt {attempt + 1} unusable: {last}")
    raise RuntimeError(f"the model did not write a usable plan ({last})")


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _video_scene(s: Dict, media: List[Dict]) -> Optional[Dict]:
    want = str(s.get("video") or "").strip()
    m = next((m for m in media if m["file"] == want), None) or \
        next((m for m in media if os.path.splitext(m["file"])[0].lower() == os.path.splitext(want)[0].lower()), None)
    if not m:
        return None
    length = m["seconds"]
    a = max(0.0, min(_num(s.get("from"), 0.0), max(0.0, length - 1.0)))
    b = min(length, _num(s.get("to"), length))
    if b - a < 1.0:
        b = min(length, a + 8.0)
    sound = "keep" if str(s.get("sound") or "").lower() == "keep" and m.get("audio") else "voice"
    narration = "" if sound == "keep" else str(s.get("narration") or "").strip()
    need = len(words(narration)) / WORDS_PER_SECOND + 1.0 if narration else 0.0
    if b - a < need:                        # more to say than the moment lasts: show more of the video
        b = min(length, a + need)
        a = max(0.0, min(a, b - need))
    return {"video": m["file"], "from": round(a, 2), "to": round(b, 2), "sound": sound,
            "caption": str(s.get("caption") or "")[:60], "narration": narration, "seconds": round(b - a, 2)}


def _repeats(v: Dict, scenes: List[Dict]) -> bool:
    """Whether most of this moment was already shown (a model short of footage tends to show it twice)."""
    for s in scenes:
        if s.get("video") == v["video"]:
            both = min(s["to"], v["to"]) - max(s["from"], v["from"])
            if both > 0.5 * min(s["seconds"], v["seconds"]):
                return True
    return False


def check(plan: Dict, crawl: Optional[Dict], seconds: Optional[int], media: Optional[List[Dict]] = None) -> Dict:
    """Validate and repair a plan: known URLs and videos only, sane timings, text that fits, every video used."""
    media = media or []
    pages = (crawl or {}).get("pages") or []
    known = {p["url"].rstrip("/") for p in pages}
    start = pages[0]["url"] if pages else ""
    scenes = []
    for s in plan.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        if s.get("video"):
            v = _video_scene(s, media)
            if v and not _repeats(v, scenes):
                scenes.append(v)
            continue
        if not pages:
            continue
        url = str(s.get("url") or start)
        if url.rstrip("/") not in known:
            url = start
        narration = str(s.get("narration") or "").strip()
        need = len(words(narration)) / WORDS_PER_SECOND + 1.0
        secs = max(4.0, min(60.0, _num(s.get("seconds"), need), need + 6))
        acts = []
        for a in (s.get("actions") or [])[:8]:
            if isinstance(a, dict) and a.get("do") in ("scroll", "hover", "click", "pause"):
                acts.append({k: a[k] for k in ("do", "to", "text", "seconds") if k in a})
        scenes.append({"url": url, "caption": str(s.get("caption") or "")[:60], "narration": narration,
                       "seconds": round(max(secs, need), 2), "actions": acts})
    used = {s["video"] for s in scenes if "video" in s}
    for i, m in enumerate(media):           # a video the model left out still goes in, spread among the scenes
        if m["file"] not in used:
            v = _video_scene({"video": m["file"], "from": 0, "to": min(m["seconds"], 45.0),
                              "sound": "keep" if m.get("audio") else "voice",
                              "caption": (m.get("note") or "")[:40]}, media)
            scenes.insert(min(len(scenes), round((i + 1) * len(scenes) / (len(media) + 1))), v)
    if not scenes:
        raise ValueError("no scenes")
    first = os.path.splitext(media[0]["file"])[0] if media else ""
    out = {"title": str(plan.get("title") or (pages[0].get("title") if pages else first) or "")[:80],
           "tagline": str(plan.get("tagline") or "")[:120],
           "intro": {"narration": str((plan.get("intro") or {}).get("narration") or "")},
           "outro": {"narration": str((plan.get("outro") or {}).get("narration") or ""),
                     "call_to_action": str((plan.get("outro") or {}).get("call_to_action") or start)[:80]},
           "url": start, "scenes": scenes}
    if seconds:
        _fit(out, seconds, media)
    return out


def _fit(plan: Dict, seconds: int, media: Optional[List[Dict]] = None) -> None:
    """Stretch or shrink scene times toward the target; never below what the narration needs. Website scenes take
    up the slack and the owner's footage keeps its length; with no website, more of each video is shown instead (as
    far as the videos go)."""
    goal = max(10, seconds - 10)              # the intro and outro (about 10 s) do not stretch
    site = [s for s in plan["scenes"] if "video" not in s]
    vids = [s for s in plan["scenes"] if "video" in s]
    fixed = sum(s["seconds"] for s in vids)
    if site:
        flex = sum(s["seconds"] for s in site)
        k = max(4.0 * len(site), goal - fixed) / flex if flex > 0 else 1.0
        for s in site:
            need = len(words(s["narration"])) / WORDS_PER_SECOND + 1.0
            s["seconds"] = round(max(need, min(90.0, s["seconds"] * k)), 2)
        return
    lengths = {m["file"]: m["seconds"] for m in (media or [])}
    short = goal - fixed
    while short > 0.05:                       # too short: let each moment run on, in proportion, while it can
        room = [s for s in vids if lengths.get(s["video"], s["to"]) - s["to"] > 0.01]
        if not room:
            break
        share = sum(s["seconds"] for s in room)
        for s in room:
            add = min(lengths.get(s["video"], s["to"]) - s["to"], short * s["seconds"] / share)
            s["to"] = round(s["to"] + add, 2)
            s["seconds"] = round(s["to"] - s["from"], 2)
        short = goal - sum(s["seconds"] for s in vids)


def summary(plan: Dict) -> str:
    total = sum(s["seconds"] for s in plan["scenes"])
    n = sum(1 for s in plan["scenes"] if "video" in s)
    return (f"{len(plan['scenes'])} scenes" + (f" ({n} from your videos)" if n else "") +
            f", about {round(total + 10)} s: " + json.dumps([s["caption"] for s in plan["scenes"]])[:300])
