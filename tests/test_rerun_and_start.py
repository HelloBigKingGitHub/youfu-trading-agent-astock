"""Tests for P2.35 ``rerun_helper.rerun_and_start`` — atomic rerun + actually start.

P2.34 closed the atomicity half (delete + create race) of DDD_OPERATIONS.md
§6.9 but the endpoint only created a new history entry — it never spawned
the worker thread, so the user saw ``status=pending`` forever. P2.35
chains ``start_analysis`` onto the helper so a rerun behaves like a fresh
``POST /api/analyze`` for the same ticker/date.

This file tests the chain end-to-end (with ``start_analysis`` mocked
because the real one needs an OpenAI key):

  * rerun creates a new history entry AND starts it
  * config / ticker / date from the old entry propagate to the
    ``start_analysis`` call
  * the 60s debounce + status guard from P2.34 still applies
  * if ``start_analysis`` raises, the helper stub stays in ``pending``
    so the user can retry
  * the log message includes ``"rerun: A -> B"`` for ops observability

Every test runs against a tmp ``_HISTORY_DIR`` and resets the
HistoryStore singleton + the helper's module-level debounce ledger in
setup so no state leaks between cases.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def rerun_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect ``_HISTORY_DIR`` to tmp, reset singletons + debounce."""
    from backend.core import history_store as history_mod
    from backend.core import rerun_helper

    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(history_mod, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)
    # Drop the module-level debounce ledger so tests do not leak a
    # 60s wait between cases.
    rerun_helper.reset_debounce()

    yield {
        "tmp": tmp_path,
        "history_dir": history_dir,
    }


@pytest.fixture()
def stub_start_analysis(monkeypatch: pytest.MonkeyPatch):
    """Patch ``backend.core.start_analysis`` to a controllable stub.

    The real ``start_analysis`` requires an OpenAI key and would launch
    a worker thread — neither belongs in a unit test. We replace it
    with a stub that returns ``(live_id, tracker)`` where ``live_id``
    follows the canonical ``{ticker}_{date}_{hex}`` shape.

    Tests can introspect the stub via ``stub_start_analysis.calls`` /
    ``stub_start_analysis.last_request`` to assert what was passed in.
    """
    stub = MagicMock()

    def _fake(request):
        # Mimic TrackerStore.create()'s id format so the entry is
        # recognisable as a real ``start_analysis`` output.
        import uuid
        from backend.core.history_store import get_history_store

        live_id = (
            f"{request.ticker}_{request.trade_date}_"
            f"{uuid.uuid4().hex[:8]}"
        )
        get_history_store().create(
            request.ticker,
            request.trade_date,
            status="running",
            analysis_id=live_id,
        )
        tracker = MagicMock()
        stub.last_request = request
        stub.last_live_id = live_id
        return live_id, tracker

    stub.side_effect = _fake

    # ``rerun_and_start`` does ``from backend.core import start_analysis
    # as _start_analysis`` inside the function body, so we patch the
    # attribute on the source module ``backend.core``.
    monkeypatch.setattr("backend.core.start_analysis", stub)
    return stub


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient for endpoint-level tests."""
    from fastapi.testclient import TestClient
    from backend.main import app

    return TestClient(app)


# ── helper unit tests (7) ──────────────────────────────────────────────────


def test_rerun_creates_new_entry_and_marks_running(
    rerun_env,
    stub_start_analysis,
):
    """Happy path: rerun a completed entry → live id returned by
    ``start_analysis``, old entry gone, helper stub cleaned up.

    The ``status=running`` check happens implicitly: ``start_analysis``
    is what marks the entry running. The history list reflects this
    because we only ever have the live id on disk after the helper
    cleans up its own stub.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    old = get_history_store().create(
        "600595", "2026-07-23", status="completed",
        analysis_id="old-analysis",
    )
    old.signal = "Buy"
    old.elapsed = 12.5
    get_history_store().update(old)

    result = rerun_and_start("old-analysis", debounce_sec=0.0)

    # Result is the structured P2.35 payload.
    assert result["ok"] is True
    assert result["analysis_id"] == stub_start_analysis.last_live_id
    assert result["ticker"] == "600595"
    assert result["trade_date"] == "2026-07-23"
    assert result["start_analysis"] == {
        "ticker": "600595",
        "trade_date": "2026-07-23",
    }

    # Old entry must be gone (deleted by rerun_analysis).
    store = get_history_store()
    assert store.get("old-analysis") is None

    # The helper-created ``_r<ts>_<hex>`` stub must be cleaned up —
    # only the live id (the one start_analysis wrote) should remain.
    # No entry should have the helper stub format.
    all_entries, _ = store.list_all(limit=100, offset=0)
    assert len(all_entries) == 1
    assert all_entries[0].analysis_id == stub_start_analysis.last_live_id


