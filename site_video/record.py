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
from typing import Dict, List, Optional

from .crawl import open_page
from .util import FPS, HANDLE, HEIGHT, WIDTH, ffmpeg, frames, live

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
    if (look === 'none' || (look === 'auto' && sessionStorage.getItem('__svCur') !== '1')) cur.style.display = 'none';
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
    // the element showing `want` inside the smallest block that also shows `row` (a button in one row of a list)
    within(row, want, box) {
      const low = s => (s || '').toLowerCase().replace(/\s+/g, ' ').trim(), R = low(row), W = low(want);
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      // real buttons and links first; plain text only when the row has none showing `want`
      const sels = box ? ['input[type=checkbox], [role=checkbox], .p-checkbox, .mat-mdc-checkbox']
                       : ['button, a, [role=button], [role=menuitem], [role=tab], label', 'span, td, div'];
      let best = null, area = Infinity;
      for (const sel of sels) {
        for (const h of document.querySelectorAll(sel)) {
          if (!vis(h) && !(box && h.matches('input'))) continue;
          if (!box && !low(h.innerText || h.getAttribute('aria-label') || h.value).includes(W)) continue;
          for (let p = h.parentElement; p && p !== document.body; p = p.parentElement)
            if (low(p.innerText).includes(R)) { const r = p.getBoundingClientRect(), a = r.width * r.height;
              if (a < area) { area = a; best = h; } break; }
        }
        if (best) break;
      }
      if (best && box && best.matches('input') && !vis(best)) best = best.closest('label, .p-checkbox, div') || best;
      return best;
    },
    norm(s) { return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ')
      .map(w => w.length > 3 ? w.replace(/s$/, '') : w).join(' '); },
    vis(e) { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; },
    PRESS: 'button, a, [role=button], [role=menuitem], [role=tab], label',
    // a button whose label is `want` once case, hyphens and plurals are ignored ("Create Part-Ins" = "Create Part In")
    fuzzy(want) { const W = this.norm(want); if (!W) return null;
      const all = [...(this.modal() || document).querySelectorAll(this.PRESS)].filter(e => this.vis(e));
      const lab = e => this.norm(e.innerText || e.getAttribute('aria-label'));
      return all.find(e => lab(e) === W) || all.find(e => lab(e).includes(W)) || null; },
    modal() { return [...document.querySelectorAll('dialog[open], [role=dialog], [role=alertdialog], [aria-modal=true], ' +
      '.p-dialog, .mat-mdc-dialog-container')].filter(e => this.vis(e)).pop() || null; },
    inModal(t) { const d = this.modal(), T = this.norm(t); if (!d || !T) return false;
      return this.norm(d.innerText).includes(T) || [...d.querySelectorAll('input, textarea')].some(i =>
        this.norm(i.placeholder + ' ' + i.name + ' ' + i.getAttribute('aria-label')).includes(T)); },
    // the go-ahead button of the open dialog: one sharing a word with what was clicked, else a confirm word
    confirm(clicked) { const d = this.modal(); if (!d) return null;
      const no = /\b(cancel|close|back|no|not now|dismiss|delete|remove|discard|keep editing)\b/i;
      const ok = [...d.querySelectorAll('button, [role=button], a')].filter(b => this.vis(b) && (b.innerText || '').trim()
        && !no.test(b.innerText));
      const words = this.norm(clicked).split(' ').filter(w => w.length > 2);
      return ok.find(b => words.some(w => this.norm(b.innerText).split(' ').includes(w)))
        || ok.find(b => /\b(ok|yes|confirm|continue|save|create|convert|add|done|finish|complete|submit|apply|anyway)\b/i.test(b.innerText))
        || null; },
    clickables() { const d = this.modal(), top = d || document, seen = new Set(), uniq = xs => xs.filter(x => x && !seen.has(x) && seen.add(x));
      const t = e => (e.innerText || e.getAttribute('aria-label') || e.value || '').replace(/\s+/g, ' ').trim();
      // each row: its own text, its own buttons, and whether it has a checkbox
      const rows = [...top.querySelectorAll('tr, li, [role=row]')].filter(r => this.vis(r) &&
        r.querySelector('button, [role=button], input[type=checkbox], [role=checkbox], a')).slice(0, 30).map(r => {
          const bs = [...r.querySelectorAll('button, [role=button], a')].filter(e => this.vis(e)).map(t).filter(Boolean);
          let txt = t(r); for (const b of bs) txt = txt.replace(b, ' ');
          return {row: txt.replace(/\s+/g, ' ').trim().slice(0, 90), buttons: bs.slice(0, 6),
                  checkbox: !!r.querySelector('input[type=checkbox], [role=checkbox], .p-checkbox')}; });
      return {heading: t(document.querySelector('h1') || document.body).slice(0, 120), dialog: d ? t(d).slice(0, 300) : '',
        buttons: uniq([...top.querySelectorAll(this.PRESS)].filter(e => this.vis(e)).map(e => t(e).slice(0, 60))).slice(0, 60),
        rows, fields: uniq([...top.querySelectorAll('input:not([type=checkbox]):not([type=hidden]), textarea')].filter(e => this.vis(e))
          .map(e => e.placeholder || e.getAttribute('aria-label') || e.name)).slice(0, 15)}; },
    // after something was created: the "View ..." / "Open ..." link a dialog or the page offers to go to it
    onward() { const top = this.modal() || document;
      return [...top.querySelectorAll('a, button, [role=button]')].filter(e => this.vis(e))
        .find(e => /^(view|open|go to|see|show)\b/i.test((e.innerText || '').trim())) || null; },
    checked(el) { const i = el.matches('input') ? el : el.querySelector('input[type=checkbox]');
      return i ? i.checked : el.getAttribute('aria-checked') === 'true' || /checked/.test(el.className); },
    cursor(on) { try { sessionStorage.setItem('__svCur', on ? '1' : '0'); } catch (e) {}
      add(); const c = document.getElementById('__sv_cur'); if (c) c.style.display = on ? '' : 'none'; },
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

