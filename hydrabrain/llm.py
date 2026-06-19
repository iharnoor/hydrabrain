"""Shared Gemini client — with a hard per-request timeout.

Why this exists: google-genai's default client has no hard timeout, so a single
hung request can stall a whole run indefinitely (a LongMemEval run once wedged on
an open Gemini socket for ~10 hours). Every Gemini call in hydrabrain + the
benchmarks goes through `client()` so the timeout is enforced in exactly one place.
"""

from __future__ import annotations

import os

from . import config

# Hard cap per request (ms). A hung call errors here instead of blocking forever.
TIMEOUT_MS = int(os.getenv("HYDRABRAIN_LLM_TIMEOUT_MS", "90000"))

_cached = None


def client(api_key: str | None = None, cached: bool = True):
    """Return a Gemini client with a hard request timeout. Cached by default."""
    global _cached
    if cached and _cached is not None:
        return _cached
    from google import genai
    from google.genai import types

    c = genai.Client(
        api_key=api_key or config.require("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    if cached:
        _cached = c
    return c
