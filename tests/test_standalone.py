"""The site-video queue run WITHOUT Odysseus, as a user would: `python -m site_video serve` in its own process, with
no ODYSSEUS_* / SITE_VIDEO_ODYSSEUS_* variables. It answers on loopback with no token, and when asked to listen
beyond loopback it never stays open: it makes a random token (or uses SITE_VIDEO_TOKEN). ffmpeg and playwright are
not needed."""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _env(**extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ODYSSEUS_", "SITE_VIDEO_ODYSSEUS", "MOD_")) and k != "SITE_VIDEO_TOKEN"}
    env.update(PYTHONUNBUFFERED="1", **extra)
    return env


def _start(host="127.0.0.1", **env_extra):
    port = _free_port()
    home = tempfile.mkdtemp(prefix="sv-standalone-")
    proc = subprocess.Popen([sys.executable, "-m", "site_video", "serve", "--host", host, "--port", str(port),
                             "--home", home], cwd=ROOT, env=_env(**env_extra),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail("the queue exited: " + proc.stdout.read()[-2000:])
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, f"http://127.0.0.1:{port}"
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.fail("the queue did not listen within 30 s")


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def loopback():
    proc, base = _start()
    yield base
    _stop(proc)


def test_loopback_needs_no_token(loopback):
    status, body = _get(loopback + "/api/info")
    assert status == 200 and "voices" in json.loads(body)
    status, body = _get(loopback + "/api/jobs")
    assert status == 200 and json.loads(body) == []
    status, body = _get(loopback + "/")
    assert status == 200 and b"<html" in body.lower()


def test_forged_odysseus_headers_change_nothing(loopback):
    forged = {"X-Odysseus-User": "admin", "X-Odysseus-Mod": "site-video", "X-Odysseus-Ts": str(int(time.time())),
              "X-Odysseus-Sig": "0" * 64}
    assert _get(loopback + "/api/jobs", forged)[0] == 200      # loopback queue is open; headers are simply not read


def test_beyond_loopback_without_a_token_makes_one():
    proc, base = _start(host="0.0.0.0")
    try:
        assert _get(base + "/api/info")[0] == 401
        assert _get(base + "/api/jobs")[0] == 401
        assert _get(base + "/api/jobs", {"Authorization": "Bearer wrong"})[0] == 401
        # the random token is printed once at start
        proc.stdout.flush()
        os.set_blocking(proc.stdout.fileno(), False)
        out = ""
        deadline = time.time() + 5
        while "random token" not in out and time.time() < deadline:
            out += proc.stdout.read() or ""
            time.sleep(0.1)
        tok = re.search(r"random token for this run: (\S+)", out)
        assert tok, out
        status, body = _get(base + "/api/jobs", {"Authorization": "Bearer " + tok.group(1)})
        assert status == 200 and json.loads(body) == []
        assert _get(base + "/api/info?token=" + tok.group(1))[0] == 200
    finally:
        _stop(proc)


def test_beyond_loopback_uses_the_configured_token():
    proc, base = _start(host="0.0.0.0", SITE_VIDEO_TOKEN="my-own-token")
    try:
        assert _get(base + "/api/jobs")[0] == 401
        status, body = _get(base + "/api/jobs", {"Authorization": "Bearer my-own-token"})
        assert status == 200 and json.loads(body) == []
    finally:
        _stop(proc)
