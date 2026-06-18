"""Reports / briefing — a synthesized overview of what's in the brain.

Mirrors gbrain's briefing/reports capability: instead of answering one question,
produce a digest. With a topic, it retrieves the most relevant memories and writes
a briefing on that topic; without one, it samples recent memories and writes an
overview of what the brain currently knows. Built entirely on top of HydraDB recall
+ the existing synthesis layer.
"""

from __future__ import annotations

from .client import Chunk
from .synth import Answer, synthesize


def _row_text(row: dict) -> str:
    for k in ("text", "content", "memory", "chunk_content", "summary"):
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def briefing(engine, topic: str | None = None, k: int = 12) -> Answer:
    """Return a synthesized briefing Answer. `engine` is a BrainEngine."""
    if topic:
        chunks = engine.search(topic, k=k)
        question = (f"Write a briefing on '{topic}' from these memories: what do I know, "
                    f"what are the key points, and what's still unclear?")
        return synthesize(question, chunks)

    # No topic: sample what's stored and summarize the brain's overall contents.
    rows = engine.client.list_all(kind="memory", sub_tenant_id=engine.source_id)[:k]
    chunks = [Chunk(text=_row_text(r), source_id=str(r.get("memory_id", "")))
              for r in rows if _row_text(r)]
    if not chunks:
        return Answer(text="The brain has no memories to brief on yet.", gaps="everything")
    question = ("Give me a briefing on what this personal brain currently contains: "
                "the main themes, notable entities, and what kinds of things I've saved.")
    return synthesize(question, chunks)
