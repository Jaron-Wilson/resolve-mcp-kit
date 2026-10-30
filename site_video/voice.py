"""Narration, one WAV per segment. The voice is chosen per video:

none                  no narration (scenes keep their planned length)
openai[:voice]        any OpenAI-compatible /audio/speech: OpenAI, or a local Kokoro-FastAPI server
                      SITE_VIDEO_TTS_URL (default https://api.openai.com/v1), SITE_VIDEO_TTS_KEY (or OPENAI_API_KEY),
                      SITE_VIDEO_TTS_MODEL (default tts-1; "kokoro" for Kokoro-FastAPI); voice default alloy
elevenlabs:<voice_id> ElevenLabs, ELEVENLABS_API_KEY; SITE_VIDEO_ELEVENLABS_MODEL (default eleven_multilingual_v2)
odysseus              an Odysseus server's own voice: SITE_VIDEO_ODYSSEUS_URL, SITE_VIDEO_ODYSSEUS_TOKEN
"""

import json
import os
import tempfile
import urllib.request

from .util import RATE, ffmpeg, media_seconds

PROVIDERS = ("none", "openai", "elevenlabs", "odysseus")


def parse(spec) -> tuple:
    spec = str(spec or "none").strip()
    provider, _, voice = spec.partition(":")
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"voice {spec!r}: use one of none, openai[:voice], elevenlabs:<voice id>, odysseus")
    if provider == "elevenlabs" and not voice:
        raise ValueError("elevenlabs needs a voice id: elevenlabs:<voice id>")
    return provider, voice


def _post(url, body, headers, timeout=300) -> bytes:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _audio(provider: str, voice: str, text: str) -> bytes:
    if provider == "openai":
        base = os.environ.get("SITE_VIDEO_TTS_URL", "https://api.openai.com/v1").rstrip("/")
        key = os.environ.get("SITE_VIDEO_TTS_KEY") or os.environ.get("OPENAI_API_KEY", "")
        return _post(base + "/audio/speech", {"model": os.environ.get("SITE_VIDEO_TTS_MODEL", "tts-1"),
                                              "voice": voice or "alloy", "input": text, "response_format": "wav"},
                     {"Authorization": "Bearer " + key} if key else {})
    if provider == "elevenlabs":
        key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        return _post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                     {"text": text, "model_id": os.environ.get("SITE_VIDEO_ELEVENLABS_MODEL", "eleven_multilingual_v2")},
                     {"xi-api-key": key, "Accept": "audio/mpeg"})
    if provider == "odysseus":
        base = os.environ.get("SITE_VIDEO_ODYSSEUS_URL", "").rstrip("/")
        if not base:
            raise RuntimeError("SITE_VIDEO_ODYSSEUS_URL is not set")
        tok = os.environ.get("SITE_VIDEO_ODYSSEUS_TOKEN", "")
        return _post(base + "/api/tts/synthesize", {"text": text},
                     {"Authorization": "Bearer " + tok} if tok else {})
    raise ValueError(provider)


def speak(spec, text: str, out_wav: str) -> float:
    """Write `text` as a 48 kHz stereo WAV and return its length in seconds; 0 and no file for no narration."""
    provider, voice = parse(spec)
    if provider == "none" or not text.strip():
        return 0.0
    data = _audio(provider, voice, text.strip())
    with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as f:
        f.write(data)
        raw = f.name
    try:
        ffmpeg("-i", raw, "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", out_wav)
    finally:
        os.unlink(raw)
    return media_seconds(out_wav)
