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

    # 2. LLM key (Claude → OpenAI → Gemini, first configured+installed wins)
    # Mirrors hydrabrain.llm's provider priority. sdk_module is None for Gemini
    # since google-genai is a hard dependency — always importable.
    _PROVIDER_CHECKS = (
        ("claude", config.have_anthropic, "anthropic", "pip install anthropic",
         f"Anthropic key set — using {config.ANTHROPIC_CHAT_MODEL}"),
        ("openai", config.have_openai, "openai", "pip install openai",
         f"OpenAI key set — using {config.OPENAI_CHAT_MODEL}"),
        ("gemini", config.have_gemini, None, None,
         f"Gemini key set — using {config.GEMINI_CHAT_MODEL}"),
    )
    configured = [p for p in _PROVIDER_CHECKS if p[1]()]
    if not configured:
        chk("llm_key", False,
            "no LLM key — think/enrich degraded. "
            "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY")
    else:
        runnable = None
        skipped = []
        for label, _have, sdk_module, install_hint, ok_detail in configured:
            if sdk_module is None:
                runnable = (label, ok_detail)
                break
            try:
                __import__(sdk_module)
                runnable = (label, ok_detail)
                break
            except ImportError:
                skipped.append((label, sdk_module, install_hint))
        if runnable:
            label, ok_detail = runnable
            detail = ok_detail
            if skipped:
                skipped_desc = ", ".join(f"{lbl} (`{mod}` not installed)" for lbl, mod, _ in skipped)
                detail += f". Skipped: {skipped_desc}"
            chk("llm_key", True, detail)
        else:
            hints = " / ".join(f"`{hint}`" for _, _, hint in skipped)
            chk("llm_key", False,
                f"key(s) set for {', '.join(lbl for lbl, _, _ in skipped)} but SDK(s) not "
                f"installed, and no Gemini key to fall back to. Run {hints}.")

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
