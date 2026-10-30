"""Any OpenAI-compatible chat endpoint (OpenAI, Ollama's /v1, LM Studio, vLLM, an Odysseus gateway, ...).

SITE_VIDEO_LLM_URL   base URL ending in /v1 (default http://127.0.0.1:11434/v1, a local Ollama)
SITE_VIDEO_LLM_MODEL model name (default qwen3:8b)
SITE_VIDEO_LLM_KEY   bearer key, if the endpoint needs one
"""

import json
import os
import re
import urllib.request


def settings():
    return {"url": os.environ.get("SITE_VIDEO_LLM_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
            "model": os.environ.get("SITE_VIDEO_LLM_MODEL", "qwen3:8b"),
            "key": os.environ.get("SITE_VIDEO_LLM_KEY", "")}


_models = {"at": 0.0, "ids": []}


def models() -> list:
    """The endpoint's model ids (GET /models), cached for 5 minutes; empty if it does not list them."""
    import time
    if time.time() - _models["at"] < 300:
        return _models["ids"]
    s = settings()
    headers = {"Authorization": "Bearer " + s["key"]} if s["key"] else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(s["url"] + "/models", headers=headers), timeout=10) as r:
            ids = [m["id"] for m in json.load(r).get("data", []) if m.get("id")]
    except Exception:
        ids = []
    _models.update(at=time.time(), ids=ids)
    return ids


def chat(system: str, user: str, max_tokens: int = 12000, timeout: int = 900, model: str = "") -> str:
    """The model's answer. A thinking model can spend the whole budget thinking and answer nothing: then it is
    asked once more with twice the budget."""
    s = settings()
    headers = {"Content-Type": "application/json"}
    if s["key"]:
        headers["Authorization"] = "Bearer " + s["key"]
    for budget in (max_tokens, max_tokens * 2):
        body = {"model": model or s["model"], "max_tokens": budget, "temperature": 0.4, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request(s["url"] + "/chat/completions", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
        choice = out["choices"][0]
        text = re.sub(r"<think>.*?</think>", "", choice["message"].get("content") or "", flags=re.S).strip()
        if text or choice.get("finish_reason") != "length":
            return text
    raise RuntimeError(f"{out.get('model') or body['model']} used all {budget} tokens thinking and gave no answer; "
                       "pick a smaller or non-thinking script model")


def json_from(text: str):
    """The first JSON object in a model's reply (it may wrap it in a code fence or add words around it)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)
