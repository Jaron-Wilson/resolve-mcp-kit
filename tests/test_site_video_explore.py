"""The explorer, sign-in, briefs and the review, without a network, a browser or a vision model."""
import pytest

from site_video import explore, plan, review, session

CRAWL = {"start": "https://ex.com", "pages": [
    {"url": "https://ex.com/", "title": "Ex", "headings": [{"text": "Pricing", "at": 0.5, "level": 2}],
     "buttons": ["Sign up"], "score": 3},
    {"url": "https://ex.com/lot-value", "title": "Lot value", "headings": [], "buttons": ["Evaluate"],
     "inputs": ["Paste your sets"], "score": 5}]}


def test_look_alike_pages_share_a_parent_and_urls_are_compared_without_noise():
    assert explore._parent("https://ex.com/cards/pokemon-1") == "/cards"
    assert explore._parent("https://ex.com/pricing") == "/"
    assert explore._norm("https://www.Ex.com/a/#top") == explore._norm("https://ex.com/a")
    assert explore.SKIP.search("/account/login") and explore.SKIP.search("/privacy")
    assert not explore.SKIP.search("/lot-value")


def test_search_examples_come_from_the_sites_own_items():
    pages = [{"url": f"https://ex.com/cards/{i}", "headings": [{"text": f"Charizard ex - {i}/165", "level": 1}]}
             for i in range(3)] + [{"url": "https://ex.com/", "headings": [{"text": "Home", "level": 1}]}]
    assert explore._examples(pages)[0] == "Charizard ex"


def test_a_fuller_page_scores_higher():
    empty = explore._score({"images": 0, "rows": 0, "items": 1, "words": 40}, 1)
    full = explore._score({"images": 24, "rows": 40, "items": 60, "words": 900}, 8)
    assert 0 <= empty < full <= 10


def test_sign_in_files_are_per_site_and_bad_addresses_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_VIDEO_SESSIONS", str(tmp_path))
    assert session.path_for("https://www.SetShelf.com/x") == str(tmp_path / "setshelf.com.json")
    assert session.state_for("https://setshelf.com") is None
    (tmp_path / "setshelf.com.json").write_text("{}")
    assert session.status("https://setshelf.com/")["signed_in"]
    with pytest.raises(ValueError):
        session.host("https://bad host/")


def test_a_sign_in_from_the_browser_keeps_only_that_sites_cookies_and_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_VIDEO_SESSIONS", str(tmp_path))
    state = {"cookies": [
        {"name": "sid", "value": "1", "domain": "setshelf.com", "path": "/", "expires": -1, "httpOnly": True,
         "sameSite": "no_restriction"},
        {"name": "ga", "value": "2", "domain": ".setshelf.com", "expires": 1900000000},
        {"name": "SID", "value": "3", "domain": ".google.com"},
        {"name": "x", "value": "4", "domain": "notsetshelf.com"},
        {"name": "tld", "value": "5", "domain": ".com"}],
        "origins": [{"origin": "https://setshelf.com", "localStorage": [{"name": "auth_token", "value": "jwt"}]},
                    {"origin": "https://accounts.google.com", "localStorage": [{"name": "k", "value": "v"}]}]}
    got = session.save_from_browser("https://www.setshelf.com/my-shelf", state)
    assert got["signed_in"] and got["cookies"] == 2 and got["storage"] == 1
    import json
    saved = json.load(open(session.path_for("https://setshelf.com")))
    assert [c["name"] for c in saved["cookies"]] == ["sid", "ga"]
    assert saved["cookies"][0]["sameSite"] == "None" and saved["cookies"][1]["path"] == "/"
    assert [o["origin"] for o in saved["origins"]] == ["https://setshelf.com"]
    with pytest.raises(ValueError):                          # nothing of the site's own: refused, not saved empty
        session.save_from_browser("https://ex.com", state)


