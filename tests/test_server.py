"""Smoke tests against a fake Resolve. Run: python -m pytest tests

Real Resolve is not needed; the scripting module is replaced by a stub. This
proves the server wires up and the tools call the API as intended, not that
Resolve accepts those calls.
"""

import asyncio
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Clip:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name

    def GetClipProperty(self, k):
        return {"Duration": "00:00:05:00", "FPS": "24", "Resolution": "1920x1080"}[k]


class Folder:
    def __init__(self):
        self.clips, self.subs = [], []

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subs

    def GetName(self):
        return "Master"


class Timeline:
    def __init__(self, name):
        self.name, self.items = name, []

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 0

    def GetEndFrame(self):
        return 100

    def GetTrackCount(self, kind):
        return 1

    def AddMarker(self, *a):
        return True


class Pool:
    def __init__(self, project):
        self.project, self.root, self.appended = project, Folder(), []

    def GetRootFolder(self):
        return self.root

    def ImportMedia(self, paths):
        clips = [Clip(os.path.basename(p)) for p in paths]
        self.root.clips += clips
        return clips

    def CreateEmptyTimeline(self, name):
        tl = Timeline(name)
        self.project.timelines.append(tl)
        return tl

    def AppendToTimeline(self, infos):
        self.appended += infos
        return infos


class Project:
    def __init__(self):
        self.timelines, self.current, self.pool = [], None, Pool(self)

    def GetName(self):
        return "Demo"

    def GetMediaPool(self):
        return self.pool

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, tl):
        self.current = tl
        return True

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, i):
        return self.timelines[i - 1]

    def GetSetting(self, k):
        return "24"

    def IsRenderingInProgress(self):
        return False

    def GetRenderCodecs(self, fmt):
        return {"H.264": "H264"}

    def SetCurrentRenderFormatAndCodec(self, f, c):
        return True

    def SetRenderSettings(self, s):
        self.render_settings = s
        return True

    def AddRenderJob(self):
        return "job-1"

    def StartRendering(self, jobs):
        return True

    def GetRenderJobStatus(self, j):
        return {"JobStatus": "Rendering", "CompletionPercentage": 10}


class FakeResolve:
    def __init__(self):
        self.project = Project()

    def GetProductName(self):
        return "DaVinci Resolve Studio (fake)"

    def GetVersionString(self):
        return "0.0"

    def GetCurrentPage(self):
        return "edit"

    def OpenPage(self, p):
        return True

    def GetProjectManager(self):
        outer = self

        class PM:
            def GetCurrentProject(self):
                return outer.project

            def GetProjectListInCurrentFolder(self):
                return ["Demo"]

            def SaveProject(self):
                return True
        return PM()


def _install_fake():
    fake = FakeResolve()
    mod = types.ModuleType("DaVinciResolveScript")
    mod.scriptapp = lambda name: fake
    sys.modules["DaVinciResolveScript"] = mod
    from resolve_mcp import connection
    connection.reset()
    return fake


def _call(mcp, name, args=None):
    return asyncio.run(mcp.call_tool(name, args or {}))


def test_read_only_by_default():
    _install_fake()
    import resolve_mcp_server as s
    names = {t.name for t in asyncio.run(s.build(allow_write=False).list_tools())}
    assert {"resolve_status", "list_projects", "list_timelines", "timeline_info",
            "list_media_pool", "set_page", "project_settings"} == names


def test_write_tools_register_when_enabled():
    _install_fake()
    import resolve_mcp_server as s
    names = {t.name for t in asyncio.run(s.build(allow_write=True).list_tools())}
    assert {"import_media", "create_timeline", "append_clips", "add_title",
            "start_render", "render_status"} <= names


def test_edit_and_render_flow():
    fake = _install_fake()
    import resolve_mcp_server as s
    mcp = s.build(allow_write=True)
    _call(mcp, "import_media", {"paths": ["/x/a.mp4", "/x/b.mp4"]})
    _call(mcp, "create_timeline", {"name": "Cut 1"})
    _call(mcp, "append_clips", {"clips": [
        {"name": "a.mp4", "start_frame": 10, "end_frame": 50}, {"name": "b.mp4"}]})
    infos = fake.project.pool.appended
    assert infos[0]["startFrame"] == 10 and infos[0]["endFrame"] == 50
    assert "startFrame" not in infos[1]
    _call(mcp, "start_render", {"target_dir": "/out", "name": "cut1"})
    assert fake.project.render_settings["CustomName"] == "cut1"


def test_unreachable_resolve_reports_reason():
    sys.modules["DaVinciResolveScript"] = types.SimpleNamespace(scriptapp=lambda n: None)
    from resolve_mcp import connection
    connection.reset()
    import resolve_mcp_server as s
    out = _call(s.build(allow_write=False), "resolve_status")
    assert "open DaVinci Resolve" in str(out)
