"""The shot list: a model reads the crawl and/or the owner's own videos and writes the video, scene by scene,
fitted to the length and notes.

A plan is JSON, in the shape of the hand-made promos (title card, problem card, scenes, closing card):
{"title" (the title card's headline), "tagline" (its subline), "problem": {"statement", "solution"},
 "intro": {"narration"}, "outro": {"narration", "call_to_action" (the closing line), "small"},
 "scenes": [{"url", "captions": [one or two full sentences], "caption" (the first), "narration", "seconds",
             "actions": [{"do": "scroll", "to": "<heading text>|top|bottom|0.0-1.0"},
                         {"do": "type", "into": "<field placeholder or label>", "text": "...", "enter": true},
                         {"do": "hover", "text": "<visible text>"},
                         {"do": "click", "text": "<visible text>"},
                         {"do": "pause", "seconds": n}]},
            {"video": "<file>", "from": s, "to": s, "sound": "keep"|"voice", "captions", "narration", "seconds"}]}

A scene with "video" plays part of one of the owner's videos instead of the site. With a site and videos, the
videos' scenes keep their length and the site's scenes stretch to fill the rest of the time.
"""

import json
import os
from typing import Dict, List, Optional

from . import llm
from .util import is_auto, words

WORDS_PER_SECOND = 2.4      # a calm narration pace

SYSTEM = """You write promotional product videos as a JSON shot list, in the style of a polished product demo: a
title card, a card stating the problem the product solves, 6 to 10 short scenes that each show one feature working
on the real site, and a closing card. You may get a crawl of a website (pages, headings, buttons, text fields), the
owner's own videos (with what is on screen and what is said, by time), or both. A browser plays each website scene
on the real site (sped up past the waiting), and a video scene plays the chosen part of the owner's video.

The cards:
- "title": the headline, 5 to 10 words saying what the product does for the viewer. "tagline": one plain sentence
  under it.
- "problem": {"statement": the pain in one or two short sentences, concrete ("Card prices, printings and decks live
  on five different sites."), "solution": one short sentence on how this product fixes it}.
- "outro": {"call_to_action": a short closing line, "small": a short note such as "Free to use." if the site says so}.

The scenes:
- One idea per scene, 6 to 12 seconds each.
- Show the product doing something, with 1 to 3 steps per scene: type a realistic example for THIS product into one
  of its text fields ("type", only when the crawl lists text fields for that page, using that exact field name), open
  tabs and filters ("click"), point at results ("hover"), scroll to the section that proves the point ("scroll" to a
  heading of that page). Prefer states full of real content.
- Never show a page footer, a legal notice, an empty state or a "sign in" / "needs an account" wall.
- "captions": one full sentence of 8 to 14 words stating what the product does for the viewer, as a fact they can
  see on screen, with real names and numbers from that page. Never describe the steps (no "click", "scroll", "hover",
  "type" in a caption). For a card-price site, say "Every printing of a card, with today's price from three stores."
  A scene longer than 8 seconds may have a second caption for its second beat.
- Only use URLs exactly as the crawl lists them (no #anchors), and only headings, button/link text and field names that
  the crawl shows on that page. The examples here show the shape only: never copy their words.
- Never click anything that logs in, buys, deletes, submits a form or leaves the site.
- "narration": what a narrator says over the scene, spoken English, warm and concrete, no URLs read aloud, no "In this
  video". The video must work without it too, so the captions carry the facts.
- Video scenes: "video" is the file name exactly as given, "from"/"to" are seconds inside that video. Pick the
  moments that matter. "sound": "keep" when the video's own sound must be heard (someone speaking, a demo with sound;
  then the narration is empty), "voice" when the narrator talks over it.
Reply with only the JSON object."""

SITE_SCENE = ('{"url": "...", "captions": ["A full sentence stating what the viewer sees, with real names and numbers."], '
              '"narration": "...", "seconds": 9, "actions": [{"do": "type", "into": "<a text field of this page>", '
              '"text": "<a realistic example>", "enter": true}, {"do": "scroll", "to": "<a heading of this page>"}, '
              '{"do": "hover", "text": "<a button of this page>"}]}')
VIDEO_SCENE = ('{"video": "demo.mp4", "from": 12, "to": 27, "sound": "voice", "captions": ["A full sentence."], '
               '"narration": "..."}')


