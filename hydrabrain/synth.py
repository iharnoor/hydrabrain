"""Synthesis layer — turn retrieved chunks into a cited prose answer with gaps.

This mirrors gbrain's `think` capability: instead of returning a raw list of
pages, we synthesize a grounded answer, attach inline [n] citations, and
explicitly flag what the corpus could NOT answer (gap analysis). Gemini is used
purely as the writer/grounding layer; all facts come from HydraDB retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from google import genai

from . import config
from .client import Chunk


@dataclass
class Answer:
    text: str
    citations: list[Chunk] = field(default_factory=list)
    gaps: str = ""

    def render(self) -> str:
        out = [self.text.strip()]
        if self.gaps:
            out.append(f"\n**Gaps:** {self.gaps.strip()}")
        if self.citations:
            out.append("\n**Sources:**")
            for i, c in enumerate(self.citations, 1):
                snippet = c.text.strip().replace("\n", " ")
                out.append(f"  [{i}] {snippet[:160]}")
        return "\n".join(out)


def _genai() -> genai.Client:
    from . import llm
    return llm.client()  # cached, with a hard request timeout


_SYNTH_PROMPT = """You are the synthesis layer of a personal memory engine. The user asked a \
question and a retrieval system returned the memory chunks below (ranked). \

Write a grounded answer using ONLY facts present in these chunks. Rules:
- Cite every claim with inline [n] referring to the chunk number.
- Be concise and direct. Lead with the answer.
- If the chunks do not contain enough information, say so plainly rather than guessing.
- After the answer, on a new line beginning with "GAPS:", state in one sentence what \
the memory could not answer (or "GAPS: none").

Question: {question}

Memory chunks:
{context}
"""


def synthesize(question: str, chunks: list[Chunk], model: str | None = None) -> Answer:
    if not chunks:
        return Answer(text="I have no memories relevant to that yet.", gaps="entire question")

    # Free mode: no Gemini key → skip synthesis, return the top matching memories
    # directly so capture/search/read are fully usable without a paid/LLM key.
    if not config.have_gemini():
        top = chunks[0].text.strip().replace("\n", " ")
        return Answer(
            text=(f"Here's the most relevant memory I found [1]:\n\n{top[:400]}\n\n"
                  "_(Add a Gemini key via `hydrabrain init` to get synthesized, cited answers.)_"),
            citations=chunks,
            gaps="",
        )

    context = "\n\n".join(
        f"[{i}] {c.text.strip()}" for i, c in enumerate(chunks, 1)
    )
    resp = _genai().models.generate_content(
        model=model or config.GEMINI_CHAT_MODEL,
        contents=_SYNTH_PROMPT.format(question=question, context=context),
    )
    text = (resp.text or "").strip()

    gaps = ""
    if "GAPS:" in text:
        body, _, gap_part = text.partition("GAPS:")
        text = body.strip()
        gaps = gap_part.strip()
        if gaps.lower() == "none":
            gaps = ""
    return Answer(text=text, citations=chunks, gaps=gaps)
