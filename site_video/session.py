"""Signing in to your own site, once, so the explorer and the recorder see it the way you do.

`signin(url)` opens a real browser window on this computer at the site; you log in there by hand and close the window.
It is your installed Chrome or Edge, started as a plain browser (no debugging port, no automation switches) with a
profile of its own (SITE_VIDEO_SESSIONS/profile): Google refuses to sign anyone in to a browser that is driven or
debuggable ("This browser or app may not be secure"), so "Sign in with Google" only works this way. The window looks
like a new, empty browser: that is the profile. When you close it, site_video opens that profile in the background
and copies the site's cookies out. The videos use the site's own sign-in cookie, not your Google account.
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


def _keep_session_cookies(profile: str) -> None:
    """Set the profile to "Continue where you left off". A browser set that way keeps session cookies (the ones with
    no expiry date, which many sites use for their login) on disk when it closes; otherwise closing the window would
    throw the sign-in away before it could be read."""
    d = os.path.join(profile, "Default")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "Preferences")
    try:
        with open(p, encoding="utf-8") as f:
            prefs = json.load(f)
    except Exception:
        prefs = {}
    if prefs.get("session", {}).get("restore_on_startup") == 1:
        return
    prefs.setdefault("session", {})["restore_on_startup"] = 1
    _save(prefs, p)


def _profile_in_use(profile: str) -> bool:
    """Whether a browser still has the profile open (an earlier sign-in window, say)."""
    if os.name == "nt":
        lock = os.path.join(profile, "lockfile")     # held open with no sharing while the browser runs
        if not os.path.exists(lock):
            return False
        try:
            with open(lock, "a"):
                return False
        except OSError:
            return True
    try:
        pid = int(os.readlink(os.path.join(profile, "SingletonLock")).rsplit("-", 1)[1])
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


def _save(state, out: str) -> None:
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, out)


def _signin_real(exe: str, url: str, out: str, log, wait_s: int) -> bool:
    """Chrome/Edge started as a completely ordinary browser on a profile of its own: no debugging port and no
    automation switches, since Google refuses to sign in a browser that has either. Once the person closes the
    window, the same profile is opened in the background and the site's cookies are read from it."""
    import subprocess
    from playwright.sync_api import sync_playwright
    profile = os.path.join(folder(), "profile")
    _keep_session_cookies(profile)
    args = [exe, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--new-window", url]
    if os.name != "nt":
        # off Windows a plain Chrome encrypts cookies with the desktop keyring, which the background reader below
        # cannot open; Windows keys them to the user account, the same for both
        args.insert(2, "--password-store=basic")
    started = time.time()
    proc = subprocess.Popen(args)
    end = started + wait_s
    while time.time() < end and proc.poll() is None:
        time.sleep(2)
    if proc.poll() is None:
        log("the sign-in window was still open after the wait; reading what it has so far")
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
    elif time.time() - started < 15 and _profile_in_use(profile):
        # a browser already had this profile open (an earlier sign-in window): ours handed the page to it and quit
        log("an earlier sign-in window is still open; the page opened there. Sign in, then close that window")
        while time.time() < end and _profile_in_use(profile):
            time.sleep(3)
    time.sleep(2)                                   # let the browser finish writing its cookie store
    saved = None
    with sync_playwright() as pw:
        for attempt in range(3):
            try:
                ctx = pw.chromium.launch_persistent_context(profile, executable_path=exe, headless=True)
                try:
                    # the site is opened once so its own storage is read too: sign-ins through Firebase or
                    # Supabase ("Sign in with Google" on many sites) keep the login there, not in a cookie
                    page = ctx.new_page()
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_timeout(2500)
                    except Exception as e:
                        log(f"  could not open {url} to read its storage ({type(e).__name__}); cookies only")
                    saved = ctx.storage_state(indexed_db=True)
                finally:
                    ctx.close()
                break
            except Exception as e:                  # the profile may still be locked for a moment
                log(f"  reading the sign-in ({type(e).__name__}); trying again")
                time.sleep(4)
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
