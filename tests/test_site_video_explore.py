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
