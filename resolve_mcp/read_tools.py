"""Read-only tools, plus set_page. These are the tools the original server had."""

from typing import Any, Dict, List, Optional

from . import connection as c


def register(mcp):
    @mcp.tool()
    def resolve_status() -> Dict[str, Any]:
        """Whether Resolve is reachable, and what is currently open."""
        try:
            r = c.connect()
        except RuntimeError as e:
            return {"connected": False, "reason": str(e)}
        proj = r.GetProjectManager().GetCurrentProject()
        out: Dict[str, Any] = {
            "connected": True,
            "product": r.GetProductName(),
            "version": r.GetVersionString(),
            "page": r.GetCurrentPage(),
            "project": proj.GetName() if proj else None,
        }
        if proj:
            tl = proj.GetCurrentTimeline()
            out["timeline"] = tl.GetName() if tl else None
            out["timeline_count"] = proj.GetTimelineCount()
        if out["page"] is None:
            out["note"] = ("No page is open: Resolve is showing the Project Manager. "
                           "Project queries still work; set_page will not until a "
                           "project is opened in the window.")
        return out

    @mcp.tool()
    def list_projects() -> List[str]:
        """Names of the projects in the current database folder."""
        return c.connect().GetProjectManager().GetProjectListInCurrentFolder() or []

    @mcp.tool()
    def list_timelines() -> List[str]:
        """Timelines in the open project."""
        p = c.project()
        return [p.GetTimelineByIndex(i).GetName()
                for i in range(1, (p.GetTimelineCount() or 0) + 1)]

    @mcp.tool()
    def timeline_info(name: Optional[str] = None) -> Dict[str, Any]:
        """Details of a timeline: the current one unless a name is given."""
        p = c.project()
        tl = c.find_timeline(p, name)
        return {
            "name": tl.GetName(),
            "start_frame": tl.GetStartFrame(),
            "end_frame": tl.GetEndFrame(),
            "video_tracks": tl.GetTrackCount("video"),
            "audio_tracks": tl.GetTrackCount("audio"),
            "fps": p.GetSetting("timelineFrameRate"),
        }

    @mcp.tool()
    def list_media_pool(folder: str = "") -> List[Dict[str, Any]]:
        """Clips in the media pool: the root bin unless a folder name is given."""
        mp = c.project().GetMediaPool()
        target = mp.GetRootFolder()
        if folder:
            match = [f for f in (target.GetSubFolderList() or [])
                     if f.GetName() == folder]
            if not match:
                raise RuntimeError(f"No media pool folder named {folder!r}")
            target = match[0]
        return [{
            "name": clip.GetName(),
            "duration": clip.GetClipProperty("Duration"),
            "fps": clip.GetClipProperty("FPS"),
            "resolution": clip.GetClipProperty("Resolution"),
        } for clip in (target.GetClipList() or [])]

    @mcp.tool()
    def set_page(page: str) -> Dict[str, Any]:
        """Switch Resolve's page: media, cut, edit, fusion, color, fairlight, deliver.

        Changes what is on screen but touches no media.
        """
        valid = {"media", "cut", "edit", "fusion", "color", "fairlight", "deliver"}
        page = (page or "").strip().lower()
        if page not in valid:
            raise RuntimeError(f"page must be one of: {', '.join(sorted(valid))}")
        r = c.connect()
        ok = r.OpenPage(page)
        now = r.GetCurrentPage()
        out: Dict[str, Any] = {"ok": bool(ok), "page": now}
        if not ok:
            out["reason"] = (
                "Resolve refused the page switch. GetCurrentPage() is also None, which "
                "means Resolve is on the Project Manager screen rather than in a "
                "project: open a project in the Resolve window first."
                if now is None else
                f"Resolve refused the page switch and is still on {now!r}.")
        return out

    @mcp.tool()
    def project_settings(keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """Read project settings. Without `keys`, returns the common ones."""
        p = c.project()
        wanted = keys or ["timelineFrameRate", "timelineResolutionWidth",
                          "timelineResolutionHeight", "colorScienceMode",
                          "timelineOutputResolutionWidth"]
        return {k: p.GetSetting(k) for k in wanted}
