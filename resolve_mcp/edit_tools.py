"""Editing and render tools.

These are NEW in this kit: the original server this was derived from is read-only (plus
set_page). They exist so the bundled editing skill has something to drive.
They only register when RESOLVE_MCP_ALLOW_WRITE=1, and none of them deletes
anything. The Resolve calls follow Resolve's own scripting README, but they
have only been exercised against a fake Resolve object, not a real install.
"""

from typing import Any, Dict, List, Optional

from . import connection as c


def _find_clip(folder, name):
    for clip in (folder.GetClipList() or []):
        if clip.GetName() == name:
            return clip
    for sub in (folder.GetSubFolderList() or []):
        hit = _find_clip(sub, name)
        if hit is not None:
            return hit
    return None


def register(mcp):
    @mcp.tool()
    def save_project() -> Dict[str, Any]:
        """WRITE. Save the open project."""
        return {"ok": bool(c.connect().GetProjectManager().SaveProject())}

    @mcp.tool()
    def import_media(paths: List[str], folder: str = "") -> Dict[str, Any]:
        """WRITE. Import media files (absolute paths on the Resolve machine) into the
        media pool. With `folder`, they go into that bin, created if missing."""
        mp = c.project().GetMediaPool()
        if folder:
            root = mp.GetRootFolder()
            match = [f for f in (root.GetSubFolderList() or []) if f.GetName() == folder]
            target = match[0] if match else mp.AddSubFolder(root, folder)
            if not target:
                raise RuntimeError(f"Could not create media pool folder {folder!r}")
            mp.SetCurrentFolder(target)
        items = mp.ImportMedia(list(paths)) or []
        return {"imported": [i.GetName() for i in items],
                "requested": len(paths), "ok": len(items) > 0}

    @mcp.tool()
    def create_timeline(name: str) -> Dict[str, Any]:
        """WRITE. Create an empty timeline and make it current. Settings such as
        frame rate come from the project; set them before adding clips."""
        p = c.project()
        tl = p.GetMediaPool().CreateEmptyTimeline(name)
        if not tl:
            raise RuntimeError(f"Resolve would not create timeline {name!r} "
                               "(the name may already exist).")
        p.SetCurrentTimeline(tl)
        return {"ok": True, "name": tl.GetName()}

    @mcp.tool()
    def append_clips(clips: List[Dict[str, Any]],
                     timeline: Optional[str] = None) -> Dict[str, Any]:
        """WRITE. Append media pool clips to a timeline, in order.

        Each entry: {"name": <clip name>, "start_frame": int?, "end_frame": int?,
        "track": int?}. start_frame/end_frame trim the source (in source frames,
        end inclusive); omit both for the whole clip. This is how cuts are made.
        """
        p = c.project()
        tl = c.find_timeline(p, timeline)
        p.SetCurrentTimeline(tl)
        mp = p.GetMediaPool()
        root = mp.GetRootFolder()
        infos, missing = [], []
        for spec in clips:
            item = _find_clip(root, spec.get("name", ""))
            if item is None:
                missing.append(spec.get("name"))
                continue
            info: Dict[str, Any] = {"mediaPoolItem": item}
            if spec.get("start_frame") is not None:
                info["startFrame"] = int(spec["start_frame"])
            if spec.get("end_frame") is not None:
                info["endFrame"] = int(spec["end_frame"])
            if spec.get("track") is not None:
                info["trackIndex"] = int(spec["track"])
            infos.append(info)
        if missing:
            raise RuntimeError(f"Clips not in the media pool: {missing}. "
                               "Nothing was appended.")
        added = mp.AppendToTimeline(infos) or []
        return {"ok": len(added) == len(infos), "appended": len(added)}

    @mcp.tool()
    def add_title(text: str, title: str = "Text+",
                  timeline: Optional[str] = None) -> Dict[str, Any]:
        """WRITE. Insert a title generator (default Text+) at the playhead and set
        its text. Only titles with a Text+ tool get the text set."""
        p = c.project()
        tl = c.find_timeline(p, timeline)
        p.SetCurrentTimeline(tl)
        item = tl.InsertTitleIntoTimeline(title)
        if not item:
            raise RuntimeError(f"Resolve would not insert title {title!r}.")
        comp = item.GetFusionCompByIndex(1) if item.GetFusionCompCount() else None
        tool = comp.FindToolByID("TextPlus") if comp else None
        if tool is None:
            return {"ok": True, "text_set": False,
                    "note": "Title inserted, but no Text+ tool found to set the text on."}
        tool.SetInput("StyledText", text)
        return {"ok": True, "text_set": True}

    @mcp.tool()
    def add_marker(frame: int, color: str = "Blue", name: str = "", note: str = "",
                   timeline: Optional[str] = None) -> Dict[str, Any]:
        """WRITE. Add a timeline marker at `frame` (timeline frame number)."""
        tl = c.find_timeline(c.project(), timeline)
        return {"ok": bool(tl.AddMarker(int(frame), color, name, note, 1))}

    @mcp.tool()
    def render_formats_and_codecs(format: str = "mp4") -> Dict[str, Any]:
        """Render formats, and the codecs available for `format`."""
        p = c.project()
        return {"formats": p.GetRenderFormats(), "codecs": p.GetRenderCodecs(format)}

    @mcp.tool()
    def start_render(target_dir: str, name: str, format: str = "mp4",
                     codec: str = "", width: int = 0, height: int = 0,
                     timeline: Optional[str] = None) -> Dict[str, Any]:
        """WRITE. Queue a render of the timeline and start it. Returns a job id for
        render_status. `codec` is a key from render_formats_and_codecs; blank keeps
        the first one listed. width/height of 0 keep the timeline size."""
        p = c.project()
        tl = c.find_timeline(p, timeline)
        p.SetCurrentTimeline(tl)
        if p.IsRenderingInProgress():
            raise RuntimeError("Resolve is already rendering; not starting another.")
        if not codec:
            codec = next(iter((p.GetRenderCodecs(format) or {}).values()), "")
        if not p.SetCurrentRenderFormatAndCodec(format, codec):
            raise RuntimeError(f"Could not select format {format!r} / codec {codec!r}.")
        settings: Dict[str, Any] = {"SelectAllFrames": True,
                                    "TargetDir": target_dir, "CustomName": name}
        if width and height:
            settings.update(FormatWidth=int(width), FormatHeight=int(height))
        if not p.SetRenderSettings(settings):
            raise RuntimeError("Resolve refused the render settings (is target_dir "
                               "an existing folder on the Resolve machine?).")
        job = p.AddRenderJob()
        if not job:
            raise RuntimeError("Resolve would not add the render job.")
        if not p.StartRendering([job]):
            raise RuntimeError("Resolve would not start rendering.")
        return {"ok": True, "job_id": job}

    @mcp.tool()
    def render_status(job_id: str) -> Dict[str, Any]:
        """Progress of a render job started with start_render."""
        p = c.project()
        st = p.GetRenderJobStatus(job_id) or {}
        return {"in_progress": bool(p.IsRenderingInProgress()), "status": st}
