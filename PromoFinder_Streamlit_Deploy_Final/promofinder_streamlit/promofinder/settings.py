"""Server-side configuration for the app.

Read from Streamlit secrets (Community Cloud: App settings -> Secrets) or environment variables.
Nothing here is ever entered through the public UI, and os.environ is never modified, so
concurrent visitors cannot change or see each other's settings.
"""
from __future__ import annotations

import os

KEYS = ["PROMOFINDER_PROVIDER", "PROMOFINDER_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "PROMOFINDER_TEMPERATURE", "PROMOFINDER_MAX_TOKENS",
        "PROMOFINDER_ACCESS_CODE", "PROMOFINDER_MAX_LLM_EPISODES", "PROMOFINDER_LOCAL_MODE"]


def load_settings(secrets=None) -> dict:
    """secrets: a mapping such as st.secrets (may be None or raise when no secrets file exists)."""
    cfg = {}
    for k in KEYS:
        v = None
        try:
            if secrets is not None and k in secrets:
                v = secrets[k]
        except Exception:  # st.secrets raises if no secrets.toml exists
            v = None
        if v in (None, ""):
            v = os.getenv(k)
        if v not in (None, ""):
            cfg[k] = str(v)
    prov = cfg.get("PROMOFINDER_PROVIDER", "").lower()
    has_key = (prov == "anthropic" and "ANTHROPIC_API_KEY" in cfg) or \
              (prov == "openai" and ("OPENAI_API_KEY" in cfg or
                                     any(h in cfg.get("OPENAI_BASE_URL", "") for h in ("localhost", "127.0.0.1"))))
    cfg["_llm_configured"] = bool(has_key)
    cfg["_provider"] = prov if has_key else "heuristic"
    cfg["_model"] = cfg.get("PROMOFINDER_MODEL", "claude-sonnet-5-5" if prov == "anthropic" else "gpt-4o-mini") if has_key else ""
    cfg["_local_mode"] = cfg.get("PROMOFINDER_LOCAL_MODE", "0").lower() in ("1", "true", "yes")
    cfg["_max_llm_episodes"] = int(cfg.get("PROMOFINDER_MAX_LLM_EPISODES", "60"))
    return cfg


def public_summary(cfg: dict) -> str:
    """Safe-to-display description (never includes keys)."""
    if not cfg.get("_llm_configured"):
        return "No LLM configured on this server: heuristic mode and the saved-response demo only."
    return f"LLM configured on the server: {cfg['_provider']} · model {cfg['_model']}"
