"""Provider-agnostic LLM client — Claude, OpenAI, or Gemini.

Priority: ANTHROPIC_API_KEY → OPENAI_API_KEY → GEMINI_API_KEY. All three are
optional; without any key, synthesis degrades gracefully (returns top memory
directly).

None of the provider SDKs (`anthropic`, `openai`) are hard dependencies (see
pyproject.toml's `anthropic` / `openai` extras) — plenty of installs (e.g. an
agent that already has its own LLM access, like a harness calling hydrabrain
as a tool) set a provider's API key without ever installing that provider's
SDK. If a key is present but its package isn't installed, `generate()` logs a
warning and falls through to the next configured provider instead of
crashing the caller with a raw ModuleNotFoundError. `google-genai` (Gemini)
is the one hard dependency, so there's always a working baseline once a
GEMINI_API_KEY is set.

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
_openai_cached = None
_gemini_cached = None


class LLMSDKMissing(RuntimeError):
    """Raised when a provider's API key is set but its SDK package isn't installed."""


# ── Anthropic ──────────────────────────────────────────────────────────────

def _anthropic_client():
    global _anthropic_cached
    if _anthropic_cached is not None:
        return _anthropic_cached
    try:
        import anthropic
    except ImportError as e:
        raise LLMSDKMissing(
            "ANTHROPIC_API_KEY is set but the `anthropic` package isn't installed. "
            "Run `pip install anthropic` (or `pip install hydrabrain[anthropic]`), "
            "or unset ANTHROPIC_API_KEY to use another configured provider."
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


# ── OpenAI ───────────────────────────────────────────────────────────────────

def _openai_client():
    global _openai_cached
    if _openai_cached is not None:
        return _openai_cached
    try:
        import openai
    except ImportError as e:
        raise LLMSDKMissing(
            "OPENAI_API_KEY is set but the `openai` package isn't installed. "
            "Run `pip install openai` (or `pip install hydrabrain[openai]`), "
            "or unset OPENAI_API_KEY to use another configured provider."
        ) from e
    _openai_cached = openai.OpenAI(
        api_key=config.require("OPENAI_API_KEY"),
        timeout=TIMEOUT_MS / 1000,
    )
    return _openai_cached


def _openai_generate(prompt: str, model: str | None = None) -> str:
    c = _openai_client()
    model = model or config.OPENAI_CHAT_MODEL
    resp = c.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or "" if resp.choices else ""


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

# Ordered (have_key_fn, generate_fn, label) — first configured provider wins;
# a provider whose SDK is missing falls through to the next one, logging why.
_PROVIDERS = (
    (config.have_anthropic, _anthropic_generate, "claude"),
    (config.have_openai, _openai_generate, "openai"),
    (config.have_gemini, _gemini_generate, "gemini"),
)


def generate(prompt: str, model: str | None = None) -> str:
    """Generate text from a prompt, trying each configured provider in priority order."""
    tried = []
    for have_key, provider_generate, label in _PROVIDERS:
        if not have_key():
            continue
        tried.append(label)
        try:
            return provider_generate(prompt, model)
        except LLMSDKMissing as e:
            log.warning("%s — trying next configured provider.", e)
            continue
    if tried:
        raise RuntimeError(
            f"All configured LLM provider(s) failed to run ({', '.join(tried)}) — "
            "each had its API key set but its SDK package wasn't installed. "
            "Install at least one of: anthropic, openai. Gemini (google-genai) "
            "ships with hydrabrain, so GEMINI_API_KEY alone always works."
        )
    raise RuntimeError(
        "No LLM key configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY.\n"
        "Run `hydrabrain init` or add the key to ~/.hydrabrain/.env"
    )


def active_provider() -> str:
    """Return the name of whichever provider will be used."""
    for have_key, _generate, label in _PROVIDERS:
        if have_key():
            return label
    return "none"
