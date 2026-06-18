"""Onboarding — get a fresh install to a working state with zero dotfile editing.

Two entry points share this logic:
  • the web setup screen (webapp.py serves it when keys are missing)
  • `hydrabrain init` (cli.py) for headless / SSH

The one hard requirement is a HydraDB key (storage + retrieval). A Gemini key is
optional: it unlocks synthesized, cited answers (`think`/`enrich`/`briefing`).
Without it you can still capture, sync, read URLs, and search — that's "free mode".
"""

from __future__ import annotations

from . import config


def validate_hydradb(key: str) -> tuple[bool, str]:
    """Live-check a HydraDB key with a cheap, timeout-bounded call."""
    key = (key or "").strip()
    if not key:
        return False, "HydraDB key is required."
    try:
        from .client import HydraDBClient
        HydraDBClient(api_key=key).list_tenants()  # client has (connect, read) timeouts
        return True, "ok"
    except Exception as e:
        return False, f"could not reach HydraDB with that key: {type(e).__name__}"


def validate_gemini(key: str) -> tuple[bool, str]:
    """Format-only check (no live call — keeps onboarding fast and unhangable)."""
    key = (key or "").strip()
    if not key:
        return True, "skipped (free mode — no synthesized answers until added)"
    if len(key) < 20:
        return False, "that doesn't look like a Gemini API key."
    return True, "ok"


def apply(hydradb_key: str, gemini_key: str = "", *, validate: bool = True) -> dict:
    """Validate (optionally) + persist keys. Returns a result dict for UI/CLI to render."""
    if validate:
        ok, msg = validate_hydradb(hydradb_key)
        if not ok:
            return {"ok": False, "field": "hydradb", "message": msg}
        ok, msg = validate_gemini(gemini_key)
        if not ok:
            return {"ok": False, "field": "gemini", "message": msg}
    path = config.write_keys(hydradb_key=hydradb_key, gemini_key=gemini_key or None)
    return {"ok": True, "path": str(path), "gemini": config.have_gemini()}
