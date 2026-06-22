"""Configuration + secret loading for hydrabrain.

Key resolution order (first hit wins per var, via python-dotenv `override=False`):
  1. process environment (already-exported vars)
  2. ./.env                     (repo-local, for development)
  3. ~/.hydrabrain/.env         (user-level — where onboarding writes keys)
  4. a legacy sibling path      (back-compat on the original dev machine; a no-op elsewhere)

Onboarding (`hydrabrain init` / the web setup screen) writes #3, so a fresh
machine becomes turnkey without anyone hand-editing a dotfile.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

USER_ENV = Path.home() / ".hydrabrain" / ".env"

_ENV_CANDIDATES = [
    Path(__file__).resolve().parent.parent / ".env",   # repo-root .env
    USER_ENV,                                          # user-level ~/.hydrabrain/.env
]


def _load_env() -> None:
    if load_dotenv is None:
        return
    for path in _ENV_CANDIDATES:
        if path.exists():
            load_dotenv(path, override=False)


def reload() -> None:
    """Re-read the .env files and refresh module-level keys (after onboarding writes them)."""
    global HYDRADB_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY
    if load_dotenv is not None:
        for path in _ENV_CANDIDATES:
            if path.exists():
                load_dotenv(path, override=True)
    HYDRADB_API_KEY = os.getenv("HYDRADB_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


_load_env()

HYDRADB_API_KEY = os.getenv("HYDRADB_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# A HydraDB free plan is capped at one tenant; reuse it everywhere.
DEFAULT_TENANT = os.getenv("HYDRABRAIN_TENANT", "test1")

# Source = which repo inside the brain (gbrain's second axis). Maps to HydraDB's
# sub_tenant_id namespace. "" is the host/default source. Resolution order in the
# engine: explicit arg → HYDRABRAIN_SOURCE env → "" (host).
DEFAULT_SOURCE = os.getenv("HYDRABRAIN_SOURCE", "")

# HydraDB recall tuning. alpha weights dense vs BM25; mode "thinking" does deeper
# graph traversal. Defaults chosen empirically (see bench/) — alpha=0.8 starves
# the keyword signal on entity/date queries.
HYDRA_RECALL_MODE = os.getenv("HYDRA_RECALL_MODE", "thinking")
HYDRA_RECALL_ALPHA = float(os.getenv("HYDRA_RECALL_ALPHA", "1.0"))

# Models
GEMINI_CHAT_MODEL = os.getenv("HYDRABRAIN_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_EMBED_MODEL = os.getenv("HYDRABRAIN_EMBED_MODEL", "gemini-embedding-001")
ANTHROPIC_CHAT_MODEL = os.getenv("HYDRABRAIN_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Where to get free keys (shown in onboarding "free mode").
HYDRADB_SIGNUP_URL = "https://hydradb.com"
GEMINI_SIGNUP_URL = "https://aistudio.google.com/apikey"


def have_hydradb() -> bool:
    return bool(os.getenv("HYDRADB_API_KEY", ""))


def have_gemini() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", ""))


def have_anthropic() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", ""))


def have_llm() -> bool:
    """True if any synthesis backend is available."""
    return have_anthropic() or have_gemini()


def needs_onboarding() -> bool:
    """True until the one hard requirement — a HydraDB key — is present."""
    return not have_hydradb()


def write_keys(hydradb_key: str | None = None, gemini_key: str | None = None) -> Path:
    """Persist keys to ~/.hydrabrain/.env (merging with any existing values) and reload."""
    existing: dict[str, str] = {}
    if USER_ENV.exists():
        for line in USER_ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    if hydradb_key:
        existing["HYDRADB_API_KEY"] = hydradb_key.strip()
    if gemini_key:
        existing["GEMINI_API_KEY"] = gemini_key.strip()
    USER_ENV.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in existing.items())
    USER_ENV.write_text(body)
    try:
        USER_ENV.chmod(0o600)  # contains secrets
    except Exception:
        pass
    # make the new keys live in this process immediately
    for k, v in existing.items():
        os.environ[k] = v
    reload()
    return USER_ENV


def require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        raise RuntimeError(
            f"Missing required env var {key}. Run `hydrabrain init` (or `hydrabrain web`) "
            f"to set it up, or add it to {USER_ENV}."
        )
    return val
