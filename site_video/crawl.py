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
  const meta = n => (document.querySelector(`meta[name="${n}"],meta[property="${n}"]`) || {}).content || '';
  return { title: document.title, description: meta('description') || meta('og:description'),
    site_name: meta('og:site_name'), height: H, headings: heads.slice(0, 40),
    buttons: [...new Set(buttons)].slice(0, 40), links,
    text: txt(document.body).slice(0, 2500) };
}"""

# text of common cookie and consent buttons, clicked once per page so they do not cover the video
CONSENT = ["Accept all", "Accept All", "Accept", "I agree", "Agree", "Got it", "OK", "Allow all", "Accept cookies"]


def dismiss_consent(page) -> None:
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


def _same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    return ha.removeprefix("www.") == hb.removeprefix("www.")


def crawl(start: str, max_pages: int = 6, log=print) -> Dict:
    """{"start", "pages": [{url, title, description, headings, buttons, text, height}]}."""
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
            if len(pages) == 1:      # follow the start page's own links: its nav is the site's outline
                for ln in links:
                    href = urljoin(page.url, ln["href"]).split("#")[0]
                    if href.startswith("http") and _same_site(href, start) and not href.lower().endswith(
                            (".pdf", ".zip", ".jpg", ".png", ".mp4")) and "logout" not in href.lower():
                        queue.append(href)
        browser.close()
    if not pages:
        raise RuntimeError(f"could not open {start}")
    return {"start": start, "pages": pages}


def pages_for(seconds) -> int:
    """How many pages to read: more for a longer video."""
    if not seconds:
        return 5
    return max(2, min(12, int(seconds // 40) + 2))
