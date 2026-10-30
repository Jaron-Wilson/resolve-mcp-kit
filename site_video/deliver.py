"""Deliverables: what a job hands back, chosen per job.

video            the rendered MP4 (always)
script           script.md (scenes, captions, narration, on-screen actions) and plan.json
voiceover        voiceover/: one WAV per narration line, and soundtrack.wav (the mixed audio of the whole video)
clips            clips/: the recorded scenes and the title cards, 1920x1080 30 fps
timeline         the Resolve timeline as .drt (Resolve), .fcpxml (Final Cut, Premiere) and .edl (Resolve edits only)
resolve_project  the video's own Resolve project as .drp (Resolve edits only)
package          one .zip with everything above, the media the project uses, and a README

Everything lands in <job>/deliverables/.
"""

import os
import shutil
import zipfile
from typing import Dict, List

KINDS = ("video", "script", "voiceover", "clips", "timeline", "resolve_project", "package")
NEEDS_RESOLVE = ("timeline", "resolve_project")


def parse(value) -> List[str]:
    """'video,script' or ['video', 'script'] -> a checked list that always has video; 'all' -> every kind."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").replace(" ", "").split(",")
    items = [str(i).strip().lower() for i in items if str(i).strip()]
    if "all" in items:
        return list(KINDS)
    bad = [i for i in items if i not in KINDS]
    if bad:
        raise ValueError(f"deliverables: unknown {', '.join(bad)}; choose from {', '.join(KINDS)} or all")
    out = ["video"] + [k for k in KINDS if k in items and k != "video"]
    if "package" in out:          # the package holds everything, so make everything
        out = list(KINDS)
    return out


def script_md(plan: Dict, secs: List[float]) -> str:
    lines = [f"# {plan.get('title') or 'Site video'}", ""]
    if plan.get("tagline"):
        lines += [f"*{plan['tagline']}*", ""]
    t = 0.0

    def stamp(x):
        return f"{int(x // 60)}:{int(x % 60):02d}"
    lines += [f"## Intro ({stamp(t)}, {secs[0]:.1f} s)", "", plan["intro"].get("narration") or "(no narration)", ""]
    t += secs[0]
    for i, s in enumerate(plan["scenes"]):
        d = secs[i + 1]
        lines += [f"## {i + 1}. {s.get('caption') or 'Scene'} ({stamp(t)}, {d:.1f} s)", "", f"Page: {s['url']}", ""]
        if s.get("actions"):
            acts = []
            for a in s["actions"]:
                what = a.get("to") or a.get("text") or (f"{a.get('seconds')} s" if a["do"] == "pause" else "")
                acts.append(f"{a['do']} {what}".strip())
            lines += ["On screen: " + "; ".join(acts), ""]
        lines += [s.get("narration") or "(no narration)", ""]
        t += d
    lines += [f"## Outro ({stamp(t)}, {secs[-1]:.1f} s)", "", plan["outro"].get("narration") or "(no narration)", "",
              f"Call to action: {plan['outro'].get('call_to_action') or plan.get('url')}", "",
              f"Total: {stamp(sum(secs))}"]
    return "\n".join(lines) + "\n"


README = """{title}

What is in this package
- {video}: the finished video
- script.md, plan.json: the script, scene by scene
- voiceover/: each narration line as a WAV, and soundtrack.wav (the whole mixed audio)
- clips/: the recorded scenes and title cards, 1920x1080, 30 fps
{resolve}
Edit it yourself
- In DaVinci Resolve: Project Manager > right click > Import Project, choose the .drp. If Resolve asks for media,
  point it at the clips/ folder and soundtrack.wav (Relink Media).
- In another editor: import the .fcpxml (Final Cut Pro, Premiere Pro) or the .edl with the clips/ folder and
  soundtrack.wav, or lay the clips in order on one track with soundtrack.wav from the start.
"""


def collect(job_dir: str, kinds: List[str], ready: Dict, result: Dict, voice_wavs: List, log=print) -> List[Dict]:
    """Copy what was asked for into <job>/deliverables/ and return [{"name", "kind", "bytes"}]."""
    import json
    out = os.path.join(job_dir, "deliverables")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    name = ready["name"]
    files: List[Dict] = []

    def add(path, kind):
        files.append({"name": os.path.relpath(path, out).replace(os.sep, "/"), "kind": kind,
                      "bytes": os.path.getsize(path)})

    video = os.path.join(out, os.path.basename(result["video"]))
    shutil.move(result["video"], video)
    add(video, "video")
    if "script" in kinds:
        with open(os.path.join(out, "script.md"), "w", encoding="utf-8") as f:
            f.write(script_md(ready["plan"], ready["secs"]))
        with open(os.path.join(out, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(ready["plan"], f, indent=2)
        add(os.path.join(out, "script.md"), "script")
        add(os.path.join(out, "plan.json"), "script")
    if "voiceover" in kinds:
        vdir = os.path.join(out, "voiceover")
        os.makedirs(vdir)
        labels = ["intro"] + [f"scene{i + 1:02d}" for i in range(len(ready["plan"]["scenes"]))] + ["outro"]
        for lab, wav in zip(labels, voice_wavs):
            if wav and os.path.exists(wav):
                dst = os.path.join(vdir, f"{lab}.wav")
                shutil.copy2(wav, dst)
                add(dst, "voiceover")
        dst = os.path.join(vdir, "soundtrack.wav")
        shutil.copy2(ready["mix"], dst)
        add(dst, "voiceover")
    if "clips" in kinds:
        cdir = os.path.join(out, "clips")
        os.makedirs(cdir)
        for clip in ready["clips"]:
            dst = os.path.join(cdir, os.path.basename(clip))
            shutil.copy2(clip, dst)
            add(dst, "clips")
    for path in result.get("timeline") or []:
        dst = os.path.join(out, os.path.basename(path))
        shutil.move(path, dst)
        add(dst, "timeline")
    if result.get("project"):
        dst = os.path.join(out, os.path.basename(result["project"]))
        shutil.move(result["project"], dst)
        add(dst, "resolve_project")
    for k in NEEDS_RESOLVE:
        if k in kinds and not any(f["kind"] == k for f in files):
            log(f"no {k.replace('_', ' ')}: it comes from a Resolve edit (this one used {result.get('editor', 'ffmpeg')})")
    if "package" in kinds:
        zpath = os.path.join(out, name + ".zip")
        has_resolve = any(f["kind"] in NEEDS_RESOLVE for f in files)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:      # video and WAV do not compress
            for f in list(files):
                z.write(os.path.join(out, f["name"]), f"{name}/{f['name']}")
            z.writestr(f"{name}/README.txt", README.format(
                title=ready["plan"].get("title") or name, video=os.path.basename(video),
                resolve=("- the .drp (Resolve project) and .drt/.fcpxml/.edl (the timeline)\n" if has_resolve else "")))
        add(zpath, "package")
    log("deliverables: " + ", ".join(sorted({f["kind"] for f in files})))
    return files
