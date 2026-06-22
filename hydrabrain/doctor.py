"""Health checks — mirrors gbrain doctor."""
from __future__ import annotations


def run(engine) -> list[dict]:
    from . import config

    checks: list[dict] = []

    def chk(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. HydraDB key
    chk("hydradb_key", bool(config.HYDRADB_API_KEY),
        "set" if config.HYDRADB_API_KEY else "missing — run `hydrabrain init`")

    # 2. LLM key (Claude preferred, Gemini fallback)
    from . import llm as _llm
    provider = _llm.active_provider()
    llm_ok = provider != "none"
    detail = {
        "claude": f"Anthropic key set — using {config.ANTHROPIC_CHAT_MODEL}",
        "gemini": f"Gemini key set — using {config.GEMINI_CHAT_MODEL}",
        "none": "no LLM key — think/enrich degraded. Set ANTHROPIC_API_KEY or GEMINI_API_KEY",
    }[provider]
    chk("llm_key", llm_ok, detail)

    # 3. API connectivity + memory count
    try:
        status = engine.status()
        count = status.get("memories", 0)
        chk("api_connectivity", True,
            f"tenant={status['tenant']} memories={count}")
        chk("memory_count", count > 0,
            f"{count} memories" if count > 0
            else "0 memories — run `hydrabrain capture` or `hydrabrain sync`")
    except Exception as e:
        chk("api_connectivity", False, str(e)[:200])

    # 4. MCP server importable
    try:
        from . import mcp_server as _  # noqa: F401
        chk("mcp_server", True, "importable — `hydrabrain serve` ready")
    except Exception as e:
        chk("mcp_server", False, str(e)[:200])

    # 5. Cron jobs registered
    try:
        from . import cron
        jobs = cron.list_jobs()
        chk("cron_jobs", True,
            f"{len(jobs)} scheduled job(s)" if jobs else "none scheduled — `hydrabrain cron add` to set up auto-sync")
    except Exception as e:
        chk("cron_jobs", False, str(e)[:120])

    return checks


def print_report(checks: list[dict]) -> int:
    """Print a human-readable report. Returns 1 if any check failed, else 0."""
    width = max(len(c["check"]) for c in checks) + 2
    failures = 0
    for c in checks:
        icon = "✓" if c["ok"] else "✗"
        print(f"  {icon}  {c['check']:<{width}}  {c['detail']}")
        if not c["ok"]:
            failures += 1
    return failures
