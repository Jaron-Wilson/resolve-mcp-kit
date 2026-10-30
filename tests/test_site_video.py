"""site_video without a network, a browser or Resolve: the parts that decide things."""
import json
import os

import pytest

from site_video import assemble, pipeline, plan, voice
from site_video.queue import Queue
from site_video.util import FPS, parse_length

CRAWL = {"start": "https://ex.com", "pages": [
    {"url": "https://ex.com/", "title": "Ex", "headings": [{"text": "Pricing", "at": 0.5}], "buttons": ["Sign up"]},
    {"url": "https://ex.com/docs", "title": "Docs", "headings": [], "buttons": []}]}


@pytest.mark.parametrize("text,secs", [("5min", 300), ("5m", 300), ("90s", 90), ("1:30", 90), ("2", 120),
                                       ("2.5 min", 150), ("auto", None), ("", None), (None, None)])
def test_lengths(text, secs):
    assert parse_length(text) == secs


@pytest.mark.parametrize("bad", ["5 hours", "abc", "3s", "45min"])
def test_bad_lengths(bad):
    with pytest.raises(ValueError):
        parse_length(bad)


def test_a_plan_is_repaired_to_what_the_site_and_narration_allow():
    raw = {"title": "Ex", "scenes": [
        {"url": "https://evil.example/", "caption": "Off site", "narration": "word " * 40, "seconds": 3,
         "actions": [{"do": "scroll", "to": "Pricing"}, {"do": "submit", "text": "Buy"}, "junk"]},
        {"url": "https://ex.com/docs/", "caption": "Docs", "narration": "", "seconds": 6, "actions": []}]}
    p = plan.check(raw, CRAWL, None)
    s0, s1 = p["scenes"]
    assert s0["url"] == "https://ex.com/"                       # unknown URL -> the start page
    assert s0["seconds"] >= 40 / plan.WORDS_PER_SECOND          # long enough to say the narration
    assert s0["actions"] == [{"do": "scroll", "to": "Pricing"}]  # unknown or unsafe actions dropped
    assert s1["url"] == "https://ex.com/docs/" and s1["seconds"] == 6
    assert p["outro"]["call_to_action"] == "https://ex.com/"


def test_a_plan_with_no_scenes_is_refused():
    with pytest.raises(ValueError):
        plan.check({"scenes": []}, CRAWL, 60)


def test_a_target_length_stretches_scenes_but_never_below_the_narration():
    raw = {"scenes": [{"url": "https://ex.com/", "narration": "", "seconds": 5},
                      {"url": "https://ex.com/", "narration": "word " * 24, "seconds": 11}]}
    p = plan.check(raw, CRAWL, 60)
    assert abs(sum(s["seconds"] for s in p["scenes"]) + 10 - 60) < 6
    assert p["scenes"][1]["seconds"] >= 24 / plan.WORDS_PER_SECOND


def test_segments_fit_their_narration_and_land_on_whole_frames():
    p = {"scenes": [{"seconds": 5.0}, {"seconds": 12.0}]}
    d = assemble.durations(p, [2.0, 9.0, 1.0, 6.0])
    assert d[1] >= 9.0 + 1.1 and d[2] >= 12.0 and d[3] >= 6.0 + 0.7
    assert all(abs(x * FPS - round(x * FPS)) < 1e-6 for x in d)


@pytest.mark.parametrize("spec,ok", [("none", True), ("openai", True), ("openai:af_heart", True),
                                     ("elevenlabs:abc123", True), ("elevenlabs", False), ("odysseus", True),
                                     ("siri", False)])
def test_voices(spec, ok):
    if ok:
        voice.parse(spec)
    else:
        with pytest.raises(ValueError):
            voice.parse(spec)


def test_requests_are_checked():
    r = pipeline.request("https://ex.com", "2min", "", "none", "auto")
    assert r["length"] == 120 and r["notes"] == "auto"
    for bad in (dict(url="ex.com"), dict(url="https://ex.com", editor="premiere"),
                dict(url="https://ex.com", voice_spec="siri")):
        with pytest.raises(ValueError):
            pipeline.request(**bad)


