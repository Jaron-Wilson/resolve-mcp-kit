"""Locate Resolve's scripting module and attach to a running Resolve.

Resolve's scripting API ships with the application, not on PyPI, so its
location is added to sys.path before DaVinciResolveScript is imported.
Override the defaults with RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB.
"""

import os
import sys


def _defaults():
    if sys.platform.startswith("win"):
        pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        api = os.path.join(pd, "Blackmagic Design", "DaVinci Resolve",
                           "Support", "Developer", "Scripting")
        lib = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    elif sys.platform == "darwin":
        api = ("/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
               "Developer/Scripting")
        lib = ("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/"
               "Libraries/Fusion/fusionscript.so")
    else:
        api = "/opt/resolve/Developer/Scripting"
        lib = "/opt/resolve/libs/Fusion/fusionscript.so"
    return api, lib


_API_DEFAULT, _LIB_DEFAULT = _defaults()
API_DIR = os.environ.get("RESOLVE_SCRIPT_API", _API_DEFAULT)
LIB_PATH = os.environ.get("RESOLVE_SCRIPT_LIB", _LIB_DEFAULT)
os.environ.setdefault("RESOLVE_SCRIPT_API", API_DIR)
os.environ.setdefault("RESOLVE_SCRIPT_LIB", LIB_PATH)
_MODULES = os.path.join(API_DIR, "Modules")
if _MODULES not in sys.path:
    sys.path.append(_MODULES)

_resolve = None


def connect():
    """Attach to a running Resolve, or explain why we cannot.

    The API returns None rather than raising when it cannot attach, which
    reads as a mysterious null far from the cause, so say plainly why.
    """
    global _resolve
    if _resolve is not None:
        return _resolve
    try:
        import DaVinciResolveScript as dvr
    except ImportError as e:
        raise RuntimeError(
            f"Resolve's scripting module is not importable ({e}). Expected it under "
            f"{_MODULES}. Check that DaVinci Resolve is installed, or set "
            "RESOLVE_SCRIPT_API to its Developer/Scripting folder.")
    r = dvr.scriptapp("Resolve")
    if r is None:
        raise RuntimeError(
            "Could not attach to Resolve. It returns nothing rather than an error "
            "when the application is not running, so: open DaVinci Resolve and try "
            "again. In Resolve, set Preferences > System > General > External "
            "scripting using to Local. The free edition may not allow external "
            "scripting at all.")
    _resolve = r
    return r


def reset():
    """Forget the cached handle (after Resolve restarts, and for tests)."""
    global _resolve
    _resolve = None


def project():
    p = connect().GetProjectManager().GetCurrentProject()
    if p is None:
        raise RuntimeError("No project is open in Resolve.")
    return p


def find_timeline(p, name=None):
    if not name:
        tl = p.GetCurrentTimeline()
        if tl is None:
            raise RuntimeError("No timeline is open.")
        return tl
    for i in range(1, (p.GetTimelineCount() or 0) + 1):
        cand = p.GetTimelineByIndex(i)
        if cand.GetName() == name:
            return cand
    raise RuntimeError(f"No timeline named {name!r}")
