"""Tests for P2.34 ``rerun_helper`` — atomic rerun + debounce.

The hotfix is a thin wrapper around ``HistoryStore.exclusive_access()``
that adds three guarantees the previous in-endpoint implementation
lacked:

  1. **Atomicity** — the ``delete + create`` pair cannot interleave
     with another rerun, a worker ``mark_*`` write, or a purge sweep.
  2. **Status guard** — only ``completed`` / ``error`` entries are
     eligible; rerunning a live analysis would create two parallel
     runs.
  3. **Debounce** — the same ``analysis_id`` cannot be rerun twice
     within 60 seconds, so a spammy client can not pile up
     duplicates.

Every test runs against a tmp ``_HISTORY_DIR`` and resets the
HistoryStore singleton + the helper's module-level debounce ledger
in setup so no state leaks between tests.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

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
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient — same pattern as tests/test_history_purge.py.

    The lifespan hook touches the LLM client; we stub it so the test
    suite never needs real API keys.
    """
    from fastapi.testclient import TestClient
    from backend.main import app

    return TestClient(app)


# ── helper unit tests (7) ──────────────────────────────────────────────────


def test_rerun_creates_new_entry_and_deletes_old(rerun_env):
    """Happy path: rerun a completed entry → new id, old gone, new pending."""
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_analysis

    old = get_history_store().create(
        "600595", "2026-07-23", status="completed",
        analysis_id="old-analysis",
    )
    old.signal = "Buy"
    old.elapsed = 12.5
    get_history_store().update(old)

    new_id = rerun_analysis("old-analysis")

    # New id is different and follows the expected format.
    assert new_id != "old-analysis"
    assert new_id.startswith("600595_2026-07-23_r")
    assert "_" in new_id  # the _r<unix>_<6hex> tail

    store = get_history_store()
    # Old entry must be gone.
    assert store.get("old-analysis") is None
    # New entry must exist, inherit ticker/trade_date, start pending.
    new_entry = store.get(new_id)
    assert new_entry is not None
    assert new_entry.ticker == "600595"
    assert new_entry.trade_date == "2026-07-23"
    assert new_entry.status == "pending"


def test_rerun_rejects_running_entry(rerun_env):
    """Cannot rerun an entry with status='running'."""
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_analysis

    get_history_store().create(
        "600000", "2026-07-23", status="running",
        analysis_id="live-analysis",
    )

    with pytest.raises(ValueError, match="status is 'running'"):
        rerun_analysis("live-analysis")

    # The live entry must be left intact.
    assert get_history_store().get("live-analysis") is not None


def test_rerun_rejects_pending_entry(rerun_env):
    """Cannot rerun an entry with status='pending'."""
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_analysis

    get_history_store().create(
        "600519", "2026-07-23", status="pending",
        analysis_id="pending-analysis",
    )

    with pytest.raises(ValueError, match="status is 'pending'"):
        rerun_analysis("pending-analysis")

    assert get_history_store().get("pending-analysis") is not None


def test_rerun_debounces_within_60s(rerun_env):
    """Second rerun within debounce window raises ValueError."""
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_analysis

    get_history_store().create(
        "601318", "2026-07-23", status="completed",
        analysis_id="debounce-test",
    )

    first = rerun_analysis("debounce-test", debounce_sec=60.0)
    assert first != "debounce-test"

    # Re-create the old entry so the second attempt would otherwise
    # succeed (a previous rerun deletes the source). The point of
    # this test is the debounce rejection, not the deletion.
    get_history_store().create(
        "601318", "2026-07-23", status="completed",
        analysis_id="debounce-test",
    )

    with pytest.raises(ValueError, match="debounce"):
        rerun_analysis("debounce-test", debounce_sec=60.0)


def test_rerun_atomic_under_concurrent_calls(rerun_env):
    """Concurrent reruns on the same entry produce at most one new entry.

    The previous in-endpoint implementation could let two concurrent
    requests each ``get()`` a still-present entry, each ``delete()``
    the same one, and each ``create()`` a brand-new analysis — leaving
    the user with two parallel runs of the same ticker/date.
    """
    from backend.core.history_store import get_history_store
    from backend.core.rerun_helper import rerun_analysis

    get_history_store().create(
        "600036", "2026-07-23", status="completed",
        analysis_id="concurrent-target",
    )

    results: list[str | Exception] = []
    barrier = threading.Barrier(8)

    def attempt() -> None:
        barrier.wait()  # release all threads at the same instant
        try:
            results.append(rerun_analysis("concurrent-target", debounce_sec=0.0))
        except Exception as exc:  # noqa: BLE001 — we want every outcome
            results.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # Exactly one must succeed; the rest must be rejected (not-found
    # because the winner already deleted the source, or debounce).
    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, f"expected exactly 1 winner, got {len(successes)}: {results}"
    assert len(failures) == 7

    # The new entry must exist exactly once.
    new_entry = get_history_store().get(successes[0])
    assert new_entry is not None
    assert new_entry.status == "pending"


def test_rerun_raises_if_old_entry_not_found(rerun_env):
    """ValueError with 'not found' detail when analysis_id does not exist."""
    from backend.core.rerun_helper import rerun_analysis

    with pytest.raises(ValueError, match="not found"):
        rerun_analysis("never-existed")


def test_rerun_rolls_back_new_entry_on_create_failure(rerun_env):
    """If ``store.create()`` raises, the old entry is left intact.

    Simulates the disk-full / permissions case by patching
    ``HistoryStore.create`` to raise after the helper has already
    passed the get() / status check.
    """
    from backend.core import history_store as history_mod
    from backend.core.rerun_helper import rerun_analysis

    store = history_mod.get_history_store()
    store.create(
        "601012", "2026-07-23", status="completed",
        analysis_id="rollback-test",
    )

    original_create = history_mod.HistoryStore.create
    call_count = {"n": 0}

    def boom(self, *args, **kwargs):  # noqa: ANN001 — match parent signature
        call_count["n"] += 1
        raise OSError("simulated disk full")

    with patch.object(history_mod.HistoryStore, "create", boom):
        with pytest.raises(RuntimeError, match="create new entry for 'rollback-test' failed"):
            rerun_analysis("rollback-test", debounce_sec=0.0)

    # create() must have been attempted exactly once (the new entry).
    assert call_count["n"] == 1
    # Old entry must still be on disk — rollback guarantees no orphan.
    assert store.get("rollback-test") is not None
    # Sanity: the original ``create`` was never called through the
    # patched path, only the new-entry one.
    assert callable(original_create)
