"""Explore a website before the script is written: walk the whole site, try its search, and look at what it shows.

1. Map: every same-site page reachable by links (not only the start page's), up to SITE_VIDEO_EXPLORE_PAGES (60)
   within SITE_VIDEO_EXPLORE_SECONDS (240). Sign-in, cart and legal pages are left out, and look-alike detail pages
   (more than 4 under one parent, like /cards/<id>) are sampled rather than all read. Each page is given time to finish
   filling in, and scored for how much real content it shows.
2. Probe: each kind of search or text field is tried with a real example taken from the site itself (the name of one
   of its own items), and the page that answers is read and scored too. Nothing is submitted but a GET search: the
   browser blocks every other request, as the recorder does.
3. Look: with SITE_VIDEO_VISION_MODEL set, the best views are screenshotted and described in a sentence.

The result has the shape crawl.crawl returns (pages, best first; brand), plus "probes", so everything downstream reads
it unchanged; plan.py shows the script model a map of every page and full detail of the best ones.
"""

import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .crawl import _EXTRACT, _same_site, dismiss_consent
from .util import SCALE, VIEW_H, VIEW_W

MAX_PAGES = int(os.environ.get("SITE_VIDEO_EXPLORE_PAGES", "60"))
BUDGET_S = float(os.environ.get("SITE_VIDEO_EXPLORE_SECONDS", "240"))
PER_PARENT = 4          # look-alike pages read under one parent path
LOOK_AT = 12            # views described by the vision model

SKIP = re.compile(r"(log-?in|log-?out|sign-?in|sign-?up|sign-?out|register|account|profile|settings|cart|checkout|"
                  r"basket|password|privacy|terms|legal|cookie|gdpr|imprint|impressum|unsubscribe|wp-admin|/feed|"
                  r"\.(pdf|zip|jpe?g|png|gif|svg|webp|mp4|mov|xml|json|txt|css|js)$)", re.I)

# how full a view is: what a promo would want to show
_RICHNESS = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 24 && r.height > 24 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const n = sel => [...document.querySelectorAll(sel)].filter(vis).length;
  return { images: n('img,picture,canvas,video,svg[width]'), rows: n('tr'), items: n('li,article,[class*=card i]'),
           words: (document.body.innerText || '').split(/\s+/).length };
}"""


def _score(r: Dict, headings: int) -> float:
    """A rough 0 to 10 for how much a page shows: pictures, rows and items count most, then text."""
    return round(min(10.0, 1.6 * math.log1p(r.get("images", 0)) + 1.2 * math.log1p(r.get("rows", 0))
                     + 1.0 * math.log1p(r.get("items", 0)) + 0.6 * math.log1p(r.get("words", 0) / 50)
                     + 0.4 * math.log1p(headings)), 2)


def settle(page, max_s: float = 3.5) -> None:
    """Wait until the page stops filling in (sites that load their content after the page itself)."""
    last, still, end = -1, 0, time.time() + max_s
    while time.time() < end:
        try:
            n = page.evaluate("() => (document.body && document.body.innerText || '').length")
        except Exception:
            return
        still = still + 1 if n == last and n > 200 else 0
        if still >= 2:
            return
        last = n
        page.wait_for_timeout(400)


def _open(page, url: str) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass
    except Exception:
        page.goto(url, wait_until="load", timeout=45000)
    dismiss_consent(page)
    settle(page)


def _norm(url: str) -> str:
    u = urlparse(url.split("#")[0])
    path = re.sub(r"/+$", "", u.path) or "/"
    # ?tracking=1 and ?show=x variants are the same page; a search's query is what makes its page
    keep = u.query and re.search(r"search|find|query|results", path, re.I)
    return f"{u.scheme}://{u.netloc.lower().removeprefix('www.')}{path}" + (f"?{u.query}" if keep else "")


def _parent(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[0] if path.count("/") > 1 else "/"


def _read(page, shots: str, n: int) -> Dict:
    info = page.evaluate(_EXTRACT)
    info["richness"] = page.evaluate(_RICHNESS)
    info["score"] = _score(info["richness"], len(info.get("headings") or []))
    info["url"] = page.url
    if shots:
        path = os.path.join(shots, f"{n:03d}.jpg")
        try:
            page.screenshot(path=path, type="jpeg", quality=70)
            info["shot"] = os.path.basename(path)
        except Exception:
            pass
    return info


def _from_links(p: Dict, start: Dict) -> List[str]:
    """Short link texts that are this page's own (not the site's menu): a subjects page's subjects, say."""
    common = {b.lower() for b in start.get("buttons") or []}
    return [b for b in p.get("buttons") or [] if 3 <= len(b) <= 30 and b.lower() not in common
            and len(b.split()) <= 4 and not re.search(r"\d{3,}|more|next|prev|sign|log|menu|close", b, re.I)][:6]


def _examples(pages: List[Dict]) -> List[str]:
    """Real things to search for: the titles of the site's own detail pages (an item, a card, a product)."""
    by_parent: Dict[str, List[str]] = {}
    for p in pages:
        h1 = next((h["text"] for h in p.get("headings") or [] if h.get("level") == 1), "")
        if h1 and 2 < len(h1) < 50 and _parent(p["url"]) != "/":
            by_parent.setdefault(_parent(p["url"]), []).append(h1)
    best = sorted(by_parent.values(), key=len, reverse=True)
    out = [t for group in best for t in group]
    # a search box wants the name, not "Charizard ex - 199/165 (Scarlet & Violet)"
    return [re.split(r"\s+[-|–(:]\s*|\s*\(", t)[0].strip() for t in out][:6]


