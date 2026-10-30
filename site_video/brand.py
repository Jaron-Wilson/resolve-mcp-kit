"""The site's look, so the cards, captions and cursor match it: background and text colors, the brand color (from its
main buttons, links or CSS custom properties), the heading font, whether it is a dark site, and its logo as a PNG.

extract(page, logo_png) runs on an open page; DEFAULT is used when a site gives nothing usable.
"""

import os
from typing import Dict

DEFAULT = {"bg": "#f6f7fb", "ink": "#14161a", "primary": "#2f6fed", "font": "Inter, 'Segoe UI', system-ui, sans-serif",
           "dark": False, "logo": None, "name": "", "zoom": 1.0}

_READ = r"""() => {
  const rgb = s => { const m = (s || '').match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/);
    return m && (m[4] === undefined || +m[4] > 0.5) ? [+m[1], +m[2], +m[3]] : null; };
  const hex = c => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const lum = c => (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
  const sat = c => { const mx = Math.max(...c), mn = Math.min(...c); return mx ? (mx - mn) / mx : 0; };
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.3; };
  // background: the first opaque one from the content area outward
  let bg = null;
  for (const el of [document.querySelector('main'), document.body, document.documentElement])
    if (el && !bg) bg = rgb(getComputedStyle(el).backgroundColor);
  bg = bg || [255, 255, 255];
  const ink = rgb(getComputedStyle(document.querySelector('h1,h2,p') || document.body).color) || [20, 22, 26];
  // brand color: the most used saturated fill among buttons and links, then link text, then CSS variables
  const votes = {};
  const vote = (c, w) => { if (c && sat(c) > 0.35 && lum(c) > 0.12 && lum(c) < 0.9) { const k = hex(c); votes[k] = (votes[k] || 0) + w; } };
  for (const el of document.querySelectorAll('button,a,[role=button],input[type=submit]')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    vote(rgb(s.backgroundColor), 3 + Math.min(3, r.width * r.height / 20000));
    vote(rgb(s.color), 1);
    vote(rgb(s.borderTopColor), 0.5);
  }
  const root = getComputedStyle(document.documentElement);
  for (const sheet of [...document.styleSheets]) { let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of rules || []) if (rule.style && rule.selectorText === ':root')
      for (const p of rule.style) if (/primary|brand|accent/i.test(p)) { const el = document.createElement('i');
        el.style.color = root.getPropertyValue(p).trim(); document.body.appendChild(el); vote(rgb(getComputedStyle(el).color), 4); el.remove(); } }
  const best = Object.entries(votes).sort((a, b) => b[1] - a[1])[0];
  const h = document.querySelector('h1') || document.querySelector('h2') || document.body;
  // logo: an image or svg near the top that says it is the logo or links home; small icons (menus, chevrons) are not
  const named = el => /logo|brand/i.test([el.getAttribute('alt'), el.getAttribute('class'), el.id,
    el.parentElement && el.parentElement.getAttribute('class')].join(' '));
  const home = el => { const a = el.closest('a'); if (!a) return false;
    try { const u = new URL(a.href, location.href); return u.host === location.host && (u.pathname === '/' || u.pathname === ''); } catch (e) { return false; } };
  const cands = [...document.querySelectorAll('header img, header svg, nav img, nav svg, a img, a svg, img[alt*="logo" i], [class*="logo" i] img, [class*="logo" i] svg, svg[class*="logo" i]')]
    .filter(vis).filter(el => { const r = el.getBoundingClientRect();
      return r.top < 160 && r.width >= 40 && r.height >= 18 && r.width < 520 && r.height < 160 && (named(el) || home(el)); })
    .map(el => ({ el, score: (named(el) ? 3 : 0) + (home(el) ? 2 : 0) - el.getBoundingClientRect().left / 1000 }))
    .sort((a, b) => b.score - a.score);
  const logo = cands.length ? cands[0].el : null;
  if (logo) logo.setAttribute('data-sv-logo', '1');
  const meta = n => (document.querySelector(`meta[property="${n}"],meta[name="${n}"]`) || {}).content || '';
  // how wide the reading column is: the middle 80% of the left and right edges of the text near the top
  const lefts = [], rights = [];
  for (const el of document.querySelectorAll('p, li, h1, h2, h3, pre, table, img, button, input')) {
    const r = el.getBoundingClientRect();
    if (r.width > 40 && r.height > 8 && r.top < 3000 && vis(el)) { lefts.push(r.left); rights.push(r.right); }
  }
  lefts.sort((a, b) => a - b); rights.sort((a, b) => a - b);
  const q = (xs, k) => xs.length ? xs[Math.min(xs.length - 1, Math.floor(xs.length * k))] : 0;
  const column = lefts.length >= 6 ? q(rights, 0.9) - q(lefts, 0.1) : innerWidth;
  return { bg: hex(bg), ink: hex(ink), primary: best ? best[0] : null, font: getComputedStyle(h).fontFamily, column,
           dark: lum(bg) < 0.4, logo: !!logo, name: meta('og:site_name') || (document.title || '').split(/[|\-–·:]/)[0].trim() };
}"""


def extract(page, logo_png: str = "", log=print) -> Dict:
    try:
        b = page.evaluate(_READ)
    except Exception as e:
        log(f"  brand: could not read the page ({type(e).__name__}); using defaults")
        return dict(DEFAULT)
    out = dict(DEFAULT)
    out.update({k: v for k, v in b.items() if v not in (None, "") and k not in ("logo", "column")})
    # a narrow reading column would be small type in a sea of margin at 1920: lay the site out like a 1280 screen
    # and render it at 1.5x instead, so it fills the frame and reads like the hand-made promos
    out["zoom"] = 1.5 if 0 < float(b.get("column") or 0) < 1150 else 1.0
    out["logo"] = None
    if b.get("logo") and logo_png:
        try:
            el = page.locator("[data-sv-logo]").first
            el.screenshot(path=logo_png, omit_background=True, timeout=5000)
            out["logo"] = os.path.basename(logo_png)
        except Exception as e:
            log(f"  brand: logo not captured ({type(e).__name__})")
    log(f"  brand: {out['primary']} on {out['bg']} ({'dark' if out['dark'] else 'light'}), zoom {out['zoom']}, font {out['font'][:40]}"
        + (", logo" if out["logo"] else ", no logo"))
    return out
