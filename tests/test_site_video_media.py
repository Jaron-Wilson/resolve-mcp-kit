"""The owner's own videos: a website, their videos, or both."""
import io
import os

import pytest

from site_video import assemble, media, pipeline, plan, server
from site_video.queue import Queue
from site_video.util import FPS, HANDLE, ffmpeg, media_seconds

CRAWL = {"start": "https://ex.com", "pages": [
    {"url": "https://ex.com/", "title": "Ex", "headings": [{"text": "Pricing", "at": 0.5}], "buttons": ["Sign up"]}]}
DEMO = {"file": "demo.mp4", "seconds": 40.0, "width": 1280, "height": 720, "audio": True, "note": "app demo",
        "shots": [{"t": 3.0, "what": "a phone app with a card list"}], "speech": [{"from": 0, "to": 15, "text": "hi"}]}
BROLL = {"file": "broll.mov", "seconds": 20.0, "width": 1920, "height": 1080, "audio": False, "note": ""}


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """A 4 second 640x360 test video with a tone."""
    out = str(tmp_path_factory.mktemp("v") / "demo.mp4")
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=4", "-f", "lavfi",
           "-i", "sine=frequency=440:duration=4", "-shortest", "-c:v", "libx264", "-c:a", "aac", out)
    return out


def test_a_request_needs_a_link_or_videos(clip, tmp_path):
    with pytest.raises(ValueError, match="link, your own videos"):
        pipeline.request("", "auto", "auto", "none", "ffmpeg")
    r = pipeline.request("", "1min", "auto", "none", "ffmpeg", media=[{"file": clip, "note": " the demo "}])
    assert r["url"] == "" and r["media"] == [{"file": os.path.abspath(clip), "note": "the demo"}]
    assert pipeline.request("https://ex.com", media=[clip])["media"][0]["file"] == os.path.abspath(clip)
    with pytest.raises(ValueError, match="not found"):
        pipeline.request("", media=[str(tmp_path / "nope.mp4")])
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    with pytest.raises(ValueError, match="video file"):
        pipeline.request("", media=[str(doc)])


def test_the_planner_is_told_what_is_in_the_videos():
    p = plan.prompt(CRAWL, 300, "auto", [DEMO, BROLL], media.catalogue([DEMO, BROLL]))
    assert "demo.mp4" in p and "a phone app with a card list" in p and "said 0-15s" in p
    assert "fill the rest of the time with website scenes" in p
    only = plan.prompt(None, None, "auto", [DEMO], media.catalogue([DEMO]))
    assert "There is no website" in only and "The crawl" not in only and '"url"' not in only


def test_a_site_fills_the_length_around_the_owners_videos():
    raw = {"title": "Ex", "scenes": [
        {"url": "https://ex.com/", "caption": "Home", "narration": "word " * 12, "seconds": 8},
        {"video": "demo", "from": 5, "to": 25, "sound": "voice", "caption": "The app", "narration": "word " * 10},
        {"url": "https://ex.com/", "caption": "Price", "narration": "word " * 12, "seconds": 8},
        {"url": "https://ex.com/", "caption": "Docs", "narration": "word " * 12, "seconds": 8},
        {"url": "https://ex.com/", "caption": "Sign up", "narration": "word " * 12, "seconds": 8}]}
    p = plan.check(raw, CRAWL, 300, [DEMO, BROLL])
    vids = [s for s in p["scenes"] if "video" in s]
    assert [v["video"] for v in vids] == ["demo.mp4", "broll.mov"]       # the name repaired; the left-out one added
    assert vids[0]["seconds"] == 20.0                                    # the owner's footage keeps its length
    assert vids[1]["sound"] == "voice"                                   # no sound to keep in broll
    total = sum(s["seconds"] for s in p["scenes"])
    assert 280 <= total <= 300                                           # 5 minutes with the intro and outro


def test_kept_sound_means_no_narration_and_moments_stay_inside_the_video():
    raw = {"scenes": [{"video": "demo.mp4", "from": 38, "to": 90, "sound": "keep", "narration": "talk over"},
                      {"video": "broll.mov", "from": -4, "to": 2, "sound": "keep", "narration": "word " * 20}]}
    a, b = plan.check(raw, None, None, [DEMO, BROLL])["scenes"]
    assert a["narration"] == "" and a["sound"] == "keep" and a["from"] == 38 and a["to"] == 40
    assert b["sound"] == "voice" and b["from"] == 0                      # no sound in broll to keep
    assert b["seconds"] >= 20 / plan.WORDS_PER_SECOND                    # stretched to say its narration


