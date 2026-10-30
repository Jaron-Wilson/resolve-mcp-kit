"""Signing in to your own site, once, so the explorer and the recorder see it the way you do.

`signin(url)` opens a real browser window on this computer at the site; you log in there by hand and close the window.
It is your installed Chrome or Edge, started as a normal browser with a profile of its own (SITE_VIDEO_SESSIONS/
profile), not a browser Playwright launched: Google refuses to sign anyone in to those ("This browser or app may not
be secure"), so "Sign in with Google" only works this way. site_video only reads the window's cookies over Chrome's
debugging port while it is open. The videos use the site's own sign-in cookie, not your Google account.
The browser's cookies and storage for that site are saved in SITE_VIDEO_SESSIONS (~/.site-video/sessions), one file
per site, and every later video of that site uses them. Your password never passes through site_video. `forget(url)`
deletes the file. Only sign in to sites you own or are allowed to record.
"""

import json
import os
import re
import threading
import time
from typing import Dict, Optional
from urllib.parse import urlparse

_LOCK = threading.Lock()
_OPEN: Dict[str, float] = {}          # sites with a sign-in window open now: host -> since


def folder() -> str:
    d = os.environ.get("SITE_VIDEO_SESSIONS") or os.path.join(os.path.expanduser("~"), ".site-video", "sessions")
    os.makedirs(d, exist_ok=True)
    return d


def host(url: str) -> str:
    h = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]+(:\d+)?", h or ""):
        raise ValueError("give the site's address, like https://example.com")
    return h


def path_for(url: str) -> str:
    return os.path.join(folder(), host(url).replace(":", "_") + ".json")


def state_for(url: str) -> Optional[str]:
    """The saved sign-in for this site, for new_context(storage_state=...), or None."""
    if not url:
        return None
    try:
        p = path_for(url)
    except ValueError:
        return None
    return p if os.path.isfile(p) else None


def status(url: str) -> Dict:
    h = host(url)
    p = state_for(url)
    return {"site": h, "signed_in": bool(p), "since": os.path.getmtime(p) if p else None, "window_open": h in _OPEN}


def forget(url: str) -> bool:
    p = state_for(url)
    if p:
        os.unlink(p)
    return bool(p)


def _real_browser() -> str:
    """An installed Chrome or Edge, or "" (then Playwright's own Chromium is used, without Google sign-in)."""
    import shutil
    env = os.environ.get("SITE_VIDEO_BROWSER", "")
    if env and os.path.isfile(env):
        return env
    pf = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for path in [os.path.join(b, *tail) for b in pf if b for tail in (
            ("Google", "Chrome", "Application", "chrome.exe"), ("Microsoft", "Edge", "Application", "msedge.exe"))] + [
            shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "microsoft-edge")] + [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        if path and os.path.isfile(path):
            return path
    return ""


def _free_port() -> int:
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def _save(state, out: str) -> None:
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, out)


def _signin_real(exe: str, url: str, out: str, log, wait_s: int) -> bool:
    """Chrome/Edge as a plain process with its own profile; its cookies read over the debugging port until it closes."""
    import subprocess
    from playwright.sync_api import sync_playwright
    port = _free_port()
    profile = os.path.join(folder(), "profile")
    proc = subprocess.Popen([exe, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
                             "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                             "--new-window", url])
    saved, end = None, time.time() + wait_s
    with sync_playwright() as pw:
        browser = None
        while time.time() < end and proc.poll() is None:
            try:
                if browser is None or not browser.is_connected():
                    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=5000)
                ctxs = browser.contexts
                if ctxs:
                    saved = ctxs[0].storage_state()      # kept current: once the window is closed it cannot be read
            except Exception:
                browser = None
            time.sleep(2)
        if proc.poll() is None:
            proc.terminate()
    if saved:
        h = host(url)
        # only this site's cookies are kept (the profile also holds Google's, which the videos do not need)
        saved["cookies"] = [c for c in saved.get("cookies", []) if c.get("domain", "").lstrip(".").endswith(h.split(":")[0])
                            or h.split(":")[0].endswith(c.get("domain", "").lstrip("."))]
        def same(o):
            try:
                return host(o.get("origin", "")) == h
            except ValueError:
                return False
        saved["origins"] = [o for o in saved.get("origins", []) if same(o)]
        _save(saved, out)
    return bool(saved)


def signin(url: str, log=print, wait_s: int = 900) -> Dict:
    """Open a browser window at `url` for the person to sign in, and save the session when they close it (or after
    wait_s). Runs on the computer whose screen the person is at."""
    h = host(url)
    with _LOCK:
        if h in _OPEN:
            raise ValueError(f"a sign-in window for {h} is already open")
        _OPEN[h] = time.time()
    try:
        from playwright.sync_api import sync_playwright
        out = path_for(url)
        full = url if "://" in url else "https://" + url
        exe = _real_browser()
        if exe:
            log(f"sign in to {h} in the {os.path.basename(exe)} window that opened, then close it")
            ok = _signin_real(exe, full, out, log, wait_s)
            log(f"saved the sign-in for {h}" if ok else f"nothing saved for {h}")
            return status(url)
        log("no Chrome or Edge found: using the built-in browser (Google sign-in will not work in it)")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            ctx = browser.new_context(storage_state=state_for(url), viewport=None, no_viewport=True)
            page = ctx.new_page()
            page.goto(url if "://" in url else "https://" + url, wait_until="domcontentloaded", timeout=45000)
            log(f"sign in to {h} in the window that opened, then close it")
            end, saved = time.time() + wait_s, None
            while time.time() < end and browser.is_connected() and ctx.pages:
                try:
                    saved = ctx.storage_state()          # kept up to date: once the window is closed it cannot be read
                except Exception:
                    break
                time.sleep(2)
            if saved:
                _save(saved, out)
            try:
                browser.close()
            except Exception:
                pass
        log(f"saved the sign-in for {h}" if saved else f"nothing saved for {h}")
        return status(url)
    finally:
        with _LOCK:
            _OPEN.pop(h, None)
