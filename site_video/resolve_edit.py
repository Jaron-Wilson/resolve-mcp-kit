"""The Resolve edit: each video becomes its own project in a "Site videos" project folder, with a timeline (a marker
and the caption at every scene, so it can be polished by hand later), then a render, and on request the timeline
(.drt/.fcpxml/.edl) and the project (.drp) exported.

Runs on the computer with Resolve (its scripting only attaches locally). The project that was open is saved first and
opened again afterwards, in its own folder.
"""

import os
import time
from typing import Dict, List

from resolve_mcp import connection as c

from .util import FPS, HEIGHT, WIDTH

# each video is its own project, in this project folder, so a project export holds only that video
FOLDER = os.environ.get("SITE_VIDEO_RESOLVE_FOLDER", "Site videos")


def available() -> bool:
    try:
        c.reset()
        c.connect()
        return True
    except Exception:
        return False


def start_if_needed(log=print, wait_s: int = 180) -> bool:
    """With SITE_VIDEO_START_RESOLVE set to Resolve's program file, open Resolve when it is not running and wait
    until its scripting answers. Run the queue in your desktop session, so Resolve opens there."""
    if available():
        return True
    exe = os.environ.get("SITE_VIDEO_START_RESOLVE", "")
    if not exe or not os.path.exists(exe):
        return False
    import subprocess
    # -nogui (Studio): no window and no Project Manager screen, which would otherwise block opening projects
    args = os.environ.get("SITE_VIDEO_START_RESOLVE_ARGS", "-nogui").split()
    log("opening DaVinci Resolve " + " ".join(args))
    subprocess.Popen([exe, *args], cwd=os.path.dirname(exe))
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(5)
        if available():
            time.sleep(5)              # let the project manager finish loading
            return True
    log(f"Resolve did not answer within {wait_s} s")
    return False


def _set_format(obj) -> None:
    for k, v in (("timelineFrameRate", str(FPS)), ("timelineResolutionWidth", str(WIDTH)),
                 ("timelineResolutionHeight", str(HEIGHT)), ("timelinePlaybackFrameRate", str(FPS))):
        obj.SetSetting(k, v)


def _codec(p) -> str:
    """Resolve's own H.264: NVENC can disappear after a Remote Desktop session."""
    codecs = p.GetRenderCodecs("mp4") or {}
    for want in ("H264", "H.264"):
        for label, key in codecs.items():
            if key == want or label == want:
                return key
    for label, key in codecs.items():
        if "264" in key and "NVIDIA" not in key.upper():
            return key
    return next(iter(codecs.values()), "")


def _folder_path(pm) -> List[str]:
    """The project folder Resolve is in, as names from the root (Resolve only opens projects in the current folder)."""
    names = []
    while True:
        here = pm.GetCurrentFolder()
        if not pm.GotoParentFolder():
            break
        if here:
            names.append(here)
    names.reverse()
    pm.GotoRootFolder()
    for n in names:
        pm.OpenFolder(n)
    return names


def _open_folder(pm, names: List[str]) -> None:
    pm.GotoRootFolder()
    for n in names:
        pm.OpenFolder(n)


# Timeline formats, by the Resolve constant names tried in order (they differ between Resolve versions)
TIMELINE_EXPORTS = [("drt", ["EXPORT_DRT"]), ("fcpxml", ["EXPORT_FCPXML_1_11", "EXPORT_FCPXML_1_10", "EXPORT_FCPXML_1_9"]),
                    ("edl", ["EXPORT_EDL"])]


def _export_timeline(resolve, tl, out_dir: str, name: str, log) -> List[str]:
    done = []
    for ext, consts in TIMELINE_EXPORTS:
        kind = next((getattr(resolve, k) for k in consts if hasattr(resolve, k)), None)
        if kind is None:
            log(f"  this Resolve has no {ext} timeline export")
            continue
        path = os.path.join(out_dir, f"{name}.{ext}")
        sub = getattr(resolve, "EXPORT_NONE", None)
        ok = tl.Export(path, kind, sub) if ext == "edl" and sub is not None else tl.Export(path, kind)
        if ok and os.path.exists(path):
            done.append(path)
        else:
            log(f"  Resolve did not export the timeline as {ext}")
    return done