def test_a_moment_is_not_shown_twice():
    raw = {"scenes": [{"video": "demo.mp4", "from": 0, "to": 16, "caption": "a"},
                      {"video": "demo.mp4", "from": 8, "to": 16, "caption": "again"},
                      {"video": "demo.mp4", "from": 16, "to": 30, "caption": "later"}]}
    assert [s["caption"] for s in plan.check(raw, None, None, [DEMO])["scenes"]] == ["a", "later"]


def test_videos_only_run_on_to_reach_the_length_as_far_as_the_footage_goes():
    raw = {"title": "", "scenes": [{"video": "demo.mp4", "from": 0, "to": 10, "caption": "a"},
                                   {"video": "broll.mov", "from": 0, "to": 10, "caption": "b"}]}
    p = plan.check(raw, None, 60, [DEMO, BROLL])
    assert sum(s["seconds"] for s in p["scenes"]) == pytest.approx(45, abs=0.1)        # 60 less the cards
    p = plan.check(raw, None, 300, [DEMO, BROLL])
    assert [s["to"] for s in p["scenes"]] == [40.0, 20.0]                 # all there is
    assert p["title"] == "demo" and p["url"] == ""


def test_a_moment_is_cut_to_exact_frames_with_its_sound(clip, tmp_path):
    out, wav = str(tmp_path / "c.mp4"), str(tmp_path / "c.wav")
    media.cut(clip, 1.0, 5.0, out, wav)                                  # runs past the end: the last frame holds
    assert media_seconds(out) == pytest.approx(5.0 + 2 * HANDLE / FPS, abs=1.5 / FPS)   # with its handles
    assert media_seconds(wav) == pytest.approx(5.0, abs=0.05)
    info = media.analyze(clip, "note", str(tmp_path / "a.json"))
    assert info["audio"] and info["width"] == 640 and info["seconds"] == pytest.approx(4, abs=0.1)


def test_a_videos_own_sound_goes_into_the_soundtrack(clip, tmp_path):
    own = str(tmp_path / "own.wav")
    media.cut(clip, 0, 3.0, str(tmp_path / "c.mp4"), own)
    secs = [2.0, 3.0, 2.0]
    mix = str(tmp_path / "mix.wav")
    assemble.soundtrack(str(tmp_path), [None, None, None], secs, None, mix, [None, own, None])
    assert media_seconds(mix) == pytest.approx(7.0, abs=0.05)


def test_uploads_move_into_their_job_and_only_uploads_are_accepted_over_http(clip, tmp_path):
    q = Queue(str(tmp_path / "home"))
    data = open(clip, "rb").read()
    path = q.save_upload("../../My demo.mp4", io.BytesIO(data), len(data))
    assert q.is_upload(path) and os.path.basename(path) == "My demo.mp4"
    with pytest.raises(ValueError, match="stopped"):
        q.save_upload("x.mp4", io.BytesIO(b"abc"), 10)
    with pytest.raises(ValueError, match="upload it first"):
        server._allowed_media(q, [{"file": clip}])
    req = pipeline.request("", media=server._allowed_media(q, [{"file": path, "note": "n"}]))
    j = q.submit(req)
    moved = j["request"]["media"][0]["file"]
    assert moved.startswith(q._path(j["id"])) and os.path.exists(moved) and not os.path.exists(path)
    q.remove(j["id"])
    assert not os.path.exists(moved)


def test_a_model_that_only_thinks_is_asked_again_with_more_room(monkeypatch):
    import json
    from site_video import llm

    def reply(content, why):
        return io.BytesIO(json.dumps({"model": "m", "choices": [{"finish_reason": why,
                                                                 "message": {"content": content}}]}).encode())
    budgets = []

    def thinks_first(req, timeout=0):
        budgets.append(json.loads(req.data)["max_tokens"])
        return reply("", "length") if len(budgets) == 1 else reply('{"ok": 1}', "stop")
    monkeypatch.setattr(llm.urllib.request, "urlopen", thinks_first)
    assert llm.chat("s", "u", max_tokens=100) == '{"ok": 1}' and budgets == [100, 200]
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=0: reply("", "length"))
    with pytest.raises(RuntimeError, match="thinking"):
        llm.chat("s", "u", max_tokens=100)
