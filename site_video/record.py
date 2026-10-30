"""Play each scene on the real site and record it at 1920x1080, 30 fps, the way the hand-made promos were recorded.

- The page is laid out at a real 1920x1080 (no upscaling), or for a site with a narrow reading column at 1280x720
  drawn at 1.5x (still 1920x1080, but the content fills the frame), with scrollbars hidden, a cursor drawn in the
  brand's color (a headless browser shows none), eased scrolls and cursor moves, and real typing into search boxes.
- Nothing is sent but page loads: other requests (forms, likes, sign-ups) and analytics are blocked.
- Actions run at a natural pace; then the dead time between them is cut short and the scene is sped up (to 2.4x) or
  held on its last frame to land on exactly the planned length, with HANDLE spare frames at both ends so the edit can
  dissolve across each cut. Captions are not drawn here: they are separate overlays (cards.py).

Frames come from Chrome's screencast, which sends a frame whenever the page changes, so a long gap between frames is
time where nothing happened.
"""

import base64
import json
import os
import re
import shutil
import time
from typing import Dict, List

from .crawl import open_page
from .util import FPS, HANDLE, HEIGHT, WIDTH, ffmpeg, frames

# added to every page: the cursor, hidden scrollbars, and eased scrolling of whichever panel holds the content
OVERLAY = r"""(() => {
  if (window.__sv) return;
  const look = window.__svCursorStyle || 'dot', color = window.__svCursorColor || '#2f6fed';
  const css = `*::-webkit-scrollbar{display:none!important} *{scrollbar-width:none!important}
    #__sv_cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px)}
    #__sv_cur .d{position:absolute;left:-11px;top:-11px;width:22px;height:22px;border-radius:50%;box-sizing:border-box;
      background:${color};opacity:.55;border:2px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.35);transition:transform .12s,background .12s}
    #__sv_cur.down .d{transform:scale(.72);background:#e5484d;opacity:.8}
    #__sv_cur svg{display:block;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
    #__sv_cur.down svg{transform:scale(.85)}
    #__sv_cur .halo{position:absolute;left:-15px;top:-15px;width:40px;height:40px;border-radius:50%;
      background:rgba(255,214,64,.30);box-shadow:0 0 0 2px rgba(255,214,64,.55)}
    .__sv_rip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;z-index:2147483646;
      pointer-events:none;border:3px solid rgba(255,214,64,.95);animation:__sv_rip .6s ease-out forwards}
    @keyframes __sv_rip{to{transform:scale(4);opacity:0}}`;
  const add = () => {
    if (document.getElementById('__sv_cur')) return;
    const st = document.createElement('style'); st.textContent = css; document.documentElement.appendChild(st);
    const cur = document.createElement('div'); cur.id = '__sv_cur';
    const arrow = '<svg viewBox="0 0 24 24" width="24" height="24" style="margin:-2px 0 0 -4px"><path d="M4 2l15 11-6.5 1.2L16 21l-3 1.4-3.6-6.9L4 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const hand = '<svg viewBox="0 0 24 24" width="26" height="26" style="margin:-2px 0 0 -9px"><path d="M9 11V4.5a1.5 1.5 0 0 1 3 0V10h.5V8.5a1.5 1.5 0 0 1 3 0V10h.5V9.5a1.5 1.5 0 0 1 3 0V15c0 3.5-2.3 6-5.7 6H12c-2 0-3.3-.8-4.5-2.4L4.6 14.5a1.5 1.5 0 0 1 2.3-1.9L9 14.6z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    cur.innerHTML = look === 'dot' ? '<div class="d"></div>' : (look === 'ring' ? '<div class="halo"></div>' : '') + (look === 'hand' ? hand : arrow);
    if (look === 'none') cur.style.display = 'none';
    document.documentElement.appendChild(cur);
    document.addEventListener('mousemove', e => { cur.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; }, true);
    document.addEventListener('mousedown', e => { cur.classList.add('down');
      if (look !== 'ring') return;
      const r = document.createElement('div'); r.className = '__sv_rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
    document.addEventListener('mouseup', () => cur.classList.remove('down'), true);
  };
  window.__sv = {
    ensure: add,
    // Many app-like sites scroll an inner panel, not the page: scrolling goes to whichever element holds the target
    // (or, for top/bottom/a fraction, the one with the most to scroll), remembered in __svScroller for scrollTo.
    doc() { return document.scrollingElement || document.documentElement; },
    viewH(s) { return s === this.doc() ? innerHeight : s.clientHeight; },
    range(s) { return s.scrollHeight - this.viewH(s); },
    scrolls(el) { const st = getComputedStyle(el);
      return /(auto|scroll|overlay)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 4; },
    main() {
      let best = this.doc(), most = this.range(best);
      for (const el of document.querySelectorAll('body *')) {
        if (el.clientHeight < innerHeight * 0.3 || el.clientWidth < innerWidth * 0.3 || !this.scrolls(el)) continue;
        const r = this.range(el); if (r > most) { best = el; most = r; }
      }
      return best;
    },
    scrollerOf(el) { for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement)
        if (this.scrolls(p)) return p;
      return this.doc(); },
    targetFor(el, frac = 0.18) {
      const s = this.scrollerOf(el), top = s === this.doc() ? 0 : s.getBoundingClientRect().top;
      window.__svScroller = s;
      return el.getBoundingClientRect().top - top + s.scrollTop - this.viewH(s) * frac;
    },
    scrollTo(y, ms) { return new Promise(res => {
      const se = window.__svScroller || this.main(), y0 = se.scrollTop,
            y1 = Math.max(0, Math.min(this.range(se), y)), t0 = performance.now();
      document.documentElement.style.scrollBehavior = 'auto'; se.style.scrollBehavior = 'auto';
      const ease = k => k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      const step = now => { const k = Math.min(1, (now - t0) / ms); se.scrollTop = y0 + (y1 - y0) * ease(k);
        k < 1 ? requestAnimationFrame(step) : res(); };
      requestAnimationFrame(step); }); },
    targetY(what) {
      if (['top', 'bottom'].includes(what) || (String(what).trim() !== '' && !isNaN(Number(what)))) {
        const s = this.main(); window.__svScroller = s;
        return what === 'top' ? 0 : what === 'bottom' ? this.range(s) : Number(what) * this.range(s);
      }
      const want = String(what).toLowerCase().trim();
      const pick = sel => [...document.querySelectorAll(sel)].find(el => (el.innerText || '').toLowerCase().trim().startsWith(want))
        || [...document.querySelectorAll(sel)].find(el => (el.innerText || '').toLowerCase().includes(want));
      const el = pick('h1,h2,h3,h4') || pick('section,article,p,li,a,button');
      return el ? this.targetFor(el) : null;
    },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})()"""

