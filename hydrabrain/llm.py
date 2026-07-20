"""Provider-agnostic LLM client — Claude (preferred) or Gemini fallback.

Priority: ANTHROPIC_API_KEY → GEMINI_API_KEY. Both are optional; without
either key, synthesis degrades gracefully (returns top memory directly).

The `anthropic` PyPI package is NOT a hard dependency (see pyproject.toml's
`anthropic` extra) — plenty of installs (e.g. an agent that already has its
own Claude access, like a harness calling hydrabrain as a tool) set
ANTHROPIC_API_KEY without ever installing the SDK. If the key is present but
the package isn't installed, `generate()` logs a warning and falls back to
Gemini instead of crashing the caller with a raw ModuleNotFoundError.

Every synthesis call in hydrabrain routes through `generate()` so the
provider switch is in exactly one place.
"""

from __future__ import annotations

import logging
import os

from . import config

log = logging.getLogger(__name__)

TIMEOUT_MS = int(os.getenv("HYDRABRAIN_LLM_TIMEOUT_MS", "90000"))

_anthropic_cached = None
_gemini_cached = None


class AnthropicSDKMissing(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is set but the `anthropic` package isn't installed."""


# ── Anthropic ──────────────────────────────────────────────────────────────

def _anthropic_client():
    global _anthropic_cached
    if _anthropic_cached is not None:
        return _anthropic_cached
    try:
        import anthropic
    except ImportError as e:
        raise AnthropicSDKMissing(
            "ANTHROPIC_API_KEY is set but the `anthropic` package isn't installed. "
            "Run `pip install anthropic` (or `pip install hydrabrain[anthropic]`), "
            "or unset ANTHROPIC_API_KEY to use GEMINI_API_KEY instead."
        ) from e
    _anthropic_cached = anthropic.Anthropic(
        api_key=config.require("ANTHROPIC_API_KEY"),
        timeout=TIMEOUT_MS / 1000,
    )
    return _anthropic_cached


def _anthropic_generate(prompt: str, model: str | None = None) -> str:
    c = _anthropic_client()
    model = model or config.ANTHROPIC_CHAT_MODEL
    msg = c.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text if msg.content else ""


# ── Gemini ─────────────────────────────────────────────────────────────────

def client(api_key: str | None = None, cached: bool = True):
    """Return a cached Gemini client (kept for bench/ compatibility)."""
    global _gemini_cached
    if cached and _gemini_cached is not None:
        return _gemini_cached
    from google import genai
    from google.genai import types

    c = genai.Client(
        api_key=api_key or config.require("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    if cached:
        _gemini_cached = c
    return c


def _gemini_generate(prompt: str, model: str | None = None) -> str:
    c = client()
    resp = c.models.generate_content(
        model=model or config.GEMINI_CHAT_MODEL,
        contents=prompt,
    )
    return (resp.text or "").strip()


# ── Public interface ────────────────────────────────────────────────────────

def generate(prompt: str, model: str | None = None) -> str:
    """Generate text from a prompt. Uses Claude if available, else Gemini."""
    if config.have_anthropic():
        try:
            return _anthropic_generate(prompt, model)
        except AnthropicSDKMissing as e:
            if config.have_gemini():
                log.warning("%s — falling back to Gemini for this call.", e)
                return _gemini_generate(prompt, model)
            raise
    if config.have_gemini():
        return _gemini_generate(prompt, model)
    raise RuntimeError(
        "No LLM key configured. Set ANTHROPIC_API_KEY or GEMINI_API_KEY.\n"
        "Run `hydrabrain init` or add the key to ~/.hydrabrain/.env"
    )


def active_provider() -> str:
    """Return the name of whichever provider will be used."""
    if config.have_anthropic():
        return "claude"
    if config.have_gemini():
        return "gemini"
    return "none"
