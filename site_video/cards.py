"""Title, problem and closing cards and the caption pills, drawn in the site's own colors and font.

They are drawn by a browser tab opened on the site itself (so its web fonts load), inside a shadow root (so the site's
styles cannot reach them), and saved as 1920x1080 PNGs: cards opaque, captions transparent for the captions track.
"""

import base64
import html
import os
from typing import Dict, Optional

from .util import HEIGHT, WIDTH

CHECK = ('<svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 12.5l4.2 4.2L19 7" fill="none" stroke="#fff" '
         'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _rgb(hexcolor: str):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (20, 22, 26)


def _mix(a: str, b: str, k: float) -> str:
    """a moved k of the way to b."""
    x, y = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(p + (q - p) * k):02x}" for p, q in zip(x, y))


def _rgba(hexcolor: str, alpha: float) -> str:
    r, g, b = _rgb(hexcolor)
    return f"rgba({r},{g},{b},{alpha})"


class Painter:
    """One browser tab for a job's cards and captions."""

    def __init__(self, browser, site_url: str, brand: Dict, brand_dir: str = "", log=print):
        self.brand, self.log = brand, log
        ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        self.page = ctx.new_page()
        try:
            if site_url:
                self.page.goto(site_url, wait_until="load", timeout=30000)
        except Exception as e:
            log(f"  cards: the site did not open ({type(e).__name__}); drawing with system fonts")
        self.page.evaluate("""() => { document.documentElement.style.cssText = 'background:transparent!important';
            document.body.innerHTML = ''; document.body.style.cssText = 'margin:0;background:transparent!important';
            const host = document.createElement('div'); host.id = '__sv_host';
            host.style.cssText = 'position:fixed;left:0;top:0;width:1920px;height:1080px;z-index:2147483647';
            document.body.appendChild(host); host.attachShadow({mode: 'open'}); }""")
        self.logo = None
        lp = os.path.join(brand_dir, brand["logo"]) if brand.get("logo") and brand_dir else ""
        if lp and os.path.exists(lp):
            with open(lp, "rb") as f:
                self.logo = "data:image/png;base64," + base64.b64encode(f.read()).decode()

    def _shot(self, body: str, css: str, out_png: str, transparent: bool) -> str:
        self.page.evaluate("([b, c]) => { document.getElementById('__sv_host').shadowRoot.innerHTML = '<style>' + c + '</style>' + b; }",
                           [body, css])
        self.page.evaluate("() => document.fonts.ready")
        self.page.wait_for_timeout(120)
        self.page.screenshot(path=out_png, omit_background=transparent, clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        return out_png

    # ── look ──
    def _font(self) -> str:
        return self.brand.get("font") or "system-ui, sans-serif"

    def _soft(self) -> str:
        b = self.brand
        base = b["bg"] if b.get("dark") else _mix(b["bg"], "#ffffff", 0.5)
        return (f"background:radial-gradient(1100px 700px at 18% 12%, {_rgba(b['primary'], .16)}, transparent 70%),"
                f"radial-gradient(1000px 650px at 85% 90%, {_rgba(b['primary'], .12)}, transparent 70%), {base};")

    def _ink(self) -> str:
        return "#ffffff" if self.brand.get("dark") else self.brand["ink"]

    def _mark(self, size: int) -> str:
        if self.logo:
            return f'<img class="logo" src="{self.logo}" style="max-height:{size}px;max-width:760px">'
        name = html.escape(self.brand.get("name") or "")
        return f'<div class="word" style="font-size:{size}px">{name}</div>' if name else ""

    def _base_css(self) -> str:
        return (f":host{{all:initial}} .card{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;"
                f"justify-content:center;text-align:center;font-family:{self._font()};-webkit-font-smoothing:antialiased;"
                f"padding:0 180px;box-sizing:border-box}} .logo{{display:block;object-fit:contain;margin-bottom:56px}}"
                f".word{{font-weight:800;letter-spacing:-.02em;margin-bottom:48px}} p{{margin:0}}")

    # ── cards ──
    def title(self, headline: str, subline: str, out_png: str) -> str:
        ink = self._ink()
        body = (f'<div class="card" style="{self._soft()}color:{ink}">{self._mark(120)}'
                f'<p class="h">{html.escape(headline)}</p><p class="s">{html.escape(subline)}</p></div>')
        css = self._base_css() + (f".h{{font-size:{70 if len(headline) < 50 else 58}px;font-weight:750;line-height:1.12;"
                                  f"letter-spacing:-.015em;max-width:1500px}} .s{{font-size:36px;line-height:1.35;"
                                  f"margin-top:30px;opacity:.72;max-width:1300px}} .word{{color:{ink}}}")
        return self._shot(body, css, out_png, False)

    def problem(self, statement: str, solution: str, out_png: str) -> str:
        b = self.brand
        dark = _mix(b["bg"], "#000000", 0.35) if b.get("dark") else _mix(b["ink"], b["primary"], 0.18)
        label = _mix(b["primary"], "#ffffff", 0.35)
        body = (f'<div class="card" style="background:radial-gradient(1200px 800px at 50% 30%, {_rgba(b["primary"], .22)}, '
                f'transparent 70%), {dark};color:#fff"><p class="k">The problem</p><p class="h">{html.escape(statement)}</p>'
                + (f'<p class="s">{html.escape(solution)}</p>' if solution else "") + "</div>")
        css = self._base_css() + (f".k{{font-size:26px;font-weight:700;letter-spacing:.24em;text-transform:uppercase;"
                                  f"color:{label};margin-bottom:34px}} .h{{font-size:{62 if len(statement) < 90 else 50}px;"
                                  f"font-weight:750;line-height:1.16;max-width:1500px}} .s{{font-size:36px;line-height:1.4;"
                                  f"margin-top:40px;color:{label};max-width:1300px}}")
        return self._shot(body, css, out_png, False)

    def close(self, line: str, url: str, small: str, out_png: str) -> str:
        b, ink = self.brand, self._ink()
        shown = url.replace("https://", "").replace("http://", "").rstrip("/")
        body = (f'<div class="card" style="{self._soft()}color:{ink}">{self._mark(110)}<p class="h">{html.escape(line)}</p>'
                f'<div class="btn">{html.escape(shown)}</div>'
                + (f'<p class="s">{html.escape(small)}</p>' if small else "") + "</div>")
        css = self._base_css() + (f".h{{font-size:{54 if len(line) < 60 else 44}px;font-weight:700;line-height:1.2;"
                                  f"max-width:1400px}} .btn{{margin-top:48px;background:{b['primary']};color:#fff;font-size:48px;"
                                  f"font-weight:800;padding:26px 64px;border-radius:22px;box-shadow:0 18px 50px "
                                  f"{_rgba(b['primary'], .35)}}} .s{{font-size:30px;margin-top:40px;opacity:.7}} .word{{color:{ink}}}")
        return self._shot(body, css, out_png, False)

    # ── captions ──
    def caption(self, text: str, out_png: str, top: bool = False) -> str:
        b = self.brand
        fill = _mix(b["bg"], "#000000", 0.25) if b.get("dark") else _mix(b["ink"], "#000000", 0.2)
        where = "top:44px" if top else "bottom:40px"
        body = (f'<div class="wrap" style="{where}"><div class="pill"><span class="dot">{CHECK}</span>'
                f'<span class="t">{html.escape(text)}</span></div></div>')
        css = (f":host{{all:initial}} .wrap{{position:absolute;left:0;right:0;display:flex;justify-content:center}}"
               f".pill{{display:flex;align-items:center;gap:20px;max-width:1640px;box-sizing:border-box;padding:20px 40px 20px 22px;"
               f"background:{_rgba(fill, .95)};color:#fff;border-radius:44px;box-shadow:0 10px 34px rgba(0,0,0,.38);"
               f"font-family:{self._font()};font-size:40px;font-weight:600;line-height:1.25;-webkit-font-smoothing:antialiased}}"
               f".dot{{flex:none;width:44px;height:44px;border-radius:50%;background:{b['primary']};display:flex;"
               f"align-items:center;justify-content:center}} .t{{text-wrap:balance}}")
        return self._shot(body, css, out_png, True)


def card_clip(pngs, seconds: float, out: str, first: float = 0.0) -> None:
    """Cards as one clip of exactly `seconds` plus HANDLE frames each side, with a slow push-in. Two cards (title,
    then problem) change at `first` seconds with a dissolve inside the clip."""
    from .util import DISSOLVE, FPS, HANDLE, ffmpeg, frames
    n = frames(seconds) + 2 * HANDLE
    zoom = f"scale={WIDTH * 2}:{HEIGHT * 2},zoompan=z='1+0.035*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    if len(pngs) == 1 or not first:
        ffmpeg("-loop", "1", "-i", pngs[0], "-vf", zoom + ",format=yuv420p", "-frames:v", str(n), "-c:v", "libx264",
               "-preset", "medium", "-crf", "16", "-r", str(FPS), "-movflags", "+faststart", out)
        return
    cut = HANDLE + frames(first)
    d = DISSOLVE / FPS
    graph = (f"[0:v]{zoom},trim=end_frame={cut + DISSOLVE // 2},setpts=PTS-STARTPTS,fps={FPS}[a];"
             f"[1:v]{zoom},trim=end_frame={n - cut + DISSOLVE // 2},setpts=PTS-STARTPTS,fps={FPS}[b];"
             f"[a][b]xfade=transition=fade:duration={d:.4f}:offset={(cut - DISSOLVE // 2) / FPS:.4f},format=yuv420p[v]")
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", pngs[0], "-loop", "1", "-framerate", str(FPS), "-i", pngs[1], "-filter_complex", graph, "-map", "[v]",
           "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
           "-movflags", "+faststart", out)


def painter(browser, req_url: str, brand: Optional[Dict], brand_dir: str, log=print) -> Painter:
    from .brand import DEFAULT
    return Painter(browser, req_url, dict(DEFAULT, **(brand or {})), brand_dir, log)