CURSORS = ("auto", "dot", "arrow", "hand", "ring", "none")  # dot: a brand-colored dot; ring: an arrow with a highlight
POINTING = ("hover", "click", "type")   # auto: a scene with one of these shows an arrow; one that only scrolls, none
SCROLL_S = 1.8                # an eased scroll, before the scene is fitted to its length
TYPE_MS = 85                  # per key
GAP_MAX = 0.6                 # nothing happening for longer than this is cut down to it
SPEED_MAX = 2.4
VERSION = 6      # bump when a recording would come out differently, so saved website clips are made again
# requests that never go out while recording: analytics and trackers (and anything but a plain page load)
BLOCK = ("google-analytics.com", "googletagmanager.com", "doubleclick.net", "segment.io", "segment.com", "hotjar",
         "facebook.net", "mixpanel", "clarity.ms", "posthog", "amplitude", "intercom", "sentry.io", "fullstory")


# never clicked, even on your own site with changes allowed
class _Missing(Exception):
    """A step's target is not on the page (yet)."""

    def __init__(self, msg: str):
        super().__init__(msg)
        self.msg = msg


REPAIR = """You help a browser recorder make a promo video of the person's own website. One step of the script could not
be done because its target is not on the page as written (a label worded differently, or a page that only exists
after earlier steps). You get that step, what the scene should show, and what the page offers right now: its
heading, whether a dialog is open, its buttons and links, rows of lists (each with its own text, its own buttons and
whether it has a checkbox), and text fields. A button that sits in a row is clicked with "in" set to that row's text.
Only check or uncheck rows that have a checkbox. To act on many rows (create something for each), do the first few. Answer with the steps that do what the step meant on this page, using only labels exactly as listed:
{"do": "click", "text": "<button>"}, {"do": "click", "text": "<button>", "in": "<text of its row>"},
{"do": "check"|"uncheck", "text": "<text of the row>"}, {"do": "type", "into": "<field>", "text": "...", "enter": false},
{"do": "scroll", "to": "<heading>|top|bottom"}. At most 4 steps. When what the step needs is on another page that this
one leads to (a "View ..." or "Open ..." link after something was just created, a tab, a row's name), start with the
click that goes there; on that page the rest is worked out again. Never delete, remove, buy, pay or sign out."""


DANGER = re.compile(r"\b(log ?out|sign ?out|delete|remove|erase|destroy|buy|purchase|checkout|check out|pay|order now|"
                    r"subscribe|unsubscribe|cancel (my )?(account|subscription))\b", re.I)


