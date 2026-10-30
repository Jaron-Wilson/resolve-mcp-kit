"""Nothing in this repository may point at, or assume, one person's computers, and the extension must point at the
queue it came from."""

import http.client
import io
import json
import os
import re
import shutil
import subprocess
import threading
import zipfile
from http.server import ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "site_video", "browser_extension")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}

# Tailscale / carrier-grade NAT addresses (100.64.0.0 to 100.127.255.255): one person's tailnet, never a default.
# Placeholders like 100.x.y.z in the docs do not match.
TAILNET_IP = re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
PERSONAL = re.compile(r"(/home/jaron|C:\\+Users\\+jaron|DESKTOP-JARON|jaron-dev|totoro|arrietty|desktop-jaron|"
                      r"chatgpt:gpt|@gmail\.com|\.ts\.net)", re.I)


def _text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = os.path.join(base, name)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    yield os.path.relpath(path, ROOT), f.read()
            except (UnicodeDecodeError, OSError):
                continue                      # a binary file


def test_no_tailnet_addresses_anywhere():
    hits = [f"{p}: {m.group(0)}" for p, text in _text_files() for m in TAILNET_IP.finditer(text)]
    assert not hits, "a tailnet address is hardcoded: " + ", ".join(hits)


def test_no_personal_paths_hosts_models_or_addresses():
    hits = [f"{p}: {m.group(0)}" for p, text in _text_files() for m in PERSONAL.finditer(text)]
    assert not hits, "something personal is hardcoded: " + ", ".join(hits)


def test_every_default_address_is_this_computer():
    """Every http(s) address with a number in it, in the code, is loopback (or the OpenAI API for voices)."""
    bad = []
    for p, text in _text_files():
        if not p.endswith((".py", ".js", ".html", ".sh", ".cmd", ".json")):
            continue
        for m in re.finditer(r"https?://(\d{1,3}(?:\.\d{1,3}){3})", text):
            if not m.group(1).startswith("127."):
                bad.append(f"{p}: {m.group(0)}")
    assert not bad, bad


# ── the extension zip ──

def _zip(address):
    from site_video.server import extension_zip
    z = zipfile.ZipFile(io.BytesIO(extension_zip(address)))
    return z, z.read("site-video-signin/config.js").decode()


def test_the_zip_carries_the_address_it_was_made_for():
    z, cfg = _zip("https://queue.example.org:9000")
    assert 'self.SITE_VIDEO_DEFAULT_SERVER = "https://queue.example.org:9000";' in cfg
    names = z.namelist()
    assert sorted(set(names)) == sorted(names)                    # config.js once, not twice
    assert {"site-video-signin/" + n for n in ("manifest.json", "popup.html", "popup.js", "safety.js",
                                               "config.js")} <= set(names)
    assert "config.js" in z.read("site-video-signin/popup.html").decode()


def test_the_address_comes_from_the_request():
    from site_video.server import FALLBACK_ADDRESS, own_address
    assert FALLBACK_ADDRESS == "http://127.0.0.1:8940"
    assert own_address("192.168.1.20:8940") == "http://192.168.1.20:8940"
    assert own_address("queue.example.org", "https") == "https://queue.example.org"
    assert own_address("queue.example.org", "https, http") == "https://queue.example.org"
    assert own_address("[::1]:8940") == "http://[::1]:8940"
    assert own_address("0.0.0.0:8940") == "http://127.0.0.1:8940"
    assert own_address("host", "javascript") == "http://host"
    for bad in (None, "", "a b", 'x";alert(1);//', "host/../x", "host:port", "user@host"):
        assert own_address(bad) == "http://127.0.0.1:8940", bad


def test_the_served_zip_points_at_the_server_it_came_from(tmp_path):
    from site_video.queue import Queue
    from site_video.server import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Queue(str(tmp_path))))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        for host, proto, want in ((f"queue.example.org:{port}", None, f"http://queue.example.org:{port}"),
                                  ("queue.example.org", "https", "https://queue.example.org")):
            c = http.client.HTTPConnection("127.0.0.1", port)
            c.putrequest("GET", "/api/signin/extension.zip", skip_host=True)
            c.putheader("Host", host)
            if proto:
                c.putheader("X-Forwarded-Proto", proto)
            c.endheaders()
            r = c.getresponse()
            assert r.status == 200 and r.getheader("Content-Type") == "application/zip"
            cfg = zipfile.ZipFile(io.BytesIO(r.read())).read("site-video-signin/config.js").decode()
            assert json.dumps(want) in cfg
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_unpacked_extension_defaults_to_this_computer():
    with open(os.path.join(EXT, "config.js"), encoding="utf-8") as f:
        assert 'SITE_VIDEO_DEFAULT_SERVER = "http://127.0.0.1:8940"' in f.read()
    with open(os.path.join(EXT, "popup.js"), encoding="utf-8") as f:
        js = f.read()
    assert "SITE_VIDEO_DEFAULT_SERVER" in js and 'DEFAULT = "http' not in js


# ── the plain-http warning ──

@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_plain_http_to_another_computer_is_flagged():
    script = ("const {isInsecureRemote: f} = require(process.argv[1]);"
              "console.log(JSON.stringify(process.argv.slice(2).map(f)))")
    urls = ["http://127.0.0.1:8940", "http://localhost:8940", "http://127.9.9.9", "http://[::1]:8940",
            "https://queue.example.org", "http://192.168.1.20:8940", "http://queue.example.org", "http://10.0.0.5"]
    out = subprocess.run(["node", "-e", script, os.path.join(EXT, "safety.js"), *urls],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [False, False, False, False, False, True, True, True]


def test_the_popup_asks_before_sending_over_plain_http():
    with open(os.path.join(EXT, "popup.js"), encoding="utf-8") as f:
        js = f.read()
    assert "isInsecureRemote(server) && !confirmed" in js
    assert js.index("isInsecureRemote(server) && !confirmed") < js.index("/api/signin/import")
    with open(os.path.join(EXT, "popup.html"), encoding="utf-8") as f:
        assert 'id="warn"' in f.read()