def _probe(page, p: Dict, field: str, query: str, shots: str, n: int, log) -> Optional[Dict]:
    """Type `query` into `field` on page p and read what answers."""
    try:
        _open(page, p["url"])
        box = None
        for loc in (page.get_by_placeholder(field), page.get_by_label(field), page.locator(f'[name="{field}"]')):
            try:
                if loc.count() and loc.first.is_visible():
                    box = loc.first
                    break
            except Exception:
                pass
        if box is None:
            return None
        box.click(timeout=3000)
        box.press_sequentially(query, delay=40)
        page.wait_for_timeout(900)          # live search shows results as you type
        typed = page.evaluate("() => document.body.innerText.length")
        box.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            pass
        settle(page)
        after = _read(page, shots, n)
        before = p.get("score", 0)
        log(f"  tried \"{query}\" in \"{field}\" on {p['url']}: {page.url} scores {after['score']} (page {before})")
        return {"page": p["url"], "field": field, "query": query, "url": page.url, "score": after["score"],
                "headings": [h["text"] for h in after.get("headings") or []][:12], "text": (after.get("text") or "")[:600],
                "shot": after.get("shot"), "live": typed > 0}
    except Exception as e:
        log(f"  could not try the field \"{field}\" on {p['url']}: {type(e).__name__}")
        return None


def _look(shots: str, items: List[Dict], log) -> None:
    """Describe the screenshots of the best views (in place, as "looks")."""
    from .media import _describe
    if not os.environ.get("SITE_VIDEO_VISION_MODEL"):
        return
    ask = ("This is a screenshot of a web page. In one sentence for a video editor: what does it show, and is it full of "
           "real content (results, products, data) or mostly empty or text?")

    def one(it):
        try:
            it["looks"] = _describe(os.path.join(shots, it["shot"]), "", ask)
        except Exception as e:
            log(f"  could not describe {it.get('url')}: {type(e).__name__}")
    todo = [it for it in items if it.get("shot")]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    log(f"looked at {len(todo)} views")


ACCOUNT = re.compile(r"(account|profile|settings|my-|dashboard)", re.I)      # read only when signed in


def explore(start: str, log=print, brand_dir: str = "", max_pages: int = MAX_PAGES, budget_s: float = BUDGET_S,
            seeds=(), session: str = None) -> Dict:
    """Map the site from `start`; `seeds` (pages the person named) are always read. With a saved sign-in (`session`),
    the pages behind it are explored too, but nothing is ever submitted here."""
    from playwright.sync_api import sync_playwright
    from . import brand as branding
    from .record import _guard
    shots = os.path.join(brand_dir, "explore") if brand_dir else ""
    if shots:
        os.makedirs(shots, exist_ok=True)
    t0 = time.time()
    pages: List[Dict] = []
    probes: List[Dict] = []
    found = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE,
                                  storage_state=session)
        ctx.route("**/*", _guard)
        page = ctx.new_page()
        named = {_norm(u) for u in seeds}
        queue, seen, per_parent = [start] + [u for u in seeds if _norm(u) != _norm(start)], set(), {}
        while queue and len(pages) < max_pages and time.time() - t0 < budget_s:
            url = queue.pop(0)
            key = _norm(url)
            if key in seen:
                continue
            seen.add(key)
            if pages:
                time.sleep(0.4)         # a polite pace: a few pages a second at most
            par = _parent(url)
            if par != "/" and per_parent.get(par, 0) >= PER_PARENT and key not in named:
                continue
            try:
                _open(page, url)
                if pages and not _same_site(page.url, start):
                    continue
                try:
                    info = _read(page, shots, len(pages))
                except Exception:
                    # the page navigated while being read (a redirect or a reload): let it land, then read again
                    try:
                        page.wait_for_load_state("load", timeout=8000)
                    except Exception:
                        pass
                    settle(page)
                    info = _read(page, shots, len(pages))
            except Exception as e:
                log(f"skipped {url}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
                continue
            if _norm(page.url) != key and _norm(page.url) in seen:
                continue                   # a redirect to a page already read
            seen.add(_norm(page.url))
            per_parent[par] = per_parent.get(par, 0) + 1
            links = info.pop("links")
            pages.append(info)
            log(f"read {page.url} ({len(info['headings'])} headings, score {info['score']})")
            if len(pages) == 1:
                found = branding.extract(page, os.path.join(brand_dir, "logo.png") if brand_dir else "", log)
                _open(page, page.url)       # the brand reader marks the logo; read the page fresh for links
            for ln in links:
                href = urljoin(page.url, ln["href"]).split("#")[0]
                path = urlparse(href).path
                skip = SKIP.search(path) and not (session and ACCOUNT.search(path) and not re.search(r"log-?out|sign-?out", path, re.I))
                if href.startswith("http") and _same_site(href, start) and not skip and _norm(href) not in seen:
                    queue.append(href)
        log(f"mapped {len(pages)} pages in {time.time() - t0:.0f} s" + (f"; {len(queue)} more links not read" if queue else ""))
        # the search and text fields, one try per kind of field
        tried, examples = set(), _examples(pages)
        for p in sorted(pages, key=lambda p: -p["score"]):
            for field in p.get("inputs") or []:
                ideas = examples or _from_links(p, pages[0])
                if field.lower() in tried or not ideas or len(probes) >= 3 or time.time() - t0 > budget_s + 60:
                    continue
                tried.add(field.lower())
                got = _probe(page, p, field, ideas[len(probes) % len(ideas)], shots, len(pages) + len(probes), log)
                if got:
                    probes.append(got)
        browser.close()
    if not pages:
        raise RuntimeError(f"could not open {start}")
    first, rest = pages[0], sorted(pages[1:], key=lambda p: -p["score"])
    pages = [first] + rest
    if shots:
        _look(shots, pages[:LOOK_AT] + probes, log)
    return {"start": start, "pages": pages, "brand": found, "probes": probes}