def test_the_cursor_moves_like_a_hand_not_a_straight_line():
    import math
    from site_video.record import human_path
    pts = human_path(100, 100, 900, 500)                       # a long move
    assert pts[-1][:2] == (900, 500)
    secs = sum(p[2] for p in pts)
    assert 0.35 <= secs <= 1.3
    # it arcs: some point is well off the straight line between the ends
    off = max(abs((500 - 100) * (x - 100) - (900 - 100) * (y - 100)) / math.hypot(800, 400) for x, y, _ in pts)
    assert off > 15
    # past 300 px it overshoots and comes back: some point is further along than the target
    along = max(((x - 100) * 800 + (y - 100) * 400) / math.hypot(800, 400) for x, y, _ in pts)
    assert along > math.hypot(800, 400) + 5
    short = human_path(100, 100, 200, 120)
    assert sum(p[2] for p in short) < secs                     # Fitts: a short hop is quicker
    assert max(x for x, _, _ in short) <= 200.5                # and does not overshoot
    assert human_path(100, 100, 900, 500) == pts               # the same move is drawn the same way


def test_a_workflow_is_a_chain_and_own_site_clicks_are_kept():
    said = []
    raw = {"title": "T", "scenes": [
        {"url": "https://ex.com/lot-value", "captions": ["Twelve sets valued at once."], "narration": "Paste it.",
         "actions": [{"do": "type", "into": "Paste your sets", "text": "6016-1"}, {"do": "click", "text": "Estimate value"}]},
        {"continue": True, "captions": ["Now one bulk lot."], "narration": "Convert it.",
         "actions": [{"do": "click", "text": "Convert to Bulk Lot"}, {"do": "click", "text": "Part In", "in": "6016-1"},
                     {"do": "uncheck", "text": "6086-1"}]},
        {"url": "https://ex.com/never-seen", "captions": ["Somewhere."], "narration": "x"}]}
    mine = plan.check(raw, CRAWL, None, changes=True, log=said.append)
    s1, s2, s3 = mine["scenes"]
    assert [a["text"] for a in s1["actions"] if a["do"] == "click"] == ["Estimate value"]     # kept: it may appear later
    assert s2.get("continue") and s2["url"] == s1["url"]
    assert s2["actions"][1] == {"do": "click", "text": "Part In", "in": "6016-1"} and s2["actions"][2]["do"] == "uncheck"
    assert s3["url"] == "https://ex.com/" and any("never-seen was not explored" in m for m in said)
    said.clear()
    theirs = plan.check(raw, CRAWL, None, log=said.append)                       # someone else's site: only what was seen
    assert [a["do"] for a in theirs["scenes"][0]["actions"]] == ["type"]
    assert any("Estimate value" in m and "dropped" in m for m in said)


def test_a_rewrite_never_narrates_a_failure():
    from site_video import revise
    old = {"scenes": [{"url": "u", "captions": ["Every set in one bulk lot."], "narration": "One click."},
                      {"url": "u", "captions": ["Part-ins for ten sets."], "narration": "Part them out."}]}
    new = {"scenes": [{"url": "u", "captions": ["Broken/loading page with no content shown."], "narration": "x"},
                      {"url": "u", "captions": ["Ten part-ins, ready to sort."], "narration": "Part them out."}]}
    got = revise._keep_selling(old, new, log=lambda m: None)
    assert got["scenes"][0]["captions"] == ["Every set in one bulk lot."]
    assert got["scenes"][1]["captions"] == ["Ten part-ins, ready to sort."]


def test_auto_is_a_cursor_choice():
    from site_video import pipeline, record
    assert pipeline._cursor("Auto") == "auto" and "auto" in record.CURSORS


def test_a_brief_is_followed_not_answered_and_the_json_ask_comes_last():
    brief = "Help me draft an outline for a short promo video. Start at https://ex.com/lot-value and paste my sets."
    p = plan.prompt(CRAWL, 60, brief, changes=True)
    assert "THE PERSON'S BRIEF" in p and "do not write an outline" in p and "own site" in p
    assert p.rstrip().endswith("}") and p.index("--- end of brief ---") < p.index("Reply with only the JSON")
    assert "SITE MAP (2 pages" in p