def test_a_video_can_name_the_model_that_writes_its_script(monkeypatch):
    from site_video import llm
    assert pipeline.request("https://ex.com", model=" gemma4:26b ")["model"] == "gemma4:26b"
    assert pipeline.request("https://ex.com")["model"] == ""
    with pytest.raises(ValueError):
        pipeline.request("https://ex.com", model="two words")
    sent = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "<think>x</think>ok"}}]}).encode()

    def fake_open(req, timeout=0):
        sent.append(json.loads(req.data)["model"])
        return Reply()
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_open)
    monkeypatch.setenv("SITE_VIDEO_LLM_MODEL", "qwen3:8b")
    assert llm.chat("s", "u", model="gemma4:26b") == "ok" and llm.chat("s", "u") == "ok"
    assert sent == ["gemma4:26b", "qwen3:8b"]


def test_the_queue_runs_stages_and_keeps_state(tmp_path, monkeypatch):
    q = Queue(str(tmp_path), parallel=2)
    calls = []

    def fake_stage(jid, stage):
        calls.append(stage)
        if stage == "edit":
            with open(os.path.join(q._path(jid), "result.json"), "w") as f:
                json.dump({"video": "/x.mp4", "editor": "ffmpeg", "seconds": 61.0}, f)
    monkeypatch.setattr(q, "_stage", fake_stage)
    j = q.submit(pipeline.request("https://ex.com", "1min", "auto", "none", "ffmpeg"))
    assert q.get(j["id"])["status"] == "queued"
    q._run(j["id"])
    done = q.get(j["id"])
    assert calls == ["prep", "edit"] and done["status"] == "done" and done["seconds"] == 61.0

    def broken(jid, stage):
        raise RuntimeError("the site would not load")
    monkeypatch.setattr(q, "_stage", broken)
    k = q.submit(pipeline.request("https://ex.com", "auto", "auto", "none", "ffmpeg"))
    q._run(k["id"])
    assert q.get(k["id"])["status"] == "failed" and "would not load" in q.get(k["id"])["error"]
    assert q.retry(k["id"])["status"] == "queued"
    assert q.cancel(k["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        q.retry(j["id"])                     # a finished job is not run again


def test_jobs_interrupted_by_a_restart_are_queued_again(tmp_path):
    q = Queue(str(tmp_path))
    j = q.submit(pipeline.request("https://ex.com", "auto", "auto", "none", "ffmpeg"))
    q._update(j["id"], status="preparing")
    assert Queue(str(tmp_path)).get(j["id"])["status"] == "queued"


def test_job_ids_cannot_escape_the_jobs_folder(tmp_path):
    q = Queue(str(tmp_path))
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(KeyError):
            q.get(bad)


def test_the_mod_only_accepts_requests_signed_by_odysseus(monkeypatch):
    import hashlib
    import hmac
    import time
    from site_video import odysseus_mod as m
    monkeypatch.setattr(m, "TOKEN", "odm_test")

    def sign(user, ts):
        return hmac.new(b"odm_test", f"v1\n{m.MOD_ID}\n{user}\n{ts}".encode(), hashlib.sha256).hexdigest()
    ts = str(int(time.time()))
    assert m._signed({"X-Odysseus-User": "alice", "X-Odysseus-Ts": ts, "X-Odysseus-Sig": sign("alice", ts)})
    assert not m._signed({"X-Odysseus-User": "mallory", "X-Odysseus-Ts": ts, "X-Odysseus-Sig": sign("alice", ts)})
    old = str(int(time.time()) - 1000)
    assert not m._signed({"X-Odysseus-User": "alice", "X-Odysseus-Ts": old, "X-Odysseus-Sig": sign("alice", old)})
    assert not m._signed({})


def test_the_mod_tells_the_model_what_a_job_is_doing():
    from site_video.odysseus_mod import _job_text
    j = {"id": "j1", "status": "preparing", "step": "recording scene 2/5", "progress": 0.5,
         "request": {"url": "https://ex.com", "length": 120, "voice": "odysseus", "notes": "show pricing"}}
    t = _job_text(j, "/mods/site-video")
    assert "recording scene 2/5, 50%" in t and "show pricing" in t
    t = _job_text(dict(j, status="done", seconds=118.2, editor="resolve"), "/mods/site-video")
    assert "118.2 s" in t and "resolve" in t and "/mods/site-video/" in t
