"""Check the recorded scenes against the script before the edit: does each clip show what the script says it shows, and
does it fit what the captions and narration say over it?

Each scene's clip is sampled at the start, middle and end into one strip, and the vision model
(SITE_VIDEO_VISION_MODEL) is asked whether it matches the scene's page, steps, captions and narration. Steps the
recorder could not do (a button or field it did not find) count against a scene without asking. The verdicts go to
review.json and the job log; pipeline.prep has the script model fix a failed scene once and records it again.
"""

import json
import os
import re
from typing import Dict, List

from .util import HANDLE, ffmpeg, frames

ASK = """You check a promo video before it is published. Below is a strip of three frames (start, middle, end) from
one scene, and what the script says the scene shows. Judge only what is visible.

The script for this scene:
{brief}

Score how well the footage shows the scene, from 1 to 5:
5 = the right page and the right part of it, as the caption says
4 = the right page and roughly the right part; small details may be too small to read (that is fine)
3 = the right page, but a different part of it than the caption talks about
2 = a different page than the script says, but a working one
1 = broken: an error, an empty or loading page, a sign-in wall, or something unrelated
Do not mark down for small text you cannot read in the frames, or for a search box that scrolled away after use.
Reply with only JSON: {{"score": 1 to 5, "saw": "what the frames really show, one sentence",
"problem": "what does not match, one sentence, or empty"}}"""


def enabled() -> bool:
    return bool(os.environ.get("SITE_VIDEO_VISION_MODEL")) and os.environ.get("SITE_VIDEO_REVIEW", "1") != "0"


def _brief(s: Dict) -> str:
    caps = " / ".join(s.get("captions") or [s.get("caption") or ""])
    if "video" in s:
        what = f"a part of the owner's video {s['video']}"
    else:
        steps = "; ".join(f"{a['do']} {a.get('into', '')} {a.get('to') or a.get('text') or ''}".replace("  ", " ").strip()
                          for a in s.get("actions") or [])
        where = ("the page the previous scene ended on (its clicks may have opened a new one)" if s.get("continue")
                 else f"the web page {s['url']}")
        what = where + (f", where these steps happen: {steps}" if steps else "")
    return (f"It shows {what}.\nCaption on screen: {caps or '(none)'}\n"
            f"Narration over it: {s.get('narration') or '(none)'}")


def _strip(clip: str, seconds: float, out_jpg: str) -> str:
    n = frames(seconds)
    at = [HANDLE + int(n * k) for k in (0.15, 0.5, 0.92)]
    sel = "+".join(f"eq(n\\,{a})" for a in at)
    ffmpeg("-i", clip, "-vf", f"select='{sel}',scale=1024:-1,tile=1x3:padding=8", "-frames:v", "1", "-q:v", "3", out_jpg)
    return out_jpg


def _verdict(text: str) -> Dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    if not isinstance(v, dict) or ("score" not in v and "matches" not in v):
        # a model that answered in words: take a clear no as a no, anything else as not judged
        no = bool(re.search(r"\b(does not|doesn't|not) match", text or "", re.I))
        return {"matches": not no, "score": 2 if no else 4, "saw": (text or "")[:200],
                "problem": (text or "")[:200] if no else "", "unsure": True}
    try:
        score = int(round(float(v.get("score"))))
    except (TypeError, ValueError):
        score = 5 if v.get("matches") in (True, "true", "yes") else 2
    score = max(1, min(5, score))
    return {"matches": score >= 3, "score": score, "saw": str(v.get("saw") or "")[:240],
            "problem": str(v.get("problem") or "")[:240] if score < 5 else ""}


def review(job_dir: str, plan: Dict, clips: List[str], secs: List[float], log=print) -> List[Dict]:
    """One verdict per scene: {"scene": n (1-based), "matches", "saw", "problem", "misses"}."""
    from .media import _describe
    from concurrent.futures import ThreadPoolExecutor
    work = os.path.join(job_dir, "review")
    os.makedirs(work, exist_ok=True)

    def one(i: int) -> Dict:
        s, clip = plan["scenes"][i], clips[i + 1]
        misses = []
        if os.path.exists(clip[:-4] + ".misses.json"):
            with open(clip[:-4] + ".misses.json") as f:
                misses = json.load(f)
        v = {"scene": i + 1, "matches": True, "saw": "", "problem": "", "misses": misses}
        try:
            strip = _strip(clip, secs[i + 1], os.path.join(work, f"scene_{i + 1:02d}.jpg"))
            v.update(_verdict(_describe(strip, "", ASK.format(brief=_brief(s)), max_tokens=300)))
        except Exception as e:
            v.update({"unsure": True, "saw": f"could not check ({type(e).__name__})"})
        if misses:
            v["matches"], v["score"] = False, min(v.get("score", 5), 1)
            v["problem"] = (v["problem"] + " " if v["problem"] else "") + "Steps that did not happen: " + "; ".join(misses)
        return v

    with ThreadPoolExecutor(3) as ex:
        out = list(ex.map(one, range(len(plan["scenes"]))))
    bad = [v for v in out if not v["matches"]]
    for v in out:
        log(f"  review scene {v['scene']}: {v.get('score', '?')}/5 {'ok' if v['matches'] else 'DOES NOT MATCH'}"
            + (f": {v['problem']}" if v["problem"] else "") + (f" (saw: {v['saw']})" if v["saw"] and not v["matches"] else ""))
    log(f"review: {len(out) - len(bad)} of {len(out)} scenes match the script")
    with open(os.path.join(job_dir, "review.json"), "w") as f:
        json.dump(out, f, indent=1)
    return out


def fix_request(verdicts: List[Dict]) -> str:
    """The change to ask the script model for, from the failed scenes."""
    lines = []
    for v in verdicts:
        # only clear failures are rewritten (a step that did not happen, a broken or wrong page); a scene that shows
        # the right page is left alone, so a picky reviewer cannot make good captions vaguer
        if v["matches"] or (v.get("score", 1) >= 2 and not v.get("misses")) or v.get("unsure"):
            continue
        lines.append(f"Scene {v['scene']}: the recording really shows: {v['saw'] or 'unknown'}. Problem: {v['problem']}")
    if not lines:
        return ""
    return ("The recorded video does not match the script in these scenes. Fix only these scenes and keep every other "
            "scene exactly as it is. For each one, in this order of preference: give it steps that really make its "
            "caption happen (on the person's own site, the clicks that create it, continuing from the scene before); "
            "or show a page that already has what the caption says; or, only if neither is possible, captions and "
            "narration about a feature that page really offers. Captions and narration sell the product: never "
            "describe an error, an empty, blank or loading page, or what went wrong in the recording.\n"
            + "\n".join(lines))