CURSORS = ("dot", "arrow", "hand", "ring", "none")  # dot: a brand-colored dot; ring: an arrow with a highlight
SCROLL_S = 1.8                # an eased scroll, before the scene is fitted to its length
TYPE_MS = 85                  # per key
GAP_MAX = 0.6                 # nothing happening for longer than this is cut down to it
SPEED_MAX = 2.4
VERSION = 4      # bump when a recording would come out differently, so saved website clips are made again
# requests that never go out while recording: analytics and trackers (and anything but a plain page load)
BLOCK = ("google-analytics.com", "googletagmanager.com", "doubleclick.net", "segment.io", "segment.com", "hotjar",
         "facebook.net", "mixpanel", "clarity.ms", "posthog", "amplitude", "intercom", "sentry.io", "fullstory")


# never clicked, even on your own site with changes allowed
DANGER = re.compile(r"\b(log ?out|sign ?out|delete|remove|erase|destroy|buy|purchase|checkout|check out|pay|order now|"
                    r"subscribe|unsubscribe|cancel (my )?(account|subscription))\b", re.I)


def _guard(route, changes: bool = False):
    """Only page loads go out, unless changes are allowed (your own site): then anything but a DELETE does."""
    req = route.request
    if any(b in req.url for b in BLOCK) or (req.method == "DELETE" if changes else
                                            req.method not in ("GET", "HEAD", "OPTIONS")):
        return route.abort()
    return route.continue_()