def test_a_reply_with_its_scenes_under_another_name_is_still_used():
    raw = {"title": "Ex", "shots": [{"url": "https://ex.com/lot-value", "narration": "", "seconds": 8,
                                     "actions": [{"do": "type", "into": "Paste your sets", "text": "a\nb"}]}]}
    p = plan.check(raw, CRAWL, None)
    assert p["scenes"][0]["url"] == "https://ex.com/lot-value" and p["scenes"][0]["actions"][0]["text"] == "a\nb"


def test_review_verdicts_are_read_from_json_or_words():
    assert review._verdict('Sure: {"matches": false, "saw": "a login page", "problem": "not the results"}') == \
        {"matches": False, "score": 2, "saw": "a login page", "problem": "not the results"}
    assert review._verdict("The footage does not match the caption.")["matches"] is False
    assert review._verdict("Looks fine to me")["matches"] is True
    assert review._verdict('{"score": 4, "saw": "the docs", "problem": "tiny text"}')["matches"] is True
    assert review._verdict('{"score": 3, "saw": "x", "problem": "another section"}')["matches"] is True


def test_only_clearly_failed_scenes_are_sent_back_to_be_fixed():
    vs = [{"scene": 1, "matches": True, "saw": "", "problem": ""},
          {"scene": 2, "matches": False, "score": 1, "saw": "an empty search page", "problem": "no results shown"},
          {"scene": 3, "matches": False, "score": 2, "saw": "a different page", "problem": "picky"}]
    ask = review.fix_request(vs)
    assert "Scene 2" in ask and "an empty search page" in ask and "Scene 1:" not in ask
    assert "Scene 3" not in ask                    # a working page is reported, not rewritten
    assert review.fix_request(vs[:1]) == ""
    brief = review._brief({"url": "https://ex.com/", "captions": ["Prices for every set."], "narration": "Look.",
                           "actions": [{"do": "type", "into": "Search", "text": "6016"}]})
    assert "type Search 6016" in brief and "Prices for every set." in brief


_SET_PAGE = """<html><body style="margin:0;font:15px sans-serif"><div style="display:flex;gap:24px;padding:16px">
 <main style="flex:1"><h1>75192-1 Millennium Falcon</h1><p>""" + "The ultimate Millennium Falcon. " * 150 + """</p>
  <h2>Price history</h2><div style="height:300px"></div><div style="height:900px"></div></main>
 <aside style="width:280px"><div style="height:120px">PURCHASE</div>
  <div style="border:1px solid #ddd;padding:8px"><div>DETAILS</div><div>ID 75192-1</div><div>Pieces 7,541</div>
   <div>Year 2017</div></div></aside></div></body></html>"""


def test_scrolling_stops_at_what_is_talked_about_and_outlines_it():
    """Seen 2026-10-30 on SetShelf: a scroll to "DETAILS", already on screen, moved it to the top anyway and pushed
    the set's title and picture off the screen. Now a target in view is not scrolled to, one below is scrolled to
    only as far as it and what it heads need, and the step's card or section gets an outline."""
    sp = pytest.importorskip("playwright.sync_api")
    from site_video.record import OVERLAY
    try:
        with sp.sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1280, "height": 720})
            pg.set_content(_SET_PAGE)
            pg.evaluate(OVERLAY)
            plan_ = pg.evaluate("() => window.__sv.scrollPlan('DETAILS')")
            assert plan_ == {"found": True, "y": None, "mark": True}
            pg.evaluate("() => window.__sv.mark(window.__svTarget, 'block')")
            assert pg.evaluate("() => window.__svMarked[0].innerText").startswith("DETAILS\nID 75192-1")
            y = pg.evaluate("() => window.__sv.scrollPlan('Price history').y")
            pg.evaluate("y => window.__sv.scrollTo(y, 50)", y)
            pg.wait_for_timeout(200)
            top = pg.evaluate("() => document.querySelector('h2').getBoundingClientRect().top")
            assert 720 * 0.12 <= top <= 720 * 0.6           # the heading and the chart under it, not past them
            assert pg.evaluate("() => window.__sv.markFor(document.querySelector('h1'), 'block')") is None
            b.close()
    except sp.Error as e:
        pytest.skip(f"no browser here: {e}")
