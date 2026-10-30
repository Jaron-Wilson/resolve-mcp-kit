"""The Resolve edit: an editable timeline in a "Site videos" project, then a render.

Runs on the computer with Resolve (its scripting only attaches locally). The project that was open is saved first and
opened again afterwards. Each video gets its own bin and timeline, with a marker and the caption at every scene, so
it can be polished by hand later.
"""

import os
import time
from typing import Dict, List

from resolve_mcp import connection as c

from .util import FPS, HEIGHT, WIDTH

PROJECT = os.environ.get("SITE_VIDEO_RESOLVE_PROJECT", "Site videos")


def available() -> bool:
    try:
        c.reset()
        c.connect()
        return True
    except Exception:
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


def edit(work: str, name: str, clips: List[str], mix: str, captions: List[str], out_dir: str, log=print) -> str:
    resolve = c.connect()
    pm = resolve.GetProjectManager()
    before = pm.GetCurrentProject()
    before_name = before.GetName() if before else None
    if before is not None:
        pm.SaveProject()
    try:
        p = pm.LoadProject(PROJECT)
        if not p:
            p = pm.CreateProject(PROJECT)
            if not p:
                raise RuntimeError(f"Resolve would not create or open the project {PROJECT!r}")
            _set_format(p)
        mp = p.GetMediaPool()
        root = mp.GetRootFolder()
        bin_ = mp.AddSubFolder(root, name) or root
        mp.SetCurrentFolder(bin_)
        items = mp.ImportMedia([os.path.abspath(x) for x in clips + [mix]]) or []
        by_path = {}
        for it in items:
            by_path[os.path.normcase(os.path.abspath(it.GetClipProperty("File Path") or ""))] = it
        need = [os.path.normcase(os.path.abspath(x)) for x in clips + [mix]]
        missing = [x for x in need if x not in by_path]
        if missing:
            raise RuntimeError(f"Resolve did not import {len(missing)} file(s), e.g. {missing[0]}")
        tl = mp.CreateEmptyTimeline(name)
        if not tl:
            raise RuntimeError(f"Resolve would not create the timeline {name!r}")
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
        log(f"timeline {name!r}: {len(vids)} clips, soundtrack, {len(captions)} markers")
        pm.SaveProject()

        if p.IsRenderingInProgress():
            raise RuntimeError("Resolve is already rendering")
        codec = _codec(p)
        if not p.SetCurrentRenderFormatAndCodec("mp4", codec):
            raise RuntimeError(f"Resolve would not select mp4 / {codec}")
        os.makedirs(out_dir, exist_ok=True)
        if not p.SetRenderSettings({"SelectAllFrames": True, "TargetDir": os.path.abspath(out_dir), "CustomName": name,
                                    "FormatWidth": WIDTH, "FormatHeight": HEIGHT, "FrameRate": float(FPS),
                                    "VideoQuality": 16000, "ExportVideo": True, "ExportAudio": True}):
            raise RuntimeError("Resolve refused the render settings")
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
        return out
    finally:
        if before_name and before_name != PROJECT:
            pm.LoadProject(before_name)
