"""Offline unit tests for the benchmark harness (bench/) and hydrabrain client.

These commit the inline sanity suite run during the fair-relational-harness ship.
Strictly offline: no network, no API keys — HydraDB / Gemini / Anthropic are
never called (clients are mocked or only their pure/early-return paths hit).

Run with either:
    python3 -m pytest tests/test_bench_harness.py -q
    python3 tests/test_bench_harness.py            # plain runner, no pytest needed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bench.gbrain_stack import (  # noqa: E402
    CHUNK_MAX_CHARS, CHUNK_OVERLAP_WORDS, CHUNK_WORDS, chunk_text,
)
from bench.hydra_wait import (  # noqa: E402
    wait_for_indexing, wait_for_retrievable, wipe_namespace,
)
from bench.longmemeval import (  # noqa: E402
    _best_session, build_units, is_evidence, judge, session_to_text,
)
from bench.lme_scale import generate_answer, judge_answer  # noqa: E402
from hydrabrain.client import Chunk, HydraDBClient  # noqa: E402


# ── chunk_text invariants ──────────────────────────────────────────

def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_text_short_passthrough():
    text = "one small session that fits in a single chunk"
    assert chunk_text(text) == [text]


def test_chunk_text_window_size_and_overlap():
    words = [f"w{i}" for i in range(1000)]
    chunks = chunk_text(" ".join(words))
    step = CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    assert len(chunks) > 1
    for i, c in enumerate(chunks[:-1]):
        assert len(c.split()) == CHUNK_WORDS, f"chunk {i} wrong size"
    # Consecutive chunks share exactly CHUNK_OVERLAP_WORDS words.
    for a, b in zip(chunks, chunks[1:]):
        assert a.split()[step:] == b.split()[:CHUNK_OVERLAP_WORDS]


def test_chunk_text_lossless():
    words = [f"tok{i}" for i in range(777)]
    chunks = chunk_text(" ".join(words))
    covered = set()
    for c in chunks:
        covered.update(c.split())
    assert covered == set(words)


def test_chunk_text_char_cap():
    # A pathological 20K-char "word" must be split; no chunk may exceed the cap.
    text = "x" * 20_000 + " tail words here"
    chunks = chunk_text(text)
    assert all(len(c) <= CHUNK_MAX_CHARS for c in chunks)
    assert len(chunks) >= 3


# ── hydra_wait: wait_for_indexing ──────────────────────────────────

class _CountClient:
    def __init__(self, counts):
        self.counts = list(counts)
        self.calls = 0

    def count(self, sub_tenant_id=""):
        self.calls += 1
        if not self.counts:
            raise RuntimeError("boom")
        v = self.counts[0]
        if len(self.counts) > 1:
            self.counts.pop(0)
        if isinstance(v, Exception):
            raise v
        return v


def test_wait_for_indexing_settles():
    c = _CountClient([2, 5, 5, 5])
    got = wait_for_indexing(c, min_count=5, timeout=5, poll=0.01, stable_checks=2)
    assert got == 5
    assert c.calls >= 3  # needed at least count + 2 stable confirmations


def test_wait_for_indexing_timeout_returns_last_seen():
    c = _CountClient([2])  # stuck below min_count forever
    got = wait_for_indexing(c, min_count=5, timeout=0.1, poll=0.02)
    assert got == 2  # proceeds with what it saw, does not raise


def test_wait_for_indexing_count_exception_is_tolerated():
    c = _CountClient([RuntimeError("api down")])
    got = wait_for_indexing(c, min_count=1, timeout=0.1, poll=0.02)
    assert got == 0  # falls back, never raises


# ── hydra_wait: wait_for_retrievable ───────────────────────────────

class _RecallClient:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)

    def recall_preferences(self, query, sub_tenant_id="", **kw):
        v = self.result_sets[0]
        if len(self.result_sets) > 1:
            self.result_sets.pop(0)
        if isinstance(v, Exception):
            raise v
        return v


def _chunks(*texts):
    return [Chunk(text=t) for t in texts]


def test_wait_for_retrievable_returns_stable_set():
    stable = _chunks("alpha", "beta")
    c = _RecallClient([[], _chunks("alpha"), stable, stable])
    got = wait_for_retrievable(c, "q", "ns", {}, timeout=5, poll=0.01)
    assert [x.text for x in got] == ["alpha", "beta"]


def test_wait_for_retrievable_timeout_returns_last():
    # Never stabilizes: every poll returns a different set.
    c = _RecallClient([_chunks(f"v{i}") for i in range(50)])
    got = wait_for_retrievable(c, "q", "ns", {}, timeout=0.05, poll=0.01)
    assert len(got) == 1  # last observed set, not an exception


def test_wait_for_retrievable_recall_exception_yields_empty():
    c = _RecallClient([RuntimeError("503")])
    got = wait_for_retrievable(c, "q", "ns", {}, timeout=0.05, poll=0.01)
    assert got == []


# ── hydra_wait: wipe_namespace ─────────────────────────────────────

class _WipeClient:
    def __init__(self, rows, delete_ok=True):
        self.rows = {"memory": list(rows), "knowledge": []}
        self.delete_ok = delete_ok
        self.delete_calls = []

    def list_all(self, kind="memory", sub_tenant_id=""):
        return list(self.rows[kind])

    def delete_memory(self, memory_id, sub_tenant_id=""):
        self.delete_calls.append((memory_id, sub_tenant_id))
        if self.delete_ok:
            self.rows["memory"] = [r for r in self.rows["memory"]
                                   if r.get("memory_id") != memory_id]
            return {"success": True}
        return {"success": False}  # the silent-no-op API behavior


def test_wipe_namespace_deletes_all_and_passes_sub_tenant():
    c = _WipeClient([{"memory_id": "m1"}, {"memory_id": "m2"}])
    removed = wipe_namespace(c, "ns1", max_rounds=3)
    assert removed == 2
    assert c.rows["memory"] == []
    # Regression guard for the silent-no-op bug: every delete carries the ns.
    assert all(st == "ns1" for _, st in c.delete_calls)


def test_wipe_namespace_raises_on_survivors():
    c = _WipeClient([{"memory_id": "m1"}], delete_ok=False)
    try:
        wipe_namespace(c, "ns1", max_rounds=2)
    except RuntimeError as e:
        assert "polluted" in str(e)
    else:
        raise AssertionError("expected RuntimeError for surviving rows")


# ── hydrabrain client: delete_memory sub_tenant_id fix ─────────────

class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True}


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def delete(self, url, params=None, timeout=None):
        self.urls.append(url)
        self.params = params
        return _FakeResp()


def _mock_client():
    c = HydraDBClient(api_key="test-key").use_tenant("t1")
    c._session = _FakeSession()
    return c


def test_delete_memory_appends_sub_tenant_id():
    c = _mock_client()
    c.delete_memory("mem123", sub_tenant_id="nsX")
    # params= (not f-string interpolation) so requests percent-encodes ids —
    # an id containing &/=/# cannot smuggle or truncate query parameters.
    assert c._session.params == {"tenant_id": "t1", "memory_id": "mem123",
                                 "sub_tenant_id": "nsX"}


def test_delete_memory_omits_empty_sub_tenant_id():
    c = _mock_client()
    c.delete_memory("mem123")
    assert "sub_tenant_id" not in c._session.params


# ── longmemeval helpers ────────────────────────────────────────────

def test_session_to_text_and_build_units():
    q = {
        "haystack_sessions": [[{"role": "user", "content": " hi "},
                               {"role": "assistant", "content": "hello"}],
                              [{"content": "no role key"}]],
        "haystack_dates": ["2025/05/20 (Tue)"],
        "haystack_session_ids": ["s1"],
    }
    units = build_units(q)
    assert [sid for sid, _ in units] == ["s1", "sess_1"]  # fallback id + date
    assert units[0][1] == "[session date: 2025/05/20 (Tue)]\nuser: hi\nassistant: hello"
    assert units[1][1].startswith("[session date: unknown]\nuser: no role key")
    assert session_to_text("d", []) == "[session date: d]"


def test_is_evidence():
    assert is_evidence(["a", "b"], ["b", "z"]) is True
    assert is_evidence(["a"], ["z"]) is False
    assert is_evidence(["a"], []) is False
    assert is_evidence([], ["a"]) is False


def test_best_session_maps_chunk_by_overlap():
    units = [("s1", "the quick brown fox jumps over the lazy dog " * 20),
             ("s2", "completely different content about databases and graphs " * 20)]
    chunk = "different content about databases and graphs completely " * 3
    assert _best_session(chunk, units) == "s2"
    assert _best_session("zzz no overlap anywhere qqq", units) == ""


def test_judge_abstention_branch_offline():
    # abstain=True never calls the LLM — pure string check.
    assert judge("q", "gold", "I don't know the answer.", "t", True, "model") is True
    assert judge("q", "gold", "There is no information about that.", "t", True, "model") is True
    assert judge("q", "gold", "The answer is Paris.", "t", True, "model") is False


def test_generate_answer_empty_contexts_short_circuits():
    assert generate_answer([], "any question", "any-model") == "I don't know."


def test_judge_answer_negative_gold_branch_offline():
    assert judge_answer("q", "I don't know", "Sorry, I cannot find that.", "t", "m") is True
    assert judge_answer("q", "Not mentioned", "It was mentioned: blue.", "t", "m") is False


# ── committed results receipt schema ───────────────────────────────

def test_longmemeval_results_schema():
    path = REPO / "bench" / "longmemeval_results.json"
    if not path.exists():  # receipt not present in this checkout
        return
    data = json.loads(path.read_text())
    summary, rows = data["summary"], data["rows"]
    for key in ("n", "top_k", "judge_model", "base_qa_acc", "base_evidence_recall",
                "hydra_qa_acc", "hydra_evidence_recall", "per_type", "type_mix",
                "baseline_chunked"):
        assert key in summary, f"summary missing {key}"
    assert summary["baseline_chunked"] is True
    assert summary["n"] == len(rows)
    req = {"question_id", "type", "abstain", "hydra_recall", "base_recall",
           "hydra_qa", "base_qa", "hydra_answer", "base_answer"}
    for r in rows:
        assert req <= set(r), f"row missing {req - set(r)}"
    # Aggregates must be recomputable from the rows (no hand-edited numbers).
    n = summary["n"]
    assert abs(summary["hydra_qa_acc"] - sum(r["hydra_qa"] for r in rows) / n) < 1e-9
    assert abs(summary["base_qa_acc"] - sum(r["base_qa"] for r in rows) / n) < 1e-9
    assert abs(summary["hydra_evidence_recall"] - sum(r["hydra_recall"] for r in rows) / n) < 1e-9
    assert abs(summary["base_evidence_recall"] - sum(r["base_recall"] for r in rows) / n) < 1e-9


# ── plain-python runner (pytest not required) ──────────────────────

if __name__ == "__main__":
    failures = 0
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL {name}: {e!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
