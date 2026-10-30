"""Changing a video after it is made: edit its script (or describe the change in words), then make it again. Only the
segments whose script changed are recorded, cut or voiced again (pipeline.prep keeps every segment by what shapes
it), so a one-scene fix takes about a minute.

suggest(): a model applies a change in words ("in scene 3, point at the Pro plan instead") to the script, for review.
apply():   check an edited script and make it the job's script; the queue then runs the job again.
"""

import json
import os
import re
from typing import Dict, List

from . import llm, media, plan as planner
from .util import read_json, write_json

SYSTEM = """You revise the shot list of a promotional video. You get the current shot list as JSON, what can be shown
(the website's pages with their headings and buttons, the owner's videos), the person's original brief if they wrote
one, and a change they asked for. Apply exactly that change and keep everything else as it is: the same scenes, words
and order unless the change is about them. When the change says a scene is wrong, make it follow the original brief.
Only use URLs, heading and button text from the website, and video names and times from the videos. Scene actions:
{"do": "scroll", "to": "<heading text>|top|bottom|0.0-1.0"}, {"do": "hover", "text": "<visible text>"},
{"do": "click", "text": "<visible text>"}, {"do": "type", "into": "<a text field>", "text": "...", "enter": true},
{"do": "pause", "seconds": n}. Captions and narration sell the product with what the viewer sees: never describe an
error, an empty, blank or loading page, or a problem with the recording. Unless told below that this is the person's
own site, never click anything that logs in, buys, deletes or submits. Reply with only the whole revised JSON object,
in the same shape."""

# a caption that describes a failure instead of the product (what an over-literal fix once wrote)
FAILURE = re.compile(r"\b(broken|loading|blank|empty|error|failed|not found|no content|nothing (?:is )?shown|"
                     r"does ?n[o']t (?:show|load|work)|no \w+(?: \w+)? (?:listed|found|yet))\b", re.I)


def context(job_dir: str) -> Dict:
    """What a script for this job may point at: the site's pages (headings, buttons) and the owner's videos."""
    cr = read_json(os.path.join(job_dir, "crawl.json")) or {}
    vids = _videos(job_dir)
    return {"pages": [{"url": p["url"], "headings": [h["text"] for h in p.get("headings", [])][:60],
                       "buttons": (p.get("buttons") or [])[:60], "inputs": (p.get("inputs") or [])[:20]}
                      for p in cr.get("pages") or []],
            "videos": [{"file": m["file"], "seconds": m["seconds"], "audio": m["audio"]} for m in vids]}


def _videos(job_dir: str) -> List[Dict]:
    d = os.path.join(job_dir, "media")
    if not os.path.isdir(d):
        return []
    return [read_json(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".json")]


def _request(job_dir: str) -> Dict:
    return (read_json(os.path.join(job_dir, "job.json")) or {}).get("request") or {}


def check(job_dir: str, new: Dict, log=None) -> Dict:
    """An edited script made safe: known pages and videos only, times inside the videos, text that fits. The
    person's own timings are kept (no fitting to the first length), and a video they took out stays out."""
    if not isinstance(new, dict) or not isinstance(new.get("scenes"), list):
        raise ValueError("a script needs a list of scenes")
    cr = read_json(os.path.join(job_dir, "crawl.json"))
    return planner.check(new, cr, None, _videos(job_dir), fill_missing=False,
                         changes=bool(_request(job_dir).get("changes")), log=log)


def _keep_selling(old: Dict, new: Dict, log=print) -> Dict:
    """A scene whose new captions or narration describe a failure ("Broken/loading page...") goes back to how it was:
    a promo never narrates what went wrong."""
    text = lambda s: " ".join([*(s.get("captions") or [s.get("caption") or ""]), s.get("narration") or ""])
    olds = old.get("scenes") or []
    for i, s in enumerate(new.get("scenes") or []):
        if FAILURE.search(text(s)) and not (i < len(olds) and FAILURE.search(text(olds[i]))):
            log(f"  scene {i + 1}: the rewrite described a failure ({FAILURE.search(text(s)).group(0)!r}); kept as it was"
                if i < len(olds) else f"  scene {i + 1}: the rewrite described a failure; left out")
            if i < len(olds):
                new["scenes"][i] = olds[i]
    new["scenes"] = [s for i, s in enumerate(new["scenes"]) if i < len(olds) or not FAILURE.search(text(s))]
    return new