def _guard(route, changes: bool = False):
    """Only page loads go out, unless changes are allowed (your own site): then anything but a DELETE does."""
    req = route.request
    if any(b in req.url for b in BLOCK) or (req.method == "DELETE" if changes else
                                            req.method not in ("GET", "HEAD", "OPTIONS")):
        return route.abort()
    return route.continue_()



def human_path(x0: float, y0: float, x1: float, y1: float, seconds: float = None, size: float = 40, fps: int = 60):
    """The points a hand moves a mouse through from (x0, y0) to (x1, y1), as [(x, y, seconds to wait), ...].

    - time: Fitts's law, T = 0.12 + 0.11 * log2(distance / size + 1) seconds, a little longer for far or small targets
    - speed: minimum-jerk, s(k) = 10k^3 - 15k^4 + 6k^5, the smooth start and stop of a real arm
    - curve: a quadratic Bezier bent sideways by 4 to 12% of the distance (the wrist pivots, so paths arc)
    - wobble: two slow sines, at most about 2 px, fading out at both ends
    - overshoot: past 300 px it lands 1.5 to 3% beyond the target, then a short correction back
    Seeded by the two points, so the same move is drawn the same way every time."""
    import math
    import random
    r = random.Random(f"{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}")
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    if dist < 2:
        return [(x1, y1, 0.05)]
    if seconds is None:
        seconds = 0.12 + 0.11 * math.log2(dist / max(size, 8) + 1)
        seconds = min(1.3, max(0.35, seconds * r.uniform(0.9, 1.15)))
    ux, uy = dx / dist, dy / dist                     # along the move, and across it
    nx, ny = -uy, ux
    pts = []

    def leg(ax, ay, bx, by, secs, bend, wob):
        d = math.hypot(bx - ax, by - ay)
        cx, cy = (ax + bx) / 2 + nx * d * bend, (ay + by) / 2 + ny * d * bend
        ph1, ph2 = r.uniform(0, 6.3), r.uniform(0, 6.3)
        steps = max(6, int(secs * fps))
        for i in range(1, steps + 1):
            k = i / steps
            s = 10 * k ** 3 - 15 * k ** 4 + 6 * k ** 5
            px = (1 - s) ** 2 * ax + 2 * (1 - s) * s * cx + s * s * bx
            py = (1 - s) ** 2 * ay + 2 * (1 - s) * s * cy + s * s * by
            w = wob * math.sin(math.pi * k) * (math.sin(2 * math.pi * 1.3 * k + ph1) + 0.5 * math.sin(2 * math.pi * 3.1 * k + ph2))
            pts.append((px + nx * w, py + ny * w, secs / steps))

    bend = r.choice((-1, 1)) * r.uniform(0.04, 0.12)
    wob = min(2.0, dist * 0.004)
    if dist > 300:
        over = dist * r.uniform(0.015, 0.03)
        ox, oy = x1 + ux * over + nx * r.uniform(-1, 1) * over * 0.3, y1 + uy * over + ny * r.uniform(-1, 1) * over * 0.3
        leg(x0, y0, ox, oy, seconds * 0.82, bend, wob)
        leg(ox, oy, x1, y1, seconds * 0.18, 0, 0)
    else:
        leg(x0, y0, x1, y1, seconds, bend, wob)
    pts[-1] = (x1, y1, pts[-1][2])
    return pts