class Recorder:
    """One browser for a job; scenes on the same URL continue where the last one left off."""

    def __init__(self, work: str, log=print, cursor: str = "dot", color: str = "#2f6fed", zoom: float = 1.0,
                 session: str = None, changes: bool = False):
        from playwright.sync_api import sync_playwright
        self.work, self.log = work, log
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        # zoom > 1: a smaller page drawn at a higher pixel ratio, so the frames are still WIDTH x HEIGHT
        self.zoom = zoom if zoom and zoom > 1 else 1.0
        self.vw, self.vh = round(WIDTH / self.zoom), round(HEIGHT / self.zoom)
        self.ctx = self.browser.new_context(viewport={"width": self.vw, "height": self.vh}, device_scale_factor=self.zoom,
                                            storage_state=session)      # signed in as you (session.py), if you did
        self.ctx.add_init_script(f"window.__svCursorStyle = {json.dumps(cursor if cursor in CURSORS else 'dot')};"
                                 f"window.__svCursorColor = {json.dumps(color or '#2f6fed')};")
        self.ctx.add_init_script(OVERLAY)
        self.ctx.route("**/*", lambda route: _guard(route, changes))
        self.page = self.ctx.new_page()
        self.cdp = self.ctx.new_cdp_session(self.page)
        self.url = None
        self.mouse = (self.vw * 0.62, self.vh * 0.55)
        self._frames: List = []
        self.misses: List[str] = []
        self._dir = None
        self.cdp.on("Page.screencastFrame", self._on_frame)

    def _miss(self, msg: str) -> None:
        """A step that did not happen: logged, and kept with the scene's clip for the review (review.py)."""
        self.log(msg)
        self.misses.append(msg.strip())

    def close(self):
        try:
            self.browser.close()
        finally:
            self._pw.stop()

    # ── capture ──
    def _on_frame(self, f):
        try:
            if self._dir is not None:
                path = os.path.join(self._dir, f"{len(self._frames):06d}.jpg")
                with open(path, "wb") as out:
                    out.write(base64.b64decode(f["data"]))
                self._frames.append((f["metadata"]["timestamp"], path))
        finally:
            try:
                self.cdp.send("Page.screencastFrameAck", {"sessionId": f["sessionId"]})
            except Exception:
                pass

    def _encode(self, t0: float, t1: float, seconds: float, out: str) -> float:
        """The captured frames as a clip of exactly `seconds` (plus HANDLE frames each side): pauses cut down to
        GAP_MAX, then sped up to fit or held on the last frame. Returns the speed used."""
        if not self._frames:
            raise RuntimeError("no frames were captured")
        shown = []                                   # (path, seconds on screen) after cutting dead time
        for i, (ts, path) in enumerate(self._frames):
            start = max(ts, t0)
            end = self._frames[i + 1][0] if i + 1 < len(self._frames) else t1
            if end <= t0:
                continue
            shown.append((path, min(GAP_MAX, max(0.001, end - start))))
        if not shown:
            shown = [(self._frames[-1][1], seconds)]
        length = sum(d for _, d in shown)
        speed = min(SPEED_MAX, max(1.0, length / seconds))
        lines = [f"file '{p}'\nduration {d / speed:.4f}" for p, d in shown]
        lines.append(f"file '{shown[-1][0]}'")
        lst = os.path.join(self._dir, "list.txt")
        with open(lst, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        n = frames(seconds)
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst,
               "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                      f"fps={FPS},tpad=stop_mode=clone:stop_duration={seconds + 2:.2f},trim=end_frame={n},"
                      f"tpad=start_mode=clone:start={HANDLE}:stop_mode=clone:stop={HANDLE},format=yuv420p",
               "-frames:v", str(n + 2 * HANDLE), "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
               "-movflags", "+faststart", out)
        return speed

    # ── actions ──
    def _glide(self, x: float, y: float, seconds: float) -> None:
        """Move the cursor along an eased path over `seconds`."""
        x0, y0 = self.mouse
        steps = max(8, int(seconds * 40))
        for i in range(1, steps + 1):
            k = i / steps
            e = 4 * k ** 3 if k < .5 else 1 - (-2 * k + 2) ** 3 / 2
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(seconds * 1000 / steps)
        self.mouse = (x, y)

    def _scroll(self, to) -> None:
        y = self.page.evaluate("t => window.__sv.targetY(t)", str(to))
        if y is None:
            self.log(f"  scroll target not found: {to!r}")
            return
        self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, int(SCROLL_S * 1000)])
        self.page.wait_for_timeout(SCROLL_S * 1000 + 300)

    def _find(self, text: str, field: bool = False):
        """The first visible element showing `text` (for a field: by its placeholder, label or name)."""
        if field:
            if text.strip():
                locs = [self.page.get_by_placeholder(text, exact=False), self.page.get_by_label(text, exact=False),
                        self.page.locator(f"input[name*={json.dumps(text)} i], textarea[name*={json.dumps(text)} i]")]
            else:
                locs = [self.page.locator("input[type=search], input[type=text], input:not([type]), textarea")]
        else:
            locs = [self.page.get_by_text(str(text), exact=False)]
        for loc in locs:
            try:
                for i in range(min(loc.count(), 8)):
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:
                continue
        return None

    def _reach(self, el):
        """Scroll el into view (in whichever panel holds it) and glide the cursor to it; its box, or None."""
        box = el.bounding_box()
        if box and not (60 < box["y"] < self.vh - 140):
            y = el.evaluate("e => window.__sv.targetFor(e, 0.4)")
            self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, 900])
            box = el.bounding_box()
        if box:
            self._glide(box["x"] + min(box["width"] * 0.5, 160), box["y"] + box["height"] * 0.55, 0.8)
        return box

    def _point_at(self, text: str, click: bool) -> None:
        if click and DANGER.search(text or ""):
            self.log(f"  not clicking {text!r}: it could delete, buy or sign out")
            click = False
        el = self._find(text)
        if el is None:
            self._miss(f"  not on the page: {text!r}")
            return
        if not self._reach(el):
            return
        self.page.wait_for_timeout(450)
        if click:
            url = self.page.url
            self.page.mouse.down()
            self.page.wait_for_timeout(90)
            self.page.mouse.up()
            try:
                self.page.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(700)
            if self.page.url != url:
                self.url = self.page.url
                self.page.evaluate("() => window.__sv && window.__sv.ensure()")

    def _type(self, into: str, text: str, enter: bool) -> None:
        el = self._find(into, field=True)
        if el is None:
            self._miss(f"  no field to type in: {into!r}")
            return
        if not self._reach(el):
            return
        self.page.mouse.down()
        self.page.mouse.up()
        try:
            el.fill("")
            if len(text) > 60:      # a list or a paragraph: pasted, as a person would, then a moment to read it
                el.fill(text)
                self.page.wait_for_timeout(700)
            else:
                el.press_sequentially(text, delay=TYPE_MS)
            self.page.wait_for_timeout(400)
            if enter:
                el.press("Enter")
                try:
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                self.page.wait_for_timeout(900)
                self.url = self.page.url
        except Exception as e:
            self._miss(f"  typing into {into!r} failed: {type(e).__name__}")

    def _run(self, actions: List[Dict]) -> None:
        for a in actions:
            self.page.wait_for_timeout(250)
            try:
                if a["do"] == "scroll":
                    self._scroll(a.get("to", "bottom"))
                elif a["do"] in ("hover", "click"):
                    self._point_at(a.get("text", ""), a["do"] == "click")
                elif a["do"] == "type":
                    self._type(a.get("into", ""), str(a.get("text", "")), bool(a.get("enter", True)))
                else:
                    self.page.wait_for_timeout(float(a.get("seconds") or 1.5) * 1000)
            except Exception as e:
                self._miss(f"  action {a} failed: {type(e).__name__}")

    # ── a scene ──
    def scene(self, scene: Dict, seconds: float, out: str) -> float:
        """Record one scene as a clip of exactly `seconds` plus handles; returns the speed it was fitted with."""
        if scene["url"].rstrip("/") != (self.url or "").rstrip("/"):
            open_page(self.page, scene["url"])
            self.url = scene["url"]
            self.page.evaluate("() => window.__sv.ensure()")
            self.page.mouse.move(*self.mouse)
            self.page.wait_for_timeout(600)
        self._dir = os.path.join(self.work, "frames_" + os.path.splitext(os.path.basename(out))[0])
        shutil.rmtree(self._dir, ignore_errors=True)
        os.makedirs(self._dir)
        self._frames = []
        self.misses = []
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": WIDTH, "maxHeight": HEIGHT})
        # nudge the cursor so the screencast sends a first frame even on a page that is already still
        self.page.mouse.move(self.mouse[0] + 1, self.mouse[1])
        t0 = time.time()
        try:
            self.page.wait_for_timeout(500)
            self._run(scene.get("actions") or [])
            self.page.wait_for_timeout(900)
        finally:
            t1 = time.time()
            self.cdp.send("Page.stopScreencast")
        self.page.wait_for_timeout(150)      # let the last frames arrive
        # screencast frames are stamped in seconds since the epoch, like time.time()
        speed = self._encode(t0, t1, seconds, out)
        if self.misses:
            with open(out[:-4] + ".misses.json", "w") as f:
                json.dump(self.misses, f)
        shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None
        return speed

    def hero(self, url: str, out_png: str) -> None:
        """A screenshot of the top of the site."""
        if url.rstrip("/") != (self.url or "").rstrip("/"):
            open_page(self.page, url)
            self.url = url
        self.page.evaluate("() => { window.__sv.doc().scrollTop = 0; window.__sv.main().scrollTop = 0; }")
        self.page.mouse.move(-50, -50)
        self.mouse = (self.vw * 0.62, self.vh * 0.55)
        self.page.wait_for_timeout(500)
        self.page.screenshot(path=out_png)
