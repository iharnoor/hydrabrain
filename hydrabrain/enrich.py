"""Enrichment — derive a summary, tags, and entities for a piece of content.

HydraDB extracts the graph natively on infer=True; this adds the human-facing
enrichment layer via the configured LLM (Claude Haiku by default, Gemini fallback).
"""

from __future__ import annotations

import json

from . import config


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
    if not config.have_llm():
        return {"summary": "", "tags": [], "entities": [],
                "_error": "No LLM key — add ANTHROPIC_API_KEY or GEMINI_API_KEY"}

    from . import llm
    raw = llm.generate(_PROMPT.format(content=text[:8000]), model=model)

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