def edit(work: str, name: str, clips: List[str], mix: str, captions: List[str], out_dir: str, log=print,
         exports=()) -> Dict:
    """Build and render the video in its own project, in the FOLDER project folder. `exports` may hold "timeline"
    and "project": the timeline as .drt/.fcpxml/.edl and the project as .drp, written to out_dir.
    {"video": path, "timeline": [paths], "project": path or None}"""
    resolve = c.connect()
    pm = resolve.GetProjectManager()
    before = pm.GetCurrentProject()
    before_name = before.GetName() if before else None
    if before is not None:
        pm.SaveProject()
    home = _folder_path(pm)
    try:
        pm.GotoRootFolder()
        if FOLDER not in (pm.GetFolderListInCurrentFolder() or []):
            pm.CreateFolder(FOLDER)
        if not pm.OpenFolder(FOLDER):
            raise RuntimeError(f"Resolve would not open the project folder {FOLDER!r}")
        p = pm.LoadProject(name) or pm.CreateProject(name)
        if not p:
            stuck = resolve.GetCurrentPage() is None
            raise RuntimeError(
                f"Resolve would not create or open the project {name!r}"
                + (". It is showing its Project Manager, which blocks scripting: open any project in Resolve, or "
                   "close Resolve so the next try starts it in the background (-nogui)" if stuck else ""))
        _set_format(p)
        mp = p.GetMediaPool()
        root = mp.GetRootFolder()
        mp.SetCurrentFolder(mp.AddSubFolder(root, "media") or root)
        items = mp.ImportMedia([os.path.abspath(x) for x in clips + [mix]]) or []
        by_path = {}
        for it in items:
            by_path[os.path.normcase(os.path.abspath(it.GetClipProperty("File Path") or ""))] = it
        need = [os.path.normcase(os.path.abspath(x)) for x in clips + [mix]]
        missing = [x for x in need if x not in by_path]
        if missing:
            raise RuntimeError(f"Resolve did not import {len(missing)} file(s), e.g. {missing[0]}")
        tl_name = name if not p.GetTimelineCount() else f"{name} {time.strftime('%H%M%S')}"     # a retry adds one
        tl = mp.CreateEmptyTimeline(tl_name)
        if not tl:
            raise RuntimeError(f"Resolve would not create the timeline {tl_name!r}")
        p.SetCurrentTimeline(tl)
        if p.GetSetting("timelineFrameRate") not in (str(FPS), f"{FPS}.0"):
            tl.SetSetting("useCustomSettings", "1")       # a project with media keeps its frame rate; the timeline can differ
            _set_format(tl)
        start = tl.GetStartFrame()
        vids = mp.AppendToTimeline([{"mediaPoolItem": by_path[x], "trackIndex": 1, "mediaType": 1} for x in need[:-1]]) or []
        if len(vids) != len(clips):
            raise RuntimeError(f"only {len(vids)} of {len(clips)} clips went onto the timeline")
        aud = mp.AppendToTimeline([{"mediaPoolItem": by_path[need[-1]], "trackIndex": 1, "mediaType": 2,
                                    "recordFrame": start}]) or []
        if not aud:
            raise RuntimeError("the soundtrack did not go onto the timeline")
        for item, cap in zip(vids[1:-1], captions):
            tl.AddMarker(item.GetStart() - start, "Blue", cap[:60] or "scene", "", 1)
        log(f"project {name!r}, timeline {tl_name!r}: {len(vids)} clips, soundtrack, {len(captions)} markers")
        pm.SaveProject()

        if p.IsRenderingInProgress():
            raise RuntimeError("Resolve is already rendering")
        codec = _codec(p)
        if not p.SetCurrentRenderFormatAndCodec("mp4", codec):
            raise RuntimeError(f"Resolve would not select mp4 / {codec}")
        os.makedirs(out_dir, exist_ok=True)
        # Resolve refuses a whole settings dict for one key it does not like, without saying which: the required
        # ones go first, then each optional one alone, and a refused optional one is only logged
        if not p.SetRenderSettings({"SelectAllFrames": True, "TargetDir": os.path.abspath(out_dir), "CustomName": name}):
            raise RuntimeError(f"Resolve refused the render target {os.path.abspath(out_dir)!r}")
        for k, v in (("ExportVideo", True), ("ExportAudio", True), ("FormatWidth", WIDTH), ("FormatHeight", HEIGHT),
                     ("VideoQuality", 16000)):
            if not p.SetRenderSettings({k: v}):
                log(f"  Resolve refused render setting {k}={v}; using its default")
        job = p.AddRenderJob()
        if not job or not p.StartRendering([job]):
            raise RuntimeError("Resolve would not start the render")
        last = -1
        while p.IsRenderingInProgress():
            st = p.GetRenderJobStatus(job) or {}
            pct = int(st.get("CompletionPercentage") or 0)
            if pct // 10 != last // 10:
                log(f"Resolve rendering {pct}%")
                last = pct
            time.sleep(2)
        st = p.GetRenderJobStatus(job) or {}
        if str(st.get("JobStatus", "")).lower() not in ("complete", "completed"):
            raise RuntimeError(f"Resolve render ended: {st}")
        p.DeleteRenderJob(job)
        pm.SaveProject()
        out = os.path.join(out_dir, name + ".mp4")
        if not os.path.exists(out):
            raise RuntimeError(f"Resolve said it finished but {out} is not there")
        result = {"video": out, "timeline": [], "project": None}
        if "timeline" in exports:
            result["timeline"] = _export_timeline(resolve, tl, out_dir, name, log)
        if "project" in exports:
            drp = os.path.join(out_dir, name + ".drp")
            if pm.ExportProject(name, drp, True) and os.path.exists(drp):
                result["project"] = drp
            else:
                log("  Resolve did not export the project")
        return result
    finally:
        _open_folder(pm, home)
        if before_name:
            pm.LoadProject(before_name)