def suggest(job_dir: str, change: str, model: str = "", log=print) -> Dict:
    """{"plan": the script with the change applied, "changes": what differs, in words}. Nothing is saved."""
    change = (change or "").strip()
    if not change:
        raise ValueError("say what to change")
    old = read_json(os.path.join(job_dir, "plan.json"))
    if not old:
        raise ValueError("this job has no script yet")
    vids = _videos(job_dir)
    shown = {k: v for k, v in old.items() if k != "url"}
    # what can be shown first, the change last: a model answers whatever it read last (page text with code in it
    # once got explained instead of the script being revised), so only headings and buttons are given, not page text
    user = ""
    req = _request(job_dir)
    if req.get("notes") and str(req["notes"]).strip().lower() != "auto":
        user += ("The person's original brief for this video:\n--- brief ---\n" + str(req["notes"]).strip()[:6000]
                 + "\n--- end of brief ---\n\n")
    if req.get("changes") and req.get("url"):
        user += planner.MY_SITE + "\n\n"
    pages = context(job_dir)["pages"]
    if pages:
        user += "Website pages that can be shown:\n" + "\n".join(
            f"PAGE {p['url']}\n  headings: {' | '.join(p['headings'])}\n  buttons/links: {' | '.join(p['buttons'])}"
            + (f"\n  text fields: {' | '.join(p['inputs'])}" if p.get("inputs") else "")
            for p in pages)[:12000] + "\n\n"
    if vids:
        user += "The owner's videos:\n" + media.catalogue(vids)[:8000] + "\n\n"
    user += (f"The current shot list:\n{json.dumps(shown, indent=1)}\n\n"
             f"The change, in the person's words (follow it exactly):\n{change[:2000]}\n\n"
             'Reply with only the whole revised shot list: one JSON object that starts with {"title" and has every '
             "scene, changed or not.")
    last = None
    for attempt in range(3):
        reply = llm.chat(SYSTEM, user + (f"\n\nYour last reply could not be used ({last}). Reply with only valid JSON."
                                         if last else ""), model=model)
        try:
            new = _keep_selling(old, check(job_dir, llm.json_from(reply), log), log)
            return {"plan": new, "changes": diff(old, new)}
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:300]
            log(f"revision attempt {attempt + 1} unusable: {last}")
    raise RuntimeError(f"the model did not write a usable revision ({last})")


def apply(job_dir: str, new: Dict) -> Dict:
    """Check `new` and make it the job's script, keeping the old one as plan.<n>.json. Returns {"plan", "changes"}."""
    new = check(job_dir, new)
    path = os.path.join(job_dir, "plan.json")
    old = read_json(path) or {}
    n = 1
    while os.path.exists(os.path.join(job_dir, f"plan.{n}.json")):
        n += 1
    if old:
        write_json(os.path.join(job_dir, f"plan.{n}.json"), old)
    write_json(path, new)
    for f in ("ready.json", "result.json"):
        if os.path.exists(os.path.join(job_dir, f)):
            os.unlink(os.path.join(job_dir, f))
    return {"plan": new, "changes": diff(old, new)}


def _what(s: Dict) -> str:
    if "video" in s:
        return f"{s['video']} {s['from']:.0f}-{s['to']:.0f}s"
    acts = "; ".join(f"{a['do']} {a.get('to') or a.get('text') or ''}".strip() for a in s.get("actions") or [])
    return f"{s.get('url')}" + (f" ({acts})" if acts else "")


def _caps(s: Dict) -> List[str]:
    caps = s.get("captions") if isinstance(s.get("captions"), list) else [s.get("caption") or ""]
    return [c for c in caps if c]


def diff(old: Dict, new: Dict) -> List[str]:
    """The differences between two scripts, as short sentences."""
    out = []
    for k, label in (("title", "Title"), ("tagline", "Tagline")):
        if (old.get(k) or "") != (new.get(k) or ""):
            out.append(f"{label}: “{new.get(k) or ''}”")
    if (old.get("problem") or {}) != (new.get("problem") or {}):
        out.append(f"Problem card: “{(new.get('problem') or {}).get('statement') or 'none'}”")
    if (old.get("intro") or {}).get("narration") != (new.get("intro") or {}).get("narration"):
        out.append("Intro narration changed")
    if (old.get("outro") or {}) != (new.get("outro") or {}):
        out.append("Outro changed")
    a, b = old.get("scenes") or [], new.get("scenes") or []
    if len(a) != len(b):
        out.append(f"{len(b)} scenes (was {len(a)})")
    for i in range(max(len(a), len(b))):
        if i >= len(b):
            out.append(f"Scene {i + 1} removed: {_caps(a[i])[:1] and _caps(a[i])[0] or _what(a[i])}")
            continue
        if i >= len(a):
            out.append(f"Scene {i + 1} added: {_caps(b[i])[:1] and _caps(b[i])[0] or _what(b[i])}")
            continue
        x, y = a[i], b[i]
        bits = []
        if _caps(x) != _caps(y):
            bits.append("caption " + " / ".join(f"“{c}”" for c in _caps(y)) if _caps(y) else "no caption")
        if x.get("narration") != y.get("narration"):
            bits.append("narration")
        if _what(x) != _what(y):
            bits.append("shows " + _what(y))
        if x.get("sound") != y.get("sound") and "video" in y:
            bits.append("its own sound" if y.get("sound") == "keep" else "narration over it")
        if bits:
            out.append(f"Scene {i + 1}: " + ", ".join(bits))
    return out or ["No changes"]