def schema(site: bool, videos: bool) -> str:
    kinds = ",\n             ".join(([SITE_SCENE] if site else []) + ([VIDEO_SCENE] if videos else []))
    return ('{"title": "...", "tagline": "...",\n "problem": {"statement": "...", "solution": "..."},\n'
            ' "intro": {"narration": "..."},\n'
            f' "scenes": [{kinds}],\n "outro": {{"narration": "...", "call_to_action": "...", "small": "..."}}}}')


def _crawl_text(crawl: Dict) -> str:
    out = []
    for p in crawl["pages"]:
        out.append(f"PAGE {p['url']}\ntitle: {p.get('title')}\ndescription: {p.get('description')}")
        out.append("headings: " + " | ".join(f"{h['text']} (at {h['at']})" for h in p.get("headings", [])))
        out.append("buttons/links: " + " | ".join(p.get("buttons", [])[:30]))
        if p.get("inputs"):
            out.append("text fields: " + " | ".join(p["inputs"]))
        out.append("text: " + (p.get("text") or "")[:1200])
    return "\n".join(out)[:24000]


def prompt(crawl: Optional[Dict], seconds: Optional[int], notes: Optional[str], media: Optional[List[Dict]] = None,
           catalogue: str = "") -> str:
    media = media or []
    site = bool(crawl and crawl.get("pages"))
    if seconds:
        body = max(10, seconds - 15)
        n = max(2, round(body / 10))
        per = max(6, int((body / n - 1.6) * WORDS_PER_SECOND))      # a scene's narration leaves a breath each side
        target = (f"The whole video must last about {seconds} seconds: the opening cards about 10 seconds and the "
                  f"closing card about 5, so about {n} scenes adding up to {body} seconds. The narration sets the pace: "
                  f"a scene can never be shorter than its narration, so keep each scene's narration to at most {per} "
                  f"words, the intro narration to 15 words and the outro to 10. Count the words.")
    else:
        target = ("Choose the length that suits the material: usually 75 to 120 seconds, longer only for a big site "
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


ACTIONS = ("scroll", "hover", "click", "pause", "type")


def _action(a) -> Optional[Dict]:
    """One step, from the ways models write it: {"do": "scroll", ...}, {"action": ...}, {"type": "scroll", ...}, or
    "scroll to Pricing"."""
    if isinstance(a, str):
        verb, _, rest = a.strip().partition(" ")
        rest = rest.strip()
        if verb.lower() not in ACTIONS:
            return None
        verb = verb.lower()
        if verb == "scroll":
            return {"do": "scroll", "to": rest.removeprefix("to ").strip() or "bottom"}
        return {"do": verb, "text": rest.removeprefix("on ").strip()} if rest else None
    if not isinstance(a, dict):
        return None
    do = a.get("do") or a.get("action")
    if do not in ACTIONS and a.get("type") in ACTIONS and a.get("type") != "type":
        do = a["type"]
    if do not in ACTIONS:
        return None
    out = {k: a[k] for k in ("to", "text", "seconds", "into", "enter") if k in a}
    out["do"] = do
    if do == "scroll" and not out.get("to"):
        out["to"] = out.pop("text", "") or "bottom"
    if do in ("hover", "click") and not out.get("text"):
        return None
    if do == "type" and not (out.get("into") and out.get("text")):
        return None
    return out


def _on_page(a: Dict, page: Dict) -> bool:
    """Whether a step points at something the crawl saw on its page (a crawl without the lists allows anything)."""
    if not page or a["do"] == "pause":
        return True
    have = lambda xs, t: any(t in x.lower() or x.lower() in t for x in xs if x)
    if a["do"] == "type":
        return "inputs" not in page or have(page["inputs"], str(a["into"]).lower().strip())
    heads = [h["text"] if isinstance(h, dict) else h for h in page.get("headings") or []]
    if a["do"] == "scroll":
        to = str(a["to"]).lower().strip()
        return to in ("top", "bottom") or _is_num(to) or "headings" not in page or have(heads, to)
    if "buttons" not in page and "headings" not in page:
        return True
    return have((page.get("buttons") or []) + heads, str(a["text"]).lower().strip())


def _is_num(t: str) -> bool:
    try:
        float(t)
        return True
    except ValueError:
        return False


def _captions(s: Dict) -> List[str]:
    """A scene's captions: up to two full sentences (older plans had one short "caption")."""
    caps = s.get("captions")
    if isinstance(caps, str):
        caps = [caps]
    if not isinstance(caps, list) or not any(str(c).strip() for c in caps):
        caps = [s.get("caption") or ""]
    return [str(c).strip()[:120] for c in caps if str(c).strip()][:2]


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
    caps = _captions(s)
    return {"video": m["file"], "from": round(a, 2), "to": round(b, 2), "sound": sound, "captions": caps,
            "caption": caps[0] if caps else "", "narration": narration, "seconds": round(b - a, 2)}


def _repeats(v: Dict, scenes: List[Dict]) -> bool:
    """Whether most of this moment was already shown (a model short of footage tends to show it twice)."""
    for s in scenes:
        if s.get("video") == v["video"]:
            both = min(s["to"], v["to"]) - max(s["from"], v["from"])
            if both > 0.5 * min(s["seconds"], v["seconds"]):
                return True
    return False


def check(plan: Dict, crawl: Optional[Dict], seconds: Optional[int], media: Optional[List[Dict]] = None,
          fill_missing: bool = True) -> Dict:
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
        url = str(s.get("url") or start).split("#")[0]
        if url.rstrip("/") not in known:
            url = start
        page = next((p for p in pages if p["url"].rstrip("/") == url.rstrip("/")), {})
        narration = str(s.get("narration") or "").strip()
        need = len(words(narration)) / WORDS_PER_SECOND + 1.0
        secs = max(4.0, min(60.0, _num(s.get("seconds"), need), need + 6))
        acts = []
        for a in (s.get("actions") or [])[:8]:
            a = _action(a)
            if a and _on_page(a, page):
                acts.append(a)
        if not acts:
            # a scene with nothing to do would be a still picture: move on down the page instead (scenes on the same
            # page carry on where the last one stopped)
            before = sum(1 for x in scenes if x.get("url") == url)
            acts = [{"do": "scroll", "to": round(min(0.9, 0.3 * (before + 1)), 2)}]
        caps = _captions(s)
        scenes.append({"url": url, "captions": caps, "caption": caps[0] if caps else "", "narration": narration,
                       "seconds": round(max(secs, need), 2), "actions": acts})
    used = {s["video"] for s in scenes if "video" in s}
    for i, m in enumerate(media if fill_missing else []):   # a video the model left out still goes in, spread out
        if m["file"] not in used:
            v = _video_scene({"video": m["file"], "from": 0, "to": min(m["seconds"], 45.0),
                              "sound": "keep" if m.get("audio") else "voice",
                              "caption": (m.get("note") or "")[:40]}, media)
            scenes.insert(min(len(scenes), round((i + 1) * len(scenes) / (len(media) + 1))), v)
    if not scenes:
        raise ValueError("no scenes")
    first = os.path.splitext(media[0]["file"])[0] if media else ""
    problem = plan.get("problem") if isinstance(plan.get("problem"), dict) else {}
    out = {"title": str(plan.get("title") or (pages[0].get("title") if pages else first) or "")[:90],
           "tagline": str(plan.get("tagline") or "")[:140],
           "problem": {"statement": str(problem.get("statement") or "").strip()[:180],
                       "solution": str(problem.get("solution") or "").strip()[:140]},
           "intro": {"narration": str((plan.get("intro") or {}).get("narration") or "")},
           "outro": {"narration": str((plan.get("outro") or {}).get("narration") or ""),
                     "call_to_action": str((plan.get("outro") or {}).get("call_to_action") or start)[:90],
                     "small": str((plan.get("outro") or {}).get("small") or "")[:80]},
           "url": start, "scenes": scenes}
    if seconds:
        _fit(out, seconds, media)
    return out


def _fit(plan: Dict, seconds: int, media: Optional[List[Dict]] = None) -> None:
    """Stretch or shrink scene times toward the target; never below what the narration needs. Website scenes take
    up the slack and the owner's footage keeps its length; with no website, more of each video is shown instead (as
    far as the videos go)."""
    goal = max(10, seconds - 15)              # the opening and closing cards (about 15 s) do not stretch
    site = [s for s in plan["scenes"] if "video" not in s]
    vids = [s for s in plan["scenes"] if "video" in s]
    fixed = sum(s["seconds"] for s in vids)
    if site:
        flex = sum(s["seconds"] for s in site)
        k = max(4.0 * len(site), goal - fixed) / flex if flex > 0 else 1.0
        cap = max(24.0, 1.5 * (goal - fixed) / len(site))     # short scenes read best, unless the length needs more
        for s in site:
            need = len(words(s["narration"])) / WORDS_PER_SECOND + 1.0
            s["seconds"] = round(max(need, min(cap, s["seconds"] * k)), 2)
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
