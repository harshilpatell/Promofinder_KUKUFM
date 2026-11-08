"""Replaceable LLM providers.

Every provider implements `complete(prompt_id, prompt) -> (text, usage_dict)`.
Select with env PROMOFINDER_PROVIDER or the --provider flag:

  anthropic  : Anthropic Messages API. ANTHROPIC_API_KEY, PROMOFINDER_MODEL (default claude-sonnet-5-5)
  openai     : any OpenAI-compatible Chat Completions endpoint (OpenAI, Gemini's OpenAI endpoint,
               Groq, OpenRouter, local Ollama). OPENAI_API_KEY, OPENAI_BASE_URL, PROMOFINDER_MODEL
  file       : offline replay. Reads <responses_dir>/<prompt_id>.json written earlier by a live
               provider or by a human/agent. Missing responses are reported, never invented.
  heuristic  : no LLM at all; pipeline switches to the keyword heuristic (clearly labelled).

All live providers also save their raw responses to <responses_dir>, which doubles as a cache:
re-running the same prompt costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


class MissingResponse(Exception):
    def __init__(self, prompt_id):
        super().__init__(prompt_id)
        self.prompt_id = prompt_id


class BaseProvider:
    name = "base"
    model = ""

    def __init__(self, responses_dir: str | Path, prompts_dir: str | Path | None = None):
        self.responses_dir = Path(responses_dir)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir = Path(prompts_dir) if prompts_dir else None
        if self.prompts_dir:
            self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.calls = []  # usage/latency log for cost monitoring

    def _cache_path(self, prompt_id):
        return self.responses_dir / f"{prompt_id}.json"

    def complete(self, prompt_id: str, prompt: str):
        if self.prompts_dir:
            (self.prompts_dir / f"{prompt_id}.prompt.txt").write_text(prompt, encoding="utf-8")
        cp = self._cache_path(prompt_id)
        h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        rec = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else None
        # live providers only reuse a cached answer if it was produced for this exact prompt
        # (same prompt_id with a different show/ZIP => cache miss). Replay ('file') is lenient by design.
        if rec is not None and self.name != "file" and rec.get("prompt_sha") != h:
            rec = None
        if rec is not None:
            self.calls.append({"prompt_id": prompt_id, "cached": True, "prompt_sha": h,
                               "prompt_chars": len(prompt), "latency_s": 0.0,
                               "produced_by": rec.get("produced_by", "unknown")})
            return rec["response_text"], rec.get("usage", {})
        # pacing for free-tier requests-per-minute limits (PROMOFINDER_MIN_INTERVAL_S, default 0)
        gap = float(os.getenv("PROMOFINDER_MIN_INTERVAL_S", "0") or 0)
        last = getattr(self, "_last_call_t", 0.0)
        if gap and time.time() - last < gap:
            time.sleep(gap - (time.time() - last))
        t0 = time.time()
        tries = int(os.getenv("PROMOFINDER_RETRIES", "4"))
        wait = float(os.getenv("PROMOFINDER_RETRY_WAIT_S", "20"))
        for attempt in range(tries + 1):
            try:
                text, usage = self._call(prompt)
                break
            except Exception as ex:  # retry only transient errors (rate limit, overload, timeout)
                msg = f"{type(ex).__name__} {ex}".lower()
                transient = any(k in msg for k in ("429", "rate", "quota", "resource_exhausted", "overloaded",
                                                   "503", "502", "500", "timeout", "timed out", "connection"))
                if not transient or attempt == tries:
                    raise
                time.sleep(wait * (attempt + 1))
        self._last_call_t = time.time()
        dt = time.time() - t0
        rec = {"prompt_id": prompt_id, "prompt_sha": h, "produced_by": f"{self.name}:{self.model}",
               "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "latency_s": round(dt, 2),
               "usage": usage, "response_text": text}
        cp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        self.calls.append({"prompt_id": prompt_id, "cached": False, "prompt_sha": h,
                           "prompt_chars": len(prompt), "latency_s": round(dt, 2), "usage": usage,
                           "produced_by": rec["produced_by"]})
        return text, usage

    def _call(self, prompt):  # pragma: no cover - overridden
        raise NotImplementedError


class FileProvider(BaseProvider):
    name = "file"
    model = "replay"

    def _call(self, prompt):
        raise MissingResponse("")

    def complete(self, prompt_id, prompt):
        try:
            return super().complete(prompt_id, prompt)
        except MissingResponse:
            raise MissingResponse(prompt_id)


def _cfg(config, key, default=None):
    """Explicit config (e.g. from Streamlit secrets) wins; then environment; then default.
    Never mutates os.environ, so concurrent app sessions cannot leak settings into each other."""
    v = (config or {}).get(key)
    if v in (None, ""):
        v = os.getenv(key)
    return default if v in (None, "") else v


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, responses_dir, prompts_dir=None, config=None):
        super().__init__(responses_dir, prompts_dir)
        key = _cfg(config, "ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        import anthropic  # imported lazily so the package is optional
        kw = {"api_key": key}
        if _cfg(config, "ANTHROPIC_BASE_URL"):
            kw["base_url"] = _cfg(config, "ANTHROPIC_BASE_URL")
        self.client = anthropic.Anthropic(**kw)
        self.model = _cfg(config, "PROMOFINDER_MODEL", "claude-sonnet-5-5")
        self.max_tokens = int(_cfg(config, "PROMOFINDER_MAX_TOKENS", "6000"))

    def _call(self, prompt):
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}])  # no sampling params: newer SDK/models reject them
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return text, {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def __init__(self, responses_dir, prompts_dir=None, config=None):
        super().__init__(responses_dir, prompts_dir)
        base = _cfg(config, "OPENAI_BASE_URL")
        key = _cfg(config, "OPENAI_API_KEY")
        if not key and not (base and ("localhost" in base or "127.0.0.1" in base)):
            raise RuntimeError("OPENAI_API_KEY is not configured (only a local base URL may omit it)")
        from openai import OpenAI
        self.client = OpenAI(api_key=key or "not-needed-for-local", base_url=base or None)
        self.model = _cfg(config, "PROMOFINDER_MODEL", "gpt-4o-mini")
        t = _cfg(config, "PROMOFINDER_TEMPERATURE")
        self.temperature = float(t) if t is not None else None  # omitted by default: some models reject it

    def _call(self, prompt):
        kw = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        r = self.client.chat.completions.create(**kw)
        u = getattr(r, "usage", None)
        usage = {"input_tokens": getattr(u, "prompt_tokens", None),
                 "output_tokens": getattr(u, "completion_tokens", None)} if u else {}
        return r.choices[0].message.content or "", usage


def get_provider(name: str, responses_dir, prompts_dir=None, config=None):
    name = (name or _cfg(config, "PROMOFINDER_PROVIDER") or "heuristic").lower()
    if name == "heuristic":
        return None
    if name == "file":
        return FileProvider(responses_dir, prompts_dir)
    cls = {"anthropic": AnthropicProvider, "openai": OpenAICompatProvider}.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider '{name}'. Use anthropic|openai|file|heuristic")
    return cls(responses_dir, prompts_dir, config)


def parse_json(text: str):
    """Extract the first JSON object from a model response (tolerates code fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("no JSON object in response")
    return json.loads(t[s:e + 1])
