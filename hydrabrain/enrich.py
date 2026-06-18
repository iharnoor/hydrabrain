"""Enrichment — derive a summary, tags, and entities for a piece of content.

gbrain enriches ingested content (summaries, auto-tags, entity extraction) on top
of raw storage. HydraDB already extracts the *graph* natively on `infer=True`; this
adds the human-facing enrichment layer (a one-line summary + topical tags) using
Gemini purely as the writer. Returns plain data; callers decide whether to store it.
"""

from __future__ import annotations

import json

from . import config
from .synth import _genai  # reuse one cached genai client (robust across calls)


_PROMPT = """Enrich this piece of content for a personal knowledge base. Return STRICT JSON \
with exactly these keys:
  "summary": one concise sentence capturing the essence,
  "tags": 3-7 lowercase topical tags (array of strings),
  "entities": notable people/places/orgs/products mentioned (array of strings).
No prose, no markdown fences — JSON only.

Content:
{content}
"""


def enrich(text: str, model: str | None = None) -> dict:
    if not text.strip():
        return {"summary": "", "tags": [], "entities": []}
    resp = _genai().models.generate_content(
        model=model or config.GEMINI_CHAT_MODEL,
        contents=_PROMPT.format(content=text[:8000]),
    )
    raw = (resp.text or "").strip()
    # Tolerate accidental ```json fences.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        data = json.loads(raw)
    except Exception:
        return {"summary": raw[:200], "tags": [], "entities": [], "_unparsed": True}
    return {
        "summary": str(data.get("summary", "")).strip(),
        "tags": [str(t).strip() for t in data.get("tags", []) if str(t).strip()],
        "entities": [str(e).strip() for e in data.get("entities", []) if str(e).strip()],
    }
