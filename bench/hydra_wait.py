"""Active wait for HydraDB's async indexing — replaces blind time.sleep().

HydraDB's `add_memory(infer=True)` returns before the background graph wiring /
chunk indexing finishes. A fixed sleep either wastes wall-clock (too long) or
silently under-measures HydraDB (too short — retrieval misses content that was
the only thing in its namespace). Instead, poll the namespace's visible row
count until it (a) reaches the number of memories we ingested and (b) stops
changing across consecutive polls, with a hard timeout as the safety net.
"""

from __future__ import annotations

import time


def wait_for_indexing(client, sub_tenant_id: str = "", min_count: int = 1,
                      timeout: float = 180, poll: float = 5,
                      stable_checks: int = 2) -> int:
    """Block until the (tenant, sub_tenant) namespace looks fully indexed.

    Done when count() >= min_count AND the count is unchanged for
    `stable_checks` consecutive polls (HydraDB re-chunks, so the count can
    exceed min_count — stability, not equality, is the signal that background
    work settled). Returns the final observed count; on timeout returns
    whatever was last seen so the caller can proceed/log rather than crash.
    """
    deadline = time.time() + timeout
    last, streak, count = -1, 0, 0
    while time.time() < deadline:
        try:
            count = client.count(sub_tenant_id=sub_tenant_id)
        except Exception:
            # A failed poll is NOT an observation — echoing the previous count
            # would satisfy count == last and fake a stability streak.
            streak = 0
            time.sleep(poll)
            continue
        if count >= min_count and count == last:
            streak += 1
            if streak >= stable_checks:
                return count
        else:
            streak = 0
        last = count
        time.sleep(poll)
    return count


def wait_for_retrievable(client, query: str, sub_tenant_id: str,
                         recall_kwargs: dict, timeout: float = 180,
                         poll: float = 8):
    """Block until the namespace's search index has actually settled.

    Row-count stability (wait_for_indexing) is necessary but NOT sufficient:
    HydraDB shows raw rows in list_content as soon as they are stored, while
    embedding/graph indexing continues in the background — a query in that
    window silently misses content that a later identical query returns.
    (Observed: 17/52 evidence 'misses' in a benchmark run all flipped to hits
    when re-queried after settling.)

    So poll the REAL query until the result set is non-empty and identical
    across two consecutive polls (recall is deterministic once settled), and
    return those chunks for the caller to use directly. On timeout, returns
    the last result set.
    """
    deadline = time.time() + timeout
    prev, chunks = None, []
    while True:
        try:
            chunks = client.recall_preferences(query, sub_tenant_id=sub_tenant_id,
                                               **recall_kwargs)
        except Exception:
            chunks = []
        sig = tuple(c.text for c in chunks)
        if chunks and sig == prev:
            return chunks
        prev = sig
        if time.time() >= deadline:
            return chunks
        time.sleep(poll)


def wipe_namespace(client, sub_tenant_id: str, max_rounds: int = 20) -> int:
    """Delete every row in one (tenant, sub_tenant) namespace.

    Guards against cross-run pollution: different benchmark harnesses reuse
    LongMemEval question_ids as sub_tenant ids on the same tenant, so a prior
    run's haystack (e.g. lme_scale's ~48 distractor sessions from the _s
    split) silently becomes part of this run's corpus. Wipe before ingest.
    """
    removed = 0
    for kind in ("memory", "knowledge"):
        for _ in range(max_rounds):
            rows = client.list_all(kind=kind, sub_tenant_id=sub_tenant_id)
            if not rows:
                break
            for r in rows:
                rid = r.get("memory_id") or r.get("source_id") or ""
                if rid:
                    try:
                        # sub_tenant_id is required — without it the API
                        # soft-fails ({"success": false}) and deletes nothing.
                        resp = client.delete_memory(rid, sub_tenant_id=sub_tenant_id)
                        removed += bool(resp.get("success") or resp.get("user_memory_deleted"))
                    except Exception:
                        pass
            time.sleep(1)
    leftover = sum(len(client.list_all(kind=k, sub_tenant_id=sub_tenant_id))
                   for k in ("memory", "knowledge"))
    if leftover:
        raise RuntimeError(f"wipe_namespace({sub_tenant_id}): {leftover} rows survived "
                           f"{max_rounds} delete rounds — refusing to continue on a "
                           f"polluted namespace")
    return removed
