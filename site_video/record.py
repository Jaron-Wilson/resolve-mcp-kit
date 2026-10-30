"""Play each scene on the real site and record it at 1920x1080, 30 fps, to the exact length the edit needs.

Frames come from Chrome's screencast (smooth, full quality), not Playwright's built-in video (low bitrate). A drawn
cursor and a lower-third caption are added to the page, since a headless browser shows neither.
"""

import base64
import html
import json
import os
import shutil
import time
from typing import Dict, List

from .crawl import open_page
from .util import FPS, HEIGHT, SCALE, VIEW_H, VIEW_W, WIDTH, ffmpeg, frames

# added to every page: a cursor that follows the mouse, a caption, and an eased scroll
OVERLAY = r"""(() => {
  if (window.__sv) return;
  const css = `#__sv_cur{position:fixed;left:0;top:0;width:20px;height:20px;z-index:2147483647;pointer-events:none;
      transform:translate(-100px,-100px);transition:transform 0s;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
    #__sv_cur.down svg{transform:scale(.85)}
    #__sv_cur .halo{position:absolute;left:-15px;top:-15px;width:40px;height:40px;border-radius:50%;
      background:rgba(255,214,64,.30);box-shadow:0 0 0 2px rgba(255,214,64,.55)}
    .__sv_rip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;z-index:2147483646;
      pointer-events:none;border:3px solid rgba(255,214,64,.95);animation:__sv_rip .6s ease-out forwards}
    @keyframes __sv_rip{to{transform:scale(4);opacity:0}}
    #__sv_cap{position:fixed;left:42px;bottom:46px;z-index:2147483646;pointer-events:none;max-width:70vw;
      font:600 26px/1.2 system-ui,"Segoe UI",Inter,Helvetica,Arial,sans-serif;color:#fff;letter-spacing:-.01em;
      background:rgba(14,16,22,.82);backdrop-filter:blur(8px);border-left:4px solid #4f9dff;border-radius:7px;
      padding:11px 18px;opacity:0;transform:translateY(12px);transition:opacity .45s ease,transform .45s ease}
    #__sv_cap.on{opacity:1;transform:none}`;
  const add = () => {
    if (document.getElementById('__sv_cur')) return;
    const st = document.createElement('style'); st.textContent = css; document.documentElement.appendChild(st);
    const cur = document.createElement('div'); cur.id = '__sv_cur';
    const look = window.__svCursorStyle || 'arrow';
    const arrow = '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M4 2l15 11-6.5 1.2L16 21l-3 1.4-3.6-6.9L4 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const hand = '<svg viewBox="0 0 24 24" width="22" height="22" style="margin:-1px 0 0 -5px"><path d="M9 11V4.5a1.5 1.5 0 0 1 3 0V10h.5V8.5a1.5 1.5 0 0 1 3 0V10h.5V9.5a1.5 1.5 0 0 1 3 0V15c0 3.5-2.3 6-5.7 6H12c-2 0-3.3-.8-4.5-2.4L4.6 14.5a1.5 1.5 0 0 1 2.3-1.9L9 14.6z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    cur.innerHTML = (look === 'ring' ? '<div class="halo"></div>' : '') + (look === 'hand' ? hand : arrow);
    if (look === 'none') cur.style.display = 'none';
    document.documentElement.appendChild(cur);
    const cap = document.createElement('div'); cap.id = '__sv_cap'; document.documentElement.appendChild(cap);
    document.addEventListener('mousemove', e => { cur.style.transform = `translate(${e.clientX - 4}px,${e.clientY - 2}px)`; }, true);
    document.addEventListener('mousedown', e => { cur.classList.add('down');
      if (look !== 'ring') return;
      const r = document.createElement('div'); r.className = '__sv_rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
    document.addEventListener('mouseup', () => cur.classList.remove('down'), true);
  };
  window.__sv = {
    ensure: add,
    caption(t) { add(); const c = document.getElementById('__sv_cap'); if (!t) { c.classList.remove('on'); return; }
      c.textContent = t; requestAnimationFrame(() => c.classList.add('on')); },
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
    scrollTop() { return (window.__svScroller || this.main()).scrollTop; },
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

SECONDS_FOR = {"scroll": 2.2, "hover": 1.6, "click": 2.4}
CURSORS = ("arrow", "hand", "ring", "none")     # ring: the arrow with a highlight around it and a ripple on clicks
LEAD, TAIL = 0.5, 0.6          # quiet time at the start and end of each scene
VERSION = 2      # bump when a recording would come out differently, so saved website clips are made again


class Recorder:
    """One browser for a job; scenes on the same URL continue where the last one left off."""

    def __init__(self, work: str, log=print, cursor: str = "arrow"):
        from playwright.sync_api import sync_playwright
        self.work, self.log = work, log
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.ctx = self.browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE)
        self.ctx.add_init_script(f"window.__svCursorStyle = {json.dumps(cursor if cursor in CURSORS else 'arrow')};")
        self.ctx.add_init_script(OVERLAY)
        self.cards = self.browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        self.page = self.ctx.new_page()
        self.cdp = self.ctx.new_cdp_session(self.page)
        self.url = None
        self.mouse = (VIEW_W * 0.62, VIEW_H * 0.55)
        self._frames: List = []
        self._dir = None
        self.cdp.on("Page.screencastFrame", self._on_frame)

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

    def _encode(self, t0: float, seconds: float, out: str) -> None:
        if not self._frames:
            raise RuntimeError("no frames were captured")
        lines = []
        for i, (ts, path) in enumerate(self._frames):
            start = max(ts, t0)
            end = self._frames[i + 1][0] if i + 1 < len(self._frames) else t0 + seconds
            if end <= t0:
                continue
            lines.append(f"file '{path}'\nduration {max(0.001, end - start):.4f}")
        lines.append(f"file '{self._frames[-1][1]}'")
        lst = os.path.join(self._dir, "list.txt")
        with open(lst, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        n = frames(seconds)
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst,
               "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                      f"fps={FPS},tpad=stop_mode=clone:stop_duration=3,format=yuv420p",
               "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
               "-movflags", "+faststart", out)

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

    def _scroll(self, to, seconds: float) -> None:
        y = self.page.evaluate("t => window.__sv.targetY(t)", str(to))
        if y is None:
            self.log(f"  scroll target not found: {to!r}")
            self.page.wait_for_timeout(seconds * 1000)
            return
        self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, int(seconds * 1000)])

    def _point_at(self, text: str, seconds: float, click: bool) -> None:
        loc = self.page.get_by_text(str(text), exact=False)
        try:
            el = next(loc.nth(i) for i in range(min(loc.count(), 8)) if loc.nth(i).is_visible())
        except StopIteration:
            self.log(f"  not on the page: {text!r}")
            self.page.wait_for_timeout(seconds * 1000)
            return
        box = el.bounding_box()
        if box and not (40 < box["y"] < VIEW_H - 80):       # bring it into view first, smoothly
            y = el.evaluate("e => window.__sv.targetFor(e, 0.4)")    # in whichever panel scrolls it
            self.page.evaluate("([y, ms]) => window.__sv.scrollTo(y, ms)", [y, 900])
            box = el.bounding_box()
            seconds = max(0.6, seconds - 0.9)
        if not box:
            return
        self._glide(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.55, min(1.1, seconds * 0.6))
        self.page.wait_for_timeout(max(0, seconds * 0.4) * 1000)
        if click:
            url = self.page.url
            self.page.mouse.down()
            self.page.mouse.up()
            try:
                self.page.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            if self.page.url != url:
                self.url = self.page.url
                self.page.evaluate("() => window.__sv && window.__sv.ensure()")

    def _run(self, actions: List[Dict], budget: float) -> None:
        """Run the actions spread over `budget` seconds: each gets its usual time, the rest is calm between them."""
        want = [float(a.get("seconds") or 1.5) if a["do"] == "pause" else SECONDS_FOR[a["do"]] for a in actions]
        k = min(1.0, budget / sum(want)) if want and sum(want) > 0 else 1.0
        spare = max(0.0, budget - sum(want) * k)
        gap = spare / (len(actions) + 1) if actions else 0
        for a, w in zip(actions, want):
            self.page.wait_for_timeout(gap * 1000)
            secs = w * k
            try:
                if a["do"] == "scroll":
                    self._scroll(a.get("to", "bottom"), secs)
                elif a["do"] in ("hover", "click"):
                    self._point_at(a.get("text", ""), secs, a["do"] == "click")
                else:
                    self.page.wait_for_timeout(secs * 1000)
            except Exception as e:
                self.log(f"  action {a} failed: {type(e).__name__}")

    # ── a scene ──
    def scene(self, scene: Dict, seconds: float, out: str) -> None:
        if (scene["url"].rstrip("/") != (self.url or "").rstrip("/")):
            open_page(self.page, scene["url"])
            self.url = scene["url"]
            self.page.evaluate("() => window.__sv.ensure()")
            self.page.mouse.move(*self.mouse)
            self.page.wait_for_timeout(700)
        self._dir = os.path.join(self.work, "frames_" + os.path.splitext(os.path.basename(out))[0])
        shutil.rmtree(self._dir, ignore_errors=True)
        os.makedirs(self._dir)
        self._frames = []
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": WIDTH, "maxHeight": HEIGHT})
        t0 = time.time()
        try:
            self.page.wait_for_timeout(LEAD * 1000 * 0.6)
            self.page.evaluate("t => window.__sv.caption(t)", scene.get("caption") or "")
            self._run(scene.get("actions") or [], max(1.0, seconds - LEAD - TAIL - 0.4))
            left = seconds - (time.time() - t0) - 0.55
            if left > 0:
                self.page.wait_for_timeout(left * 1000)
            self.page.evaluate("() => window.__sv.caption('')")
            left = seconds - (time.time() - t0) + 0.15
            if left > 0:
                self.page.wait_for_timeout(left * 1000)
        finally:
            self.cdp.send("Page.stopScreencast")
        self.page.wait_for_timeout(150)      # let the last frames arrive
        self._encode(t0, seconds, out)
        shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None

    def hero(self, url: str, out_png: str) -> None:
        """A screenshot of the top of the site, for the title cards' background."""
        if url.rstrip("/") != (self.url or "").rstrip("/"):
            open_page(self.page, url)
            self.url = url
        self.page.evaluate("() => { window.__sv.caption(''); window.__sv.doc().scrollTop = 0; window.__sv.main().scrollTop = 0; }")
        self.page.mouse.move(-50, -50)
        self.mouse = (VIEW_W * 0.62, VIEW_H * 0.55)
        self.page.wait_for_timeout(500)
        self.page.screenshot(path=out_png)

    def caption_png(self, text: str, out_png: str) -> None:
        """The lower-third caption alone on a transparent 1920x1080 image, the same as on website scenes, for laying
        over the owner's videos."""
        s = WIDTH / VIEW_W
        doc = f"""<!doctype html><html><head><style>
          html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;background:transparent}}
          div{{position:fixed;left:{42 * s:.0f}px;bottom:{46 * s:.0f}px;max-width:70vw;color:#fff;letter-spacing:-.01em;
              font:600 {26 * s:.0f}px/1.2 system-ui,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
              background:rgba(14,16,22,.82);border-left:{4 * s:.0f}px solid #4f9dff;border-radius:{7 * s:.0f}px;
              padding:{11 * s:.0f}px {18 * s:.0f}px}}
        </style></head><body><div>{html.escape(text)}</div></body></html>"""
        pg = self.cards.new_page()
        try:
            pg.set_content(doc)
            pg.wait_for_timeout(150)
            pg.screenshot(path=out_png, omit_background=True)
        finally:
            pg.close()

    def card(self, kind: str, title: str, sub: str, hero_png: str, seconds: float, out: str) -> None:
        """An intro or outro card: the site blurred behind big type, with a slow push-in and fades."""
        with open(hero_png, "rb") as f:
            bg = "data:image/png;base64," + base64.b64encode(f.read()).decode()
        big = 104 if len(title) < 28 else 80 if len(title) < 48 else 62
        doc = f"""<!doctype html><html><head><style>
          html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;background:#0b0d12}}
          .bg{{position:absolute;inset:-40px;background:url({bg}) center/cover;filter:blur(18px) saturate(1.1) brightness(.45)}}
          .shade{{position:absolute;inset:0;background:radial-gradient(ellipse at 30% 40%,rgba(20,30,60,.15),rgba(5,7,12,.85))}}
          .box{{position:absolute;left:140px;right:140px;top:50%;transform:translateY(-50%);color:#fff;
               font-family:system-ui,"Segoe UI",Inter,Helvetica,Arial,sans-serif}}
          .k{{font-size:26px;letter-spacing:.24em;text-transform:uppercase;color:#8fbaff;font-weight:600;margin-bottom:26px}}
          h1{{font-size:{big}px;line-height:1.04;margin:0 0 28px;font-weight:750;letter-spacing:-.02em}}
          p{{font-size:40px;line-height:1.3;margin:0;color:#d6dbe4;max-width:1400px}}
          .bar{{width:120px;height:8px;border-radius:4px;background:#4f9dff;margin-bottom:34px}}
        </style></head><body><div class="bg"></div><div class="shade"></div><div class="box">
          <div class="bar"></div>{'<div class="k">' + html.escape(kind) + '</div>' if kind else ''}
          <h1>{html.escape(title)}</h1><p>{html.escape(sub)}</p></div></body></html>"""
        pg = self.cards.new_page()
        try:
            pg.set_content(doc)
            pg.wait_for_timeout(300)
            png = out[:-4] + ".png"
            pg.screenshot(path=png)
        finally:
            pg.close()
        n = frames(seconds)
        fade_out = max(0.0, seconds - 0.6)
        ffmpeg("-loop", "1", "-i", png,
               "-vf", f"scale={WIDTH * 2}:{HEIGHT * 2},zoompan=z='1+0.05*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"d={n}:s={WIDTH}x{HEIGHT}:fps={FPS},fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=0.6,format=yuv420p",
               "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(FPS),
               "-movflags", "+faststart", out)
