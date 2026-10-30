"""The Resolve edit: each video becomes its own project in a "Site videos" project folder, with a timeline laid out
like the hand-made promos (V1 "Picture": the cards and scenes with a dissolve centered on each cut; V2 "Captions": the
caption images with short fades; A1 the soundtrack), so it can be polished by hand later, then a render, and on
request the timeline (.drt/.fcpxml/.edl) and the project (.drp) exported.

Runs on the computer with Resolve (its scripting only attaches locally). The project that was open is saved first and
opened again afterwards, in its own folder.
"""

import os
import time
from typing import Dict, List

from resolve_mcp import connection as c

from .util import DISSOLVE, FPS, HANDLE, HEIGHT, WIDTH, frames

# each video is its own project, in this project folder, so a project export holds only that video
FOLDER = os.environ.get("SITE_VIDEO_RESOLVE_FOLDER", "Site videos")


def available() -> bool:
    try:
        c.reset()
        c.connect()
        return True
    except Exception:
        return False


_STARTED = False      # this process opened Resolve (so it closes it again when its edit is done)


def close_if_started(log=print) -> None:
    """Quit a Resolve that start_if_needed opened (in the background, -nogui), so none is left running unseen. A
    Resolve the person opened is left alone."""
    global _STARTED
    if not _STARTED:
        return
    _STARTED = False
    try:
        c.connect().Quit()
        log("closed the background DaVinci Resolve")
    except Exception as e:
        log(f"could not close the background Resolve ({type(e).__name__})")


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
            global _STARTED
            _STARTED = True
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


def edit(work: str, name: str, clips: List[str], mix: str, secs: List[float], captions: List[Dict], out_dir: str,
         log=print, exports=()) -> Dict:
    """Build and render the video in its own project, in the FOLDER project folder. `exports` may hold "timeline"
    and "project": the timeline as .drt/.fcpxml/.edl and the project as .drp, written to out_dir.
    {"video": path, "timeline": [paths], "project": path or None}"""
    resolve = c.connect()
    pm = resolve.GetProjectManager()
    before = pm.GetCurrentProject()
    before_name = before.GetName() if before else None
    home = _folder_path(pm)
    # Only a project that is in the project list is the user's work, to save now and open again afterwards. A
    # freshly started Resolve has an unsaved "Untitled Project" open, and saving that asks where to save it, in a
    # window scripting cannot answer: leave it alone.
    keep = bool(before_name) and before_name in (pm.GetProjectListInCurrentFolder() or [])
    if keep:
        pm.SaveProject()
    try:
        pm.GotoRootFolder()
        folder = FOLDER
        if folder in (pm.GetProjectListInCurrentFolder() or []):
            # a project already has the name (an older version kept every video in one "Site videos" project), and
            # Resolve will not make a folder named like a project
            folder = FOLDER + " projects"
            log(f"a project is already called {FOLDER!r}; the video goes in the folder {folder!r}")
        if folder not in (pm.GetFolderListInCurrentFolder() or []):
            pm.CreateFolder(folder)
        if not pm.OpenFolder(folder):
            raise RuntimeError(f"Resolve would not open or create the project folder {folder!r}")
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
        pngs = list(dict.fromkeys(cap["png"] for cap in captions))
        files = [os.path.abspath(x) for x in clips + [mix] + pngs]
        items = mp.ImportMedia(files) or []
        by_path = {}
        for it in items:
            by_path[os.path.normcase(os.path.abspath(it.GetClipProperty("File Path") or ""))] = it
        missing = [x for x in files if os.path.normcase(x) not in by_path]
        if missing:
            raise RuntimeError(f"Resolve did not import {len(missing)} file(s), e.g. {missing[0]}")
        item = lambda path: by_path[os.path.normcase(os.path.abspath(path))]
        tl_name = name if not p.GetTimelineCount() else f"{name} {time.strftime('%H%M%S')}"     # a retry adds one
        tl = mp.CreateEmptyTimeline(tl_name)
        if not tl:
            raise RuntimeError(f"Resolve would not create the timeline {tl_name!r}")
        p.SetCurrentTimeline(tl)
        if p.GetSetting("timelineFrameRate") not in (str(FPS), f"{FPS}.0"):
            tl.SetSetting("useCustomSettings", "1")       # a project with media keeps its frame rate; the timeline can differ
            _set_format(tl)
        while (tl.GetTrackCount("video") or 0) < 2:
            tl.AddTrack("video")
        tl.SetTrackName("video", 1, "Picture")
        tl.SetTrackName("video", 2, "Captions")
        tl.SetTrackName("audio", 1, "Soundtrack")
        start = tl.GetStartFrame()

        # V1: each clip without its handles; the handles are what the centered dissolves overlap into
        n = [frames(d) for d in secs]
        vids = mp.AppendToTimeline([{"mediaPoolItem": item(x), "startFrame": HANDLE, "endFrame": HANDLE + k,
                                     "trackIndex": 1, "mediaType": 1} for x, k in zip(clips, n)]) or []
        if len(vids) != len(clips):
            raise RuntimeError(f"only {len(vids)} of {len(clips)} clips went onto the timeline")
        for x, k, v in zip(clips, n, vids):
            if int(v.GetDuration()) != k:
                log(f"  {os.path.basename(x)}: {int(v.GetDuration())} frames on the timeline, {k} planned")
        fades = sum(bool(v.AddTransition({"type": "Cross Dissolve", "category": "simple", "position": "end",
                                          "alignment": "center", "duration": DISSOLVE})) for v in vids[:-1])
        fades += bool(vids[-1].AddTransition({"type": "Cross Dissolve", "category": "simple", "position": "end",
                                              "alignment": "left", "duration": 24}))
        if fades < len(vids):
            log(f"  Resolve took {fades} of {len(vids)} transitions")
        aud = mp.AppendToTimeline([{"mediaPoolItem": item(mix), "trackIndex": 1, "mediaType": 2,
                                    "recordFrame": start}]) or []
        if not aud:
            raise RuntimeError("the soundtrack did not go onto the timeline")

        # V2: captions are stills; Resolve honors a still's mark in/out (not startFrame/endFrame) for its length
        placed = 0
        for cap in captions:
            still, want = item(cap["png"]), frames(cap["end"] - cap["start"])
            end = want - 1
            for _ in range(3):
                still.SetMarkInOut(0, end)
                got = mp.AppendToTimeline([{"mediaPoolItem": still, "trackIndex": 2,
                                            "recordFrame": start + frames(cap["start"])}]) or []
                still.ClearMarkInOut()
                if not got:
                    break
                d = int(got[0].GetDuration())
                if d == want:
                    placed += 1
                    for pos, align in (("start", "right"), ("end", "left")):
                        got[0].AddTransition({"type": "Cross Dissolve", "category": "simple", "position": pos,
                                              "alignment": align, "duration": 8})
                    break
                tl.DeleteClips([got[0]])
                end += want - d
        if placed < len(captions):
            log(f"  {len(captions) - placed} caption(s) did not go onto the timeline")
        log(f"project {name!r}, timeline {tl_name!r}: {len(vids)} clips with dissolves, {placed} captions, soundtrack")
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
        if keep:
            _open_folder(pm, home)
            pm.LoadProject(before_name)
