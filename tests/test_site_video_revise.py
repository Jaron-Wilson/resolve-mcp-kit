"""Changing a finished video: an edited script is checked, saved, and only what changed is made again."""
import os

import pytest

from site_video import pipeline, plan, revise
from site_video.queue import Queue
from site_video.util import ffmpeg, write_json

CRAWL = {"start": "https://ex.com", "pages": [
    {"url": "https://ex.com/", "title": "Ex", "headings": [{"text": "Pricing", "at": 0.5}], "buttons": ["Sign up", "Pro plan"]}]}
PLAN = {"title": "Ex", "tagline": "t", "intro": {"narration": "hi"}, "outro": {"narration": "bye", "call_to_action": "go"},
        "scenes": [{"url": "https://ex.com/", "caption": "Price", "narration": "one two", "seconds": 6,
                    "actions": [{"do": "hover", "text": "Sign up"}]},
                   {"url": "https://ex.com/", "caption": "End", "narration": "three", "seconds": 6, "actions": []}]}


def _job(tmp_path):
    d = tmp_path / "job"
    d.mkdir()
    write_json(str(d / "crawl.json"), CRAWL)
    write_json(str(d / "plan.json"), plan.check(PLAN, CRAWL, None))
    return str(d)


def test_an_edit_is_checked_saved_and_described(tmp_path):
    d = _job(tmp_path)
    new = plan.check(PLAN, CRAWL, None)
    new["scenes"][0]["actions"][0]["text"] = "Pro plan"
    new["scenes"][1]["url"] = "https://evil.example/"            # not on the site: repaired
    new["scenes"].reverse()
    done = revise.apply(d, new)
    assert done["plan"]["scenes"][0]["url"] == "https://ex.com/"
    assert any("Scene 2" in c and "Pro plan" in c for c in done["changes"])
    assert os.path.exists(os.path.join(d, "plan.1.json"))      # the old script is kept
    with pytest.raises(ValueError):
        revise.apply(d, {"title": "no scenes"})


def test_a_video_taken_out_stays_out_when_the_person_edits():
    demo = {"file": "a.mp4", "seconds": 20.0, "width": 640, "height": 360, "audio": False, "note": ""}
    edited = {"scenes": [{"url": "https://ex.com/", "caption": "x", "narration": "", "seconds": 5}]}
    assert all("video" not in s for s in plan.check(edited, CRAWL, None, [demo], fill_missing=False)["scenes"])
    assert any("video" in s for s in plan.check(edited, CRAWL, None, [demo])["scenes"])


def test_a_change_in_words_goes_through_the_script_model(tmp_path, monkeypatch):
    d = _job(tmp_path)
    seen = {}

    def fake_chat(system, user, model=""):
        seen["user"] = user
        out = plan.check(PLAN, CRAWL, None)
        out["scenes"][0]["actions"] = [{"do": "hover", "text": "Pro plan"}]
        import json
        return json.dumps(out)
    monkeypatch.setattr(revise.llm, "chat", fake_chat)
    got = revise.suggest(d, "point at the Pro plan instead")
    assert "point at the Pro plan instead" in seen["user"] and "Pro plan" in seen["user"]
    assert got["changes"] == ["Scene 1: shows https://ex.com/ (hover Pro plan)"]
    assert not os.path.exists(os.path.join(d, "plan.1.json"))  # a suggestion saves nothing


def test_running_jobs_cannot_be_changed_and_a_change_queues_the_job(tmp_path):
    q = Queue(str(tmp_path / "home"))
    j = q.submit(pipeline.request("https://ex.com", "auto", "auto", "none", "ffmpeg"))
    d = q._path(j["id"])
    write_json(os.path.join(d, "crawl.json"), CRAWL)
    write_json(os.path.join(d, "plan.json"), plan.check(PLAN, CRAWL, None))
    with pytest.raises(ValueError, match="queued"):
        q.revise(j["id"], PLAN)
    q._update(j["id"], status="done")
    with pytest.raises(ValueError, match="cursor"):
        q.revise(j["id"], PLAN, "sparkles")
    k = q.revise(j["id"], PLAN, "hand")
    assert k["status"] == "queued" and k["request"]["cursor"] == "hand" and k["revisions"] == 1


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("v") / "demo.mp4")
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=12", "-f", "lavfi",
           "-i", "sine=frequency=440:duration=12", "-shortest", "-c:v", "libx264", "-c:a", "aac", out)
    return out


def test_only_the_changed_scene_is_made_again(tmp_path, clip):
    pytest.importorskip("playwright")
    req = pipeline.request("", "auto", "auto", "none", "ffmpeg", media=[{"file": clip, "note": "demo"}])
    d = str(tmp_path / "job")
    os.makedirs(d)
    first = {"title": "Demo", "scenes": [
        {"video": "demo.mp4", "from": 0, "to": 3, "sound": "keep", "caption": "One"},
        {"video": "demo.mp4", "from": 4, "to": 7, "sound": "voice", "caption": "Two", "narration": ""}]}
    pipeline.footage.analyze(clip, "demo", os.path.join(d, "media", "00.json"))
    known = [pipeline.read_json(os.path.join(d, "media", "00.json"))]
    write_json(os.path.join(d, "plan.json"), plan.check(first, None, None, known))
    try:
        a = pipeline.prep(d, req)
    except Exception as e:                                       # no Chromium here
        pytest.skip(f"no browser: {type(e).__name__}")
    stamp = {c: os.path.getmtime(c) for c in a["clips"]}
    edited = pipeline.read_json(os.path.join(d, "plan.json"))
    edited["scenes"][1]["captions"] = ["Two, better"]           # a caption is its own image: no clip is cut again
    revise.apply(d, edited)
    b = pipeline.prep(d, req)
    assert b["clips"] == a["clips"] and all(os.path.getmtime(c) == stamp[c] for c in b["clips"])
    assert [c["text"] for c in b["captions"]][-1] == "Two, better"
    assert all(os.path.exists(c["png"]) for c in b["captions"])
    edited = pipeline.read_json(os.path.join(d, "plan.json"))
    edited["scenes"][1]["to"] = 8                               # a longer moment is
    revise.apply(d, edited)
    b = pipeline.prep(d, req)
    same = [c for c in b["clips"] if c in stamp and os.path.getmtime(c) == stamp[c]]
    assert b["clips"][2] not in stamp and b["clips"][1] in same
    assert sorted(f for f in os.listdir(os.path.join(d, "clips")) if f.endswith(".mp4")) == \
        sorted(os.path.basename(c) for c in b["clips"])         # the old version of the scene is gone
    assert sorted(f for f in os.listdir(os.path.join(d, "clips")) if f.startswith("cap_")) == \
        sorted(os.path.basename(c["png"]) for c in b["captions"])
