"""hydrabrain MCP server (stdio).

Exposes the brain to Claude Code / Cursor / Claude Desktop as MCP tools, the same
way gbrain does. Backed entirely by HydraDB.

Register in Claude Code with:
  claude mcp add hydrabrain -- python3 -m hydrabrain.cli serve
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .engine import BrainEngine

_engine: BrainEngine | None = None


def _eng() -> BrainEngine:
    global _engine
    if _engine is None:
        _engine = BrainEngine()
    return _engine


def build_server(tenant_id: str | None = None, source_id: str | None = None) -> FastMCP:
    global _engine
    if tenant_id or source_id:
        _engine = BrainEngine(tenant_id=tenant_id, source_id=source_id)

    mcp = FastMCP("hydrabrain")

    @mcp.tool()
    def capture(text: str, title: str = "") -> str:
        """Store a thought or a piece of consumed content (article, video note, idea) into memory."""
        _eng().capture(text, title=title)
        return "captured"

    @mcp.tool()
    def read_url(url: str) -> str:
        """Ingest a web article or YouTube video (by URL) into memory; HydraDB wires the graph."""
        import json
        return json.dumps(_eng().ingest_url(url))

    @mcp.tool()
    def search(query: str, k: int = 5) -> str:
        """Hybrid vector+graph+BM25 retrieval. Returns the top-k raw memory chunks."""
        chunks = _eng().search(query, k=k)
        if not chunks:
            return "(no results)"
        return "\n\n".join(f"[{i}] {c.text}" for i, c in enumerate(chunks, 1))

    @mcp.tool()
    def think(query: str, k: int = 6) -> str:
        """Answer a question from memory with a synthesized, cited answer and explicit gap analysis."""
        return _eng().think(query, k=k).render()

    @mcp.tool()
    def briefing(topic: str = "", k: int = 12) -> str:
        """Produce a synthesized briefing/report over memory, optionally scoped to a topic."""
        return _eng().briefing(topic=topic or None, k=k).render()

    @mcp.tool()
    def enrich(text: str) -> str:
        """Derive a one-line summary, topical tags, and entities for a piece of content."""
        import json
        return json.dumps(_eng().enrich(text))

    @mcp.tool()
    def graph(source_id: str) -> str:
        """Explore the self-wired knowledge graph around a given source/memory id."""
        import json

        return json.dumps(_eng().graph(source_id))[:4000]

    @mcp.tool()
    def status() -> str:
        """Show the current tenant/source and number of stored memories."""
        import json

        return json.dumps(_eng().status())

    return mcp


def main(tenant_id: str | None = None, source_id: str | None = None):
    build_server(tenant_id, source_id).run()


if __name__ == "__main__":
    main()
