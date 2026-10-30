"""The shot list: a model reads the crawl and writes the video, scene by scene, fitted to the length and notes.

A plan is JSON:
{"title", "tagline", "intro": {"narration"}, "outro": {"narration", "call_to_action"},
 "scenes": [{"url", "caption", "narration", "seconds",
             "actions": [{"do": "scroll", "to": "<heading text>|top|bottom|0.0-1.0"},
                         {"do": "hover", "text": "<visible text>"},
                         {"do": "click", "text": "<visible text>"},
                         {"do": "pause", "seconds": n}]}]}
"""

import json
from typing import Dict, Optional

from . import llm
from .util import is_auto, words

WORDS_PER_SECOND = 2.4      # a calm narration pace

SYSTEM = """You write promotional website walkthrough videos. You get a crawl of a website (pages, headings,
buttons) and write a shot list as JSON. A browser will play each scene on the real site while a narrator reads your
narration, with your caption as a lower-third title. Rules:
- Only use URLs from the crawl. Only point at headings and button/link text that appear in the crawl for that page.
- Each scene shows one idea. Its actions must fit its seconds: a scroll takes about 2 seconds, a hover 1.5.
- Narration is spoken English, warm and concrete, no lists, no URLs read aloud, no "In this video".
- Captions are 2 to 6 words.
- Never click anything that logs in, buys, deletes, submits a form or leaves the site.
Reply with only the JSON object."""

SCHEMA = """{"title": "...", "tagline": "...",
 "intro": {"narration": "..."},
 "scenes": [{"url": "...", "caption": "...", "narration": "...", "seconds": 8,
             "actions": [{"do": "scroll", "to": "Heading text"}, {"do": "hover", "text": "Button text"}]}],
 "outro": {"narration": "...", "call_to_action": "..."}}"""


def _crawl_text(crawl: Dict) -> str:
    out = []
    for p in crawl["pages"]:
        out.append(f"PAGE {p['url']}\ntitle: {p.get('title')}\ndescription: {p.get('description')}")
        out.append("headings: " + " | ".join(f"{h['text']} (at {h['at']})" for h in p.get("headings", [])))
        out.append("buttons/links: " + " | ".join(p.get("buttons", [])[:30]))
        out.append("text: " + (p.get("text") or "")[:1200])
    return "\n".join(out)[:24000]


def prompt(crawl: Dict, seconds: Optional[int], notes: Optional[str]) -> str:
    if seconds:
        target = (f"The whole video must last about {seconds} seconds: intro and outro about 5 seconds each, scene "
                  f"seconds adding up to about {max(10, seconds - 10)}. Total narration about "
                  f"{int(seconds * WORDS_PER_SECOND)} words, spread over the scenes in proportion to their seconds.")
    else:
        target = ("Choose the length that suits this site: usually 60 to 120 seconds, longer only for a big site. "
                  f"Narration at about {WORDS_PER_SECOND} words a second of scene.")
    want = ("Requirements from the person who asked (follow them exactly):\n" + notes.strip()) if not is_auto(notes) \
        else "No special requirements: show what the site is for, its best features, and how to get started."
    return f"{target}\n\n{want}\n\nReply in this shape:\n{SCHEMA}\n\nThe crawl:\n{_crawl_text(crawl)}"


def make(crawl: Dict, seconds: Optional[int], notes: Optional[str], log=print) -> Dict:
    last = None
    for attempt in range(3):
        reply = llm.chat(SYSTEM, prompt(crawl, seconds, notes) + (
            f"\n\nYour last reply could not be used ({last}). Reply with only valid JSON." if last else ""))
        try:
            return check(llm.json_from(reply), crawl, seconds)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:300]
            log(f"plan attempt {attempt + 1} unusable: {last}")
    raise RuntimeError(f"the model did not write a usable plan ({last})")


def check(plan: Dict, crawl: Dict, seconds: Optional[int]) -> Dict:
    """Validate and repair a plan: known URLs only, sane timings, text that fits."""
    known = {p["url"].rstrip("/") for p in crawl["pages"]}
    start = crawl["pages"][0]["url"]
    scenes = []
    for s in plan.get("scenes") or []:
        url = str(s.get("url") or start)
        if url.rstrip("/") not in known:
            url = start
        narration = str(s.get("narration") or "").strip()
        need = len(words(narration)) / WORDS_PER_SECOND + 1.0
        secs = max(4.0, min(60.0, float(s.get("seconds") or need), need + 6))
        acts = []
        for a in (s.get("actions") or [])[:8]:
            if isinstance(a, dict) and a.get("do") in ("scroll", "hover", "click", "pause"):
                acts.append({k: a[k] for k in ("do", "to", "text", "seconds") if k in a})
        scenes.append({"url": url, "caption": str(s.get("caption") or "")[:60], "narration": narration,
                       "seconds": round(max(secs, need), 2), "actions": acts})
    if not scenes:
        raise ValueError("no scenes")
    out = {"title": str(plan.get("title") or crawl["pages"][0].get("title") or "")[:80],
           "tagline": str(plan.get("tagline") or "")[:120],
           "intro": {"narration": str((plan.get("intro") or {}).get("narration") or "")},
           "outro": {"narration": str((plan.get("outro") or {}).get("narration") or ""),
                     "call_to_action": str((plan.get("outro") or {}).get("call_to_action") or start)[:80]},
           "url": start, "scenes": scenes}
    if seconds:
        _fit(out, seconds)
    return out


def _fit(plan: Dict, seconds: int) -> None:
    """Stretch or shrink scene times toward the target; never below what the narration needs."""
    scenes = sum(s["seconds"] for s in plan["scenes"])
    if scenes <= 0:
        return
    k = max(10, seconds - 10) / scenes        # the intro and outro (about 10 s) do not stretch
    for s in plan["scenes"]:
        need = len(words(s["narration"])) / WORDS_PER_SECOND + 1.0
        s["seconds"] = round(max(need, min(90.0, s["seconds"] * k)), 2)


def summary(plan: Dict) -> str:
    total = sum(s["seconds"] for s in plan["scenes"])
    return f"{len(plan['scenes'])} scenes, about {round(total + 10)} s: " + json.dumps(
        [s["caption"] for s in plan["scenes"]])[:300]
