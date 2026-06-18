"""Configuration + secret loading for hydrabrain.

Looks for a local .env first, then falls back to the sibling HydraDB project's
.env so the tool works out of the box on this machine.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

_ENV_CANDIDATES = [
    Path(__file__).resolve().parent.parent / ".env",
    Path("/Users/harnoorsingh/Developer/HydraDB/.env"),
]


def _load_env() -> None:
    if load_dotenv is None:
        return
    for path in _ENV_CANDIDATES:
        if path.exists():
            load_dotenv(path, override=False)


_load_env()

HYDRADB_API_KEY = os.getenv("HYDRADB_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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


def require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        raise RuntimeError(
            f"Missing required env var {key}. Add it to .env "
            f"(checked: {', '.join(str(p) for p in _ENV_CANDIDATES)})."
        )
    return val