class Recorder:
    """One browser for a job; scenes on the same URL continue where the last one left off."""

    def __init__(self, work: str, log=print, cursor: str = "dot", color: str = "#2f6fed", zoom: float = 1.0,
                 session: str = None, changes: bool = False, brief: str = "", model: str = ""):
        from playwright.sync_api import sync_playwright
        self.work, self.log, self.cursor, self.changes = work, log, cursor, changes
        self.brief = brief if brief and brief.strip().lower() != "auto" else ""
        # the model that works out a step again (_repair): SITE_VIDEO_REPAIR_MODEL, else the job's script model
        self.model = os.environ.get("SITE_VIDEO_REPAIR_MODEL") or model or ""
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
                data = base64.b64decode(f["data"])
                with open(path, "wb") as out:
                    out.write(data)
                self._frames.append((f["metadata"]["timestamp"], path))
                live(os.path.dirname(os.path.abspath(self.work)), data)
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
    def _glide(self, x: float, y: float, seconds: float = None, size: float = 40) -> None:
        """Move the cursor to (x, y) the way a hand does (human_path): a slight curve, a smooth start and stop, a
        little wobble, and on long moves a small overshoot that is corrected. Without `seconds` the move takes as long
        as Fitts's law says for that distance and a target `size` px wide."""
        x0, y0 = self.mouse
        path = human_path(x0, y0, x, y, seconds, size)
        for px, py, wait in path:
            self.page.mouse.move(px, py)
            self.page.wait_for_timeout(wait * 1000)
        self.mouse = (x, y)

    def _scroll(self, to) -> None:
        y = self.page.evaluate("t => window.__sv.targetY(t)", str(to))
        if y is None:
            self.log(f"  scroll target not found: {to!r}")
            return
        self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, int(SCROLL_S * 1000)])
        self.page.wait_for_timeout(SCROLL_S * 1000 + 300)

    def _find(self, text: str, field: bool = False, wait: float = 0):
        """The first visible element showing `text` (for a field: by its placeholder, label or name), waiting up to
        `wait` seconds for it to appear (a result, a dialog or a page an earlier step opened)."""
        end = time.time() + wait
        while True:
            el = self._find_now(text, field)
            if el is not None or time.time() >= end:
                return el
            self.page.wait_for_timeout(400)

    def _wait(self) -> float:
        """How long to wait for a step's target: longer on your own site, where steps create things."""
        return 12.0 if self.changes else 3.0

    def _find_in(self, row: str, text: str, box: bool = False):
        """`text` inside the row that shows `row` (box: that row's checkbox), waiting like _find."""
        end = time.time() + self._wait()
        while True:
            h = self.page.evaluate_handle("([r, t, b]) => window.__sv.within(r, t, b)", [row, text, box]).as_element()
            if h is not None or time.time() >= end:
                return h
            self.page.wait_for_timeout(400)

    def _find_now(self, text: str, field: bool = False):
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
        if not field and str(text).strip():
            try:
                return self.page.evaluate_handle("t => window.__sv.fuzzy(t)", str(text)).as_element()
            except Exception:
                return None
        return None

    def _reach(self, el):
        """Scroll el into view (in whichever panel holds it) and glide the cursor to it; its box, or None."""
        box = el.bounding_box()
        if box and not (60 < box["y"] < self.vh - 140):
            y = el.evaluate("e => window.__sv.targetFor(e, 0.4)")
            self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, 900])
            box = el.bounding_box()
        if box:
            # near the middle, not dead center: people land somewhere inside the target
            import random
            r = random.Random(f'{box["x"]:.0f},{box["y"]:.0f}')
            w, h = box["width"], box["height"]
            self._glide(box["x"] + min(w * 0.5, 160) + r.uniform(-1, 1) * min(w * 0.15, 18),
                        box["y"] + h * 0.55 + r.uniform(-1, 1) * h * 0.12, size=min(w, h) or 40)
        return box

    def _point_at(self, text: str, click: bool, row: str = "") -> None:
        if click and DANGER.search(text or ""):
            self.log(f"  not clicking {text!r}: it could delete, buy or sign out")
            click = False
        el = self._find_in(row, text) if row else self._find(text, wait=self._wait() if click else 1.5)
        if el is None:
            raise _Missing(f"  not on the page: {text!r}" + (f" in the row {row!r}" if row else ""))
        if not self._reach(el):
            return
        self.page.wait_for_timeout(450)
        if click:
            self._press()

    def _press(self) -> None:
        """Click where the cursor is, then give what the click starts (a page, a dialog, a save) time to show."""
        url = self.page.url
        self.page.mouse.down()
        self.page.wait_for_timeout(90)
        self.page.mouse.up()
        try:
            self.page.wait_for_load_state("load", timeout=8000)
            if self.changes:
                self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self.page.wait_for_timeout(700)
        if self.page.url != url:
            self.url = self.page.url
            self.page.evaluate("() => window.__sv && window.__sv.ensure()")

    def _tick(self, row: str, on: bool) -> None:
        """Check or uncheck the checkbox in the row that shows `row`. Unchecking on a page with no checkboxes at all
        is nothing to do: nothing there is selected."""
        if not on and not self.page.evaluate(
                "() => !!document.querySelector('input[type=checkbox], [role=checkbox], .p-checkbox')"):
            self.log(f"  {row!r}: no checkboxes on this page, so it is already left out")
            return
        el = self._find_in(row, "", box=True)
        if el is None:
            raise _Missing(f"  no checkbox in the row {row!r}")
        if bool(el.evaluate("e => window.__sv.checked(e)")) == on:
            return
        if self._reach(el):
            self.page.wait_for_timeout(300)
            self._press()

    def _type(self, into: str, text: str, enter: bool) -> None:
        el = self._find(into, field=True, wait=self._wait())
        if el is None:
            raise _Missing(f"  no field to type in: {into!r}")
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
            if enter and el.evaluate("e => e.tagName") != "TEXTAREA":
                el.press("Enter")
                try:
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                self.page.wait_for_timeout(900)
                self.url = self.page.url
        except Exception as e:
            self._miss(f"  typing into {into!r} failed: {type(e).__name__}")

    def _do(self, a: Dict) -> None:
        if a["do"] == "scroll":
            self._scroll(a.get("to", "bottom"))
        elif a["do"] in ("hover", "click"):
            self._point_at(str(a.get("text", "")), a["do"] == "click", str(a.get("in") or ""))
        elif a["do"] in ("check", "uncheck"):
            self._tick(str(a.get("text", "")), a["do"] == "check")
        elif a["do"] == "type":
            self._type(str(a.get("into", "")), str(a.get("text", "")), bool(a.get("enter", True)))
        else:
            self.page.wait_for_timeout(float(a.get("seconds") or 1.5) * 1000)

    def _confirm(self, clicked: str, then: Optional[Dict]) -> None:
        """On your own site, a click that opened a confirm dialog is followed by its go-ahead button ("Convert",
        "Create Part In", "Complete anyway"; never Cancel, Close or Delete), unless the scene's next step is in it."""
        if then and self.page.evaluate("t => window.__sv.inModal(t)", str(then.get("text") or then.get("into") or "")):
            return
        el = self.page.evaluate_handle("c => window.__sv.confirm(c)", clicked).as_element()
        if el is None:
            return
        label = (el.inner_text() or "").strip()
        if DANGER.search(label):
            return
        self.log(f"  confirming the dialog: {label!r}")
        if self._reach(el):
            self.page.wait_for_timeout(350)
            self._press()
            self.page.wait_for_timeout(1200)        # the dialog closes and what it did shows (a toast, a new page)

    def _onward(self, a: Dict) -> bool:
        """On your own site, a step whose target is missing right after something was created: follow the "View ..."
        link the dialog or page offers, then try the step again there."""
        el = self.page.evaluate_handle("() => window.__sv.onward()").as_element()
        label = (el.inner_text() or "").strip() if el is not None else ""
        if not label or DANGER.search(label):
            return False
        self.log(f"  {a.get('text') or a.get('into')!r} is not here yet; following {label!r}")
        if not self._reach(el):
            return False
        self.page.wait_for_timeout(350)
        self._press()
        try:
            self._do(a)
            return True
        except _Missing:
            return False

    def _repair(self, a: Dict, scene: Optional[Dict], later: Optional[List[Dict]] = None, depth: int = 0) -> bool:
        """On your own site, a step whose target is not there (a label worded differently, a page nobody had seen
        before the steps that made it) is worked out again from what the page shows now: the script model gets the
        step, the scene's caption and the page's buttons, rows and fields, and answers with the steps to do instead."""
        from . import llm
        try:
            now = self.page.evaluate("() => window.__sv.clickables()")
            caption = " / ".join((scene or {}).get("captions") or [(scene or {}).get("caption") or ""])
            reply = llm.chat(REPAIR, (f"The person's brief for the whole video:\n{self.brief[:3000]}\n\n" if self.brief else "")
                             + f"The step that could not be done: {json.dumps(a)}\n"
                                     f"The scene's steps after it: {json.dumps(later or [])[:800]}\n"
                                     f"What the scene should show: {caption}\nNarration: {(scene or {}).get('narration', '')}\n"
                                     f"The page now: {json.dumps(now)[:6000]}\n\nReply with only JSON: "
                                     '{"steps": [...]} (an empty list if nothing on the page can do it).',
                             max_tokens=3000, timeout=180, model=self.model)
            got = llm.json_from(reply)
        except Exception as e:
            self.log(f"  could not work out a replacement for {a.get('text') or a.get('into')!r} ({type(e).__name__})")
            return False
        from .plan import _action
        labels = {x.lower() for x in now.get("buttons") or []}
        for r in now.get("rows") or []:
            labels |= {b.lower() for b in r.get("buttons") or []}
        boxed = [r["row"].lower() for r in now.get("rows") or [] if r.get("checkbox")]

        def real(s):     # only steps on things the page really has, and a row's button only with its row
            t = str(s.get("text") or "").lower()
            if s["do"] in ("click", "hover"):
                in_rows = sum(1 for r in now.get("rows") or [] if t in [b.lower() for b in r.get("buttons") or []])
                return any(t == x or t in x for x in labels) and (in_rows < 2 or bool(s.get("in")))
            if s["do"] in ("check", "uncheck"):
                return any(t in r or r in t for r in boxed)
            return True
        steps = [s for s in (_action(x) for x in ((got or {}).get("steps") or [])[:4]) if s and real(s)]
        if not steps:
            self.log(f"  nothing on the page can do {a.get('do')} {a.get('text') or a.get('into')!r}")
            return False
        self.log(f"  {a.get('do')} {a.get('text') or a.get('into')!r} is not on the page; doing instead: "
                 + "; ".join(f"{s['do']} {s.get('text') or s.get('into') or s.get('to') or ''}".strip() for s in steps))
        before = self.page.url
        for i, s in enumerate(steps):
            try:
                self._do(s)
                if s["do"] == "click" and self.changes:
                    self._confirm(str(s.get("text") or ""), steps[i + 1] if i + 1 < len(steps) else None)
            except _Missing as m:
                self._miss(m.msg)
                return True
        if self.page.url != before and depth < 2:
            # the replacement only got to the right page: now the step itself, there
            try:
                modal = bool(self.page.evaluate("() => !!window.__sv.modal()"))
                self._do(a)
                if a["do"] == "click" and not modal and self.page.evaluate("() => !!window.__sv.modal()"):
                    self._confirm(str(a.get("text") or ""), (later or [None])[0])
            except _Missing as m:
                if not self._repair(a, scene, later, depth=depth + 1):
                    self._miss(m.msg)
        return True

    def _run(self, actions: List[Dict], scene: Optional[Dict] = None) -> None:
        for n, a in enumerate(actions):
            self.page.wait_for_timeout(250)
            try:
                modal = self.changes and bool(self.page.evaluate("() => !!window.__sv.modal()"))
                self._do(a)
                if a["do"] == "click" and self.changes and not modal and self.page.evaluate("() => !!window.__sv.modal()"):
                    self._confirm(str(a.get("text") or ""), actions[n + 1] if n + 1 < len(actions) else None)
            except _Missing as m:
                if not (self.changes and (self._onward(a) or self._repair(a, scene, actions[n + 1:]))):
                    self._miss(m.msg)
            except Exception as e:
                self._miss(f"  action {a} failed: {type(e).__name__}")

    # ── a scene ──
    def scene(self, scene: Dict, seconds: float, out: str) -> float:
        """Record one scene as a clip of exactly `seconds` plus handles; returns the speed it was fitted with."""
        if scene.get("continue") and self.url:
            # carries on where the last scene ended; if that left a "done: View ..." dialog open, go to what was made
            if self.changes and self.page.evaluate("() => !!window.__sv.modal() && !!window.__sv.onward()"):
                el = self.page.evaluate_handle("() => window.__sv.onward()").as_element()
                label = (el.inner_text() or "").strip()
                if label and not DANGER.search(label):
                    self.log(f"  following {label!r} from the last scene")
                    el.click()
                    try:
                        self.page.wait_for_load_state("load", timeout=8000)
                    except Exception:
                        pass
                    self.page.wait_for_timeout(800)
                    self.url = self.page.url
                    self.page.evaluate("() => window.__sv && window.__sv.ensure()")
        elif scene["url"].rstrip("/") != (self.url or "").rstrip("/"):
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
        if self.cursor == "auto":
            # a cursor only where the scene points at, clicks or types into something
            show = any(str(a.get("do")) in POINTING for a in scene.get("actions") or [])
            self.page.evaluate("on => window.__sv.cursor(on)", show)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": WIDTH, "maxHeight": HEIGHT})
        # nudge the cursor so the screencast sends a first frame even on a page that is already still
        self.page.mouse.move(self.mouse[0] + 1, self.mouse[1])
        t0 = time.time()
        try:
            self.page.wait_for_timeout(500)
            self._run(scene.get("actions") or [], scene)
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
