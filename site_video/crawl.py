"""Read a website the way the planner needs it: pages, their headings and the things on them that can be pointed at.

Only same-site pages linked from the start page are visited. Nothing is submitted or clicked here.
"""

from typing import Dict, List
from urllib.parse import urljoin, urlparse

from .util import SCALE, VIEW_H, VIEW_W

# runs in the page: what is on it, in reading order
_EXTRACT = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const H = document.documentElement.scrollHeight;
  const heads = [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(h => ({
    level: +h.tagName[1], text: txt(h).slice(0, 120),
    at: Math.round((h.getBoundingClientRect().top + scrollY) / Math.max(H, 1) * 100) / 100 })).filter(h => h.text);
  const buttons = [...document.querySelectorAll('a,button,[role=button]')].filter(vis).map(txt)
    .filter(t => t && t.length < 40);
  const links = [...document.querySelectorAll('a[href]')].map(a => ({ href: a.href, text: txt(a).slice(0, 60) }));
  const inputs = [...document.querySelectorAll('input[type=search],input[type=text],input:not([type]),textarea')].filter(vis)
    .map(el => (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('name') || '').trim())
    .filter(Boolean);
  const meta = n => (document.querySelector(`meta[name="${n}"],meta[property="${n}"]`) || {}).content || '';
  return { title: document.title, description: meta('description') || meta('og:description'),
    site_name: meta('og:site_name'), height: H, headings: heads.slice(0, 40),
    buttons: [...new Set(buttons)].slice(0, 40), links, inputs: [...new Set(inputs)].slice(0, 8),
    text: txt(document.body).slice(0, 2500) };
}"""

# text of common cookie and consent buttons, clicked once per page so they do not cover the video
CONSENT = ["Accept all", "Accept All", "Accept", "I agree", "Agree", "Got it", "OK", "Okay", "Allow all", "Accept cookies"]

# floating boxes a promo should not show: cookie bars, surveys, newsletter and feedback pop-ups. Fixed or sticky,
# not the site's own header or menu (a full-width bar at the very top), and saying what they are
_HIDE_POPUPS = r"""() => {
  const words = /cookie|consent|survey|newsletter|subscribe|feedback|privacy|we use|help us|shape the future|sign up for/i;
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 20) continue;
    if (r.top < 90 && r.width > innerWidth * 0.8 && el.closest('header,nav,[role=banner],[role=navigation]')) continue;
    if (r.width * r.height > innerWidth * innerHeight * 0.6) continue;     // a page-sized layer is the page itself
    if (!words.test((el.innerText || '').slice(0, 600))) continue;
    el.style.setProperty('display', 'none', 'important'); n++;
  }
  return n;
}"""


def dismiss_consent(page) -> None:
    _consent(page)
    for label in ("No thanks", "Not now", "Dismiss", "Close"):
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(250)
        except Exception:
            pass
    try:
        page.evaluate(_HIDE_POPUPS)
    except Exception:
        pass


def _consent(page) -> None:
    for label in CONSENT:
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def open_page(page, url: str) -> None:
    try:
        page.goto(url, wait_until="networkidle", timeout=25000)
    except Exception:
        page.goto(url, wait_until="load", timeout=45000)
    dismiss_consent(page)
    from .explore import settle
    settle(page)


def _same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    return ha.removeprefix("www.") == hb.removeprefix("www.")


def crawl(start: str, max_pages: int = 6, log=print, brand_dir: str = "") -> Dict:
    """{"start", "brand", "pages": [{url, title, description, headings, buttons, inputs, text, height}]}. The brand
    (colors, font, logo) is read from the start page; its logo goes to <brand_dir>/logo.png."""
    import os
    from . import brand as branding
    found = None
    from playwright.sync_api import sync_playwright
    pages: List[Dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE)
        page = ctx.new_page()
        queue, seen = [start], set()
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            key = url.split("#")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            try:
                open_page(page, url)
                info = page.evaluate(_EXTRACT)
            except Exception as e:
                log(f"skipped {url}: {type(e).__name__}")
                continue
            info["url"] = page.url
            links = info.pop("links")
            pages.append(info)
            log(f"read {page.url} ({len(info['headings'])} headings)")
            if len(pages) == 1:
                found = branding.extract(page, os.path.join(brand_dir, "logo.png") if brand_dir else "", log)
                # follow the start page's own links: its nav is the site's outline
                for ln in links:
                    href = urljoin(page.url, ln["href"]).split("#")[0]
                    if href.startswith("http") and _same_site(href, start) and not href.lower().endswith(
                            (".pdf", ".zip", ".jpg", ".png", ".mp4")) and "logout" not in href.lower():
                        queue.append(href)
        browser.close()
    if not pages:
        raise RuntimeError(f"could not open {start}")
    return {"start": start, "pages": pages, "brand": found}


def pages_for(seconds) -> int:
    """How many pages to read: more for a longer video."""
    if not seconds:
        return 5
    return max(2, min(12, int(seconds // 40) + 2))