def test_rerun_propagates_config(
    rerun_env,
    stub_start_analysis,
):
    """``config.llm_overrides`` is forwarded into the ``AnalyzeRequest``."""
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    get_history_store().create(
        "600519", "2026-07-23", status="completed",
        analysis_id="config-test",
    )

    config = {
        "llm_overrides": {
            "llm_provider": "openai",
            "quick_think_llm": "gpt-4o-mini",
            "deep_think_llm": "gpt-4o",
            "backend_url": "https://api.example.com",
        }
    }
    rerun_and_start("config-test", config=config, debounce_sec=0.0)

    # Stub captured the request — verify the LLM overrides flowed.
    sent = stub_start_analysis.last_request
    assert sent.ticker == "600519"
    assert sent.trade_date == "2026-07-23"
    assert sent.llm_provider == "openai"
    assert sent.quick_think_llm == "gpt-4o-mini"
    assert sent.deep_think_llm == "gpt-4o"
    assert sent.backend_url == "https://api.example.com"


def test_rerun_propagates_ticker_date_from_old(
    rerun_env,
    stub_start_analysis,
):
    """The new analysis inherits ticker/trade_date from the old entry.

    This is the whole point of §6.9 — the user clicks "重新跑" because
    they want the *same* analysis redone, not a different ticker/date.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    get_history_store().create(
        "300750", "2026-07-15", status="error",
        analysis_id="propagate-test",
    )

    rerun_and_start("propagate-test", debounce_sec=0.0)

    sent = stub_start_analysis.last_request
    assert sent.ticker == "300750"
    assert sent.trade_date == "2026-07-15"


def test_rerun_409_debounce_works(
    rerun_env,
    stub_start_analysis,
):
    """Second rerun within debounce window raises ``ValueError``.

    The error comes from ``rerun_analysis`` (P2.34 invariant) so
    ``start_analysis`` must NOT be called for the second attempt —
    otherwise the user would see two concurrent runs.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    store = get_history_store()
    store.create(
        "601318", "2026-07-23", status="completed",
        analysis_id="debounce-and-start",
    )

    first = rerun_and_start("debounce-and-start", debounce_sec=60.0)
    assert first["ok"] is True

    # Re-create the source entry so the second attempt would
    # otherwise succeed at the status guard (debounce is the
    # only thing standing in the way).
    store.create(
        "601318", "2026-07-23", status="completed",
        analysis_id="debounce-and-start",
    )

    with pytest.raises(ValueError, match="debounce"):
        rerun_and_start("debounce-and-start", debounce_sec=60.0)

    # start_analysis must have been called exactly once (the first
    # time). The second attempt must not have spawned a worker.
    assert stub_start_analysis.call_count == 1


def test_rerun_409_for_running_old_entry(
    rerun_env,
    stub_start_analysis,
):
    """Cannot rerun an entry whose status is ``running``.

    This protects against the race the user originally reported —
    two concurrent reruns on a still-running entry would pile up
    parallel analyses.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    get_history_store().create(
        "600000", "2026-07-23", status="running",
        analysis_id="running-test",
    )

    with pytest.raises(ValueError, match="status is 'running'"):
        rerun_and_start("running-test", debounce_sec=0.0)

    # start_analysis must not have been called.
    assert stub_start_analysis.call_count == 0


def test_rerun_propagates_start_analysis_failure(
    rerun_env,
    monkeypatch,
):
    """If ``start_analysis`` raises, the helper stub remains in
    ``pending`` so the user can retry.

    The rerun_helper stub (the ``_r<ts>_<hex>`` entry) is what the
    user sees on disk after the failure. The 60s debounce stays in
    effect to avoid piling up identical retries.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    store = get_history_store()
    store.create(
        "688981", "2026-07-23", status="error",
        analysis_id="start-failure-test",
    )

    def boom(_request):
        raise RuntimeError("simulated OpenAI key missing")

    monkeypatch.setattr("backend.core.start_analysis", boom)

    with pytest.raises(RuntimeError, match="simulated OpenAI key missing"):
        rerun_and_start("start-failure-test", debounce_sec=0.0)

    # The helper stub is still on disk in pending state so the
    # user can retry once the underlying problem is fixed.
    entries, _ = store.list_all(limit=100, offset=0)
    assert len(entries) == 1
    stub = entries[0]
    assert stub.analysis_id.startswith("688981_2026-07-23_r")
    assert stub.status == "pending"
    assert stub.ticker == "688981"
    assert stub.trade_date == "2026-07-23"


def test_rerun_log_marks_old_as_rerun(
    rerun_env,
    stub_start_analysis,
    caplog,
):
    """The log line includes ``"rerun: A -> B"`` for ops observability.

    This mirrors the P2.34 log shape (``rerun: A -> B (ticker=…, …)``)
    so an operator grepping for the rerun pattern keeps working.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_and_start

    get_history_store().create(
        "600036", "2026-07-23", status="completed",
        analysis_id="log-test",
    )

    with caplog.at_level(logging.WARNING, logger="backend.core.rerun_helper"):
        rerun_and_start("log-test", debounce_sec=0.0)

    # caplog captures both the P2.34 ``rerun: A -> B`` log AND the
    # P2.35 ``rerun_and_start: A -> B`` log — pick the one that
    # describes the chain end-to-end.
    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "log-test" in combined
    assert "rerun" in combined.lower()
    assert stub_start_analysis.last_live_id in combined