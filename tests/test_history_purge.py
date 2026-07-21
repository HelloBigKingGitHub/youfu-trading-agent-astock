"""Tests for ``POST /api/history/purge`` — the bulk "clear all history" action.

P2.30 — adds a destructive endpoint that wipes:
  * analysis history metadata (terminal entries only)
  * per-ticker results dir (full_states_log_*.json)
  * per-task log dirs (~/.tradingagents/logs/{ticker}/{date}_runNN/)
  * cache dir (~/.tradingagents/cache/**) when ``include_cache=true``

Refuses (409) when any analysis is ``pending`` or ``running``, in either
HistoryStore metadata or the in-memory TrackerStore.  Idempotent: re-running
on a clean store returns all zeros.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def purge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect every storage root the purge service touches to tmp_path.

    Mirrors the ``tracker_env`` fixture in ``test_tracker_stage_reports.py``.
    Every disk-bound constant is monkeypatched and every singleton reset so
    the test never touches real ``~/.tradingagents``.
    """
    from backend.core import history_store as history_mod
    from backend.core import tracker as tracker_mod
    import backend.core.history_cleanup as cleanup_mod
    import backend.api.history as history_api

    history_dir = tmp_path / "history"
    results_dir = tmp_path / "logs"
    cache_dir = tmp_path / "cache"

    # 1) HistoryStore: redirect + reset singleton.
    monkeypatch.setattr(history_mod, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_mod, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)

    # 2) TrackerStore: reset singleton.
    monkeypatch.setattr(tracker_mod.TrackerStore, "_instance", None)

    # 3) Cleanup service: redirect cache + results roots.
    monkeypatch.setattr(cleanup_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cleanup_mod, "_RESULTS_DIR", results_dir)

    # 4) API: pin confirmation token so the test stays independent of any
    # future refactor of the literal.
    monkeypatch.setattr(history_api, "REQUIRED_CONFIRMATION", "CLEAR_ALL_HISTORY")

    history_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    yield {
        "tmp": tmp_path,
        "history_dir": history_dir,
        "results_dir": results_dir,
        "cache_dir": cache_dir,
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient — same pattern as tests/test_batch.py:309-317."""
    from fastapi.testclient import TestClient
    from backend.main import app

    # Stub the analysis runner so the FastAPI lifespan hook + future tests
    # don't try to start a real LLM thread. The /purge endpoint itself
    # does not depend on the runner, but the lifespan runs at import time.
    return TestClient(app)


# ── tests ───────────────────────────────────────────────────────────────────


class TestPurgeValidation:
    def test_invalid_confirmation_returns_422(self, client: TestClient, purge_env):
        r = client.post(
            "/api/history/purge",
            json={"confirmation": "WRONG_TOKEN", "include_cache": True},
        )
        assert r.status_code == 422, r.text

    def test_missing_confirmation_returns_422(self, client: TestClient, purge_env):
        r = client.post("/api/history/purge", json={"include_cache": True})
        assert r.status_code == 422, r.text

    def test_invalid_include_cache_type_returns_422(
        self, client: TestClient, purge_env
    ):
        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": "yes"},
        )
        assert r.status_code == 422, r.text


class TestActiveAnalysesBlockPurge:
    def test_pending_metadata_blocks_purge_with_409(self, client, purge_env):
        from backend.core.history_store import get_history_store

        get_history_store().create("600595", "2026-07-18", status="pending")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["reason"] == "active_analyses"
        # The history metadata must still exist.
        assert any(purge_env["history_dir"].glob("*.json"))

    def test_running_metadata_blocks_purge_with_409(self, client, purge_env):
        from backend.core.history_store import get_history_store

        get_history_store().create("600595", "2026-07-18", status="running")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["reason"] == "active_analyses"

    def test_in_memory_tracker_blocks_purge_with_409(self, client, purge_env):
        from backend.core import tracker as tracker_mod

        tracker_mod.TrackerStore.get_instance().create(
            ticker="600595", trade_date="2026-07-18",
        )

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["reason"] == "active_analyses"

    def test_409_does_not_delete_anything(self, client, purge_env):
        from backend.core.history_store import get_history_store

        get_history_store().create("600595", "2026-07-18", status="running")
        # Drop fake results + log + cache to make sure they survive.
        report = (
            purge_env["results_dir"]
            / "600595" / "TradingAgentsStrategy_logs"
            / "full_states_log_2026-07-18.json"
        )
        report.parent.mkdir(parents=True)
        report.write_text("{}")
        run_dir = (
            purge_env["results_dir"] / "600595" / "2026-07-18_run01"
        )
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text("{}")
        cache_file = purge_env["cache_dir"] / "kline" / "600595_1d.csv"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("date,close\n")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 409
        assert report.exists()
        assert (run_dir / "meta.json").exists()
        assert cache_file.exists()
        assert any(purge_env["history_dir"].glob("*.json"))


class TestPurgeWipesAllTargets:
    def _seed_completed(
        self, purge_env, ticker: str, trade_date: str, rid: str,
    ) -> str:
        from backend.core.history_store import get_history_store

        entry = get_history_store().create(
            ticker, trade_date, status="completed", analysis_id=rid,
        )
        # Drop a results file that mirrors the production layout.
        report = (
            purge_env["results_dir"]
            / ticker
            / "TradingAgentsStrategy_logs"
            / f"full_states_log_{trade_date}.json"
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"ticker": ticker, "date": trade_date}))
        # Drop a per-run log dir.
        run_dir = (
            purge_env["results_dir"] / ticker / f"{trade_date}_run01"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(
            json.dumps({"ticker": ticker, "trade_date": trade_date})
        )
        (run_dir / "agent_outputs.jsonl").write_text("{}\n")
        # Drop a cache file.
        cache_file = purge_env["cache_dir"] / f"{ticker}_kline.csv"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("date,close\n")
        return entry.analysis_id

    def test_purges_metadata_reports_log_runs_and_cache(
        self, client: TestClient, purge_env
    ):
        rid = self._seed_completed(
            purge_env, ticker="600595", trade_date="2026-07-18", rid="rid-1",
        )

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["history_deleted"] == 1
        assert body["reports_deleted"] == 1
        assert body["log_runs_deleted"] == 1
        assert body["cache_files_deleted"] >= 1
        assert body["failed_items"] == 0
        assert body["bytes_freed"] > 0

        from backend.core.history_store import get_history_store
        assert get_history_store().get(rid) is None
        # All on-disk artifacts should be gone.
        assert not (
            purge_env["results_dir"]
            / "600595"
            / "TradingAgentsStrategy_logs"
            / "full_states_log_2026-07-18.json"
        ).exists()
        assert not (
            purge_env["results_dir"] / "600595" / "2026-07-18_run01"
        ).exists()
        # Cache root is left in place (just emptied).
        assert purge_env["cache_dir"].is_dir()

    def test_purges_multiple_entries_and_counts_dedup(self, client, purge_env):
        from backend.core.history_store import get_history_store

        hs = get_history_store()
        rid_a = hs.create(
            "600595", "2026-07-18", status="completed",
            analysis_id="rid-A",
        ).analysis_id
        rid_b = hs.create(
            "000001", "2026-07-18", status="error",
            analysis_id="rid-B",
        ).analysis_id

        # Drop one results file that satisfies both entries (legacy
        # full_states_log keyed by ticker+date only).
        shared_report = (
            purge_env["results_dir"]
            / "600595"
            / "TradingAgentsStrategy_logs"
            / "full_states_log_2026-07-18.json"
        )
        shared_report.parent.mkdir(parents=True)
        shared_report.write_text("{}")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Two history entries removed.
        assert body["history_deleted"] == 2
        # The shared file should still count as 1 deletion.
        assert body["reports_deleted"] == 1
        assert hs.get(rid_a) is None
        assert hs.get(rid_b) is None

    def test_include_cache_false_keeps_cache(self, client, purge_env):
        self._seed_completed(
            purge_env, ticker="000001", trade_date="2026-07-18", rid="rid-c",
        )
        cache_file = purge_env["cache_dir"] / "kline" / "000001_1d.csv"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("date,close\n")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cache_files_deleted"] == 0
        assert cache_file.exists()


class TestPurgePreservesUnrelatedDirs:
    def test_preserves_portfolio_watchlist_settings_memory(
        self, client, purge_env
    ):
        # Mirror the production layout for dirs that MUST survive.
        home = purge_env["tmp"].parent  # arbitrary — we use tmp_path
        portfolio = home / "portfolio"
        watchlist = home / "watchlist.json"
        settings = home / "settings.json"
        memory = home / "memory" / "trading_memory.md"
        backup = home / "logs_BACKUP_20260717"

        portfolio.mkdir()
        (portfolio / "positions.json").write_text("{}")
        watchlist.write_text("{}")
        settings.write_text("{}")
        memory.parent.mkdir(parents=True)
        memory.write_text("# memory")
        backup.mkdir()
        (backup / "history.json").write_text("{}")

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 200, r.text

        # Everything we planted outside the purge roots must still exist.
        assert (portfolio / "positions.json").exists()
        assert watchlist.exists()
        assert settings.exists()
        assert memory.exists()
        assert (backup / "history.json").exists()


class TestPurgeIdempotency:
    def test_purging_twice_returns_all_zeros(self, client, purge_env):
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )

        body1 = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        ).json()
        body2 = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        ).json()

        assert body1["ok"] is True
        assert body2["ok"] is True
        # Second call must report zero deletes and zero failures.
        assert body2["history_deleted"] == 0
        assert body2["reports_deleted"] == 0
        assert body2["log_runs_deleted"] == 0
        assert body2["cache_files_deleted"] == 0
        assert body2["bytes_freed"] == 0
        assert body2["failed_items"] == 0


class TestPurgeSafety:
    def test_results_path_outside_purge_roots_is_rejected(
        self, client, purge_env, monkeypatch
    ):
        """If a history entry's ``results_path`` points outside the
        configured purge roots, the service must NOT follow it. This is a
        regression guard for a malicious/buggy path being unlinked.
        """
        from backend.core.history_store import get_history_store
        import backend.core.history_cleanup as cleanup_mod

        # Seed a completed entry whose results_path escapes the purge roots.
        external = purge_env["tmp"] / "outside.txt"
        external.write_text("do not delete")
        rid = "rid-evil"
        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id=rid,
        )
        get_history_store().set_results_path(rid, str(external))

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        )
        assert r.status_code == 200, r.text
        # The file outside the purge roots must still be on disk.
        assert external.exists()

    def test_response_does_not_leak_absolute_paths(self, client, purge_env):
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        ).json()
        # No field may echo the user home / absolute paths back to the
        # client. ``failed_items`` is a count only.
        text = json.dumps(body, ensure_ascii=False)
        assert "tmp_path" not in text
        assert "home" not in text
        assert "/.tradingagents/" not in text


class TestPurgeEdgeCases:
    """Coverage for the defensive branches the happy-path tests don't hit."""

    def test_skips_non_ticker_subdir_under_results_root(self, client, purge_env):
        """The results root may contain non-ticker dirs (legacy ``history``
        subdir, manual ``logs_BACKUP_*`` siblings, code-style snapshots).
        None of those must be touched.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        # Drop unrelated dirs at the results root.
        (purge_env["results_dir"] / "history").mkdir()
        (purge_env["results_dir"] / "history" / "stale.json").write_text("{}")
        backup = purge_env["results_dir"] / "logs_BACKUP_20260717"
        backup.mkdir()
        (backup / "snapshot.json").write_text("{}")
        # Non-numeric / non-6-digit ticker dirs (e.g. a "docs" subdir).
        docs = purge_env["results_dir"] / "docs"
        docs.mkdir()
        (docs / "readme.md").write_text("keep me")

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        ).json()
        assert body["ok"] is True
        # Everything we planted outside the actual purge targets survives.
        assert (purge_env["results_dir"] / "history" / "stale.json").exists()
        assert (backup / "snapshot.json").exists()
        assert (docs / "readme.md").exists()

    def test_unlinks_stray_file_under_ticker_dir(self, client, purge_env):
        """Files that don't match the report/log-run patterns are still
        removed so the purge produces a clean slate.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        stray = purge_env["results_dir"] / "600595" / "leftover.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("bye")

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        ).json()
        assert body["ok"] is True
        assert not stray.exists()

    def test_purges_legacy_nested_report_subdir(self, client, purge_env):
        """Pre-v0.4 layouts had ``TradingAgentsStrategy_logs/by_date/<date>/``
        subdirs. Those must also be wiped.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        nested = (
            purge_env["results_dir"]
            / "600595"
            / "TradingAgentsStrategy_logs"
            / "by_date"
            / "2026-07-18"
        )
        nested.mkdir(parents=True)
        (nested / "legacy.json").write_text("{}")

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        ).json()
        assert body["ok"] is True
        assert not nested.exists()

    def test_unlinks_symlink_under_results_without_following(
        self, client, purge_env
    ):
        """A symlink under a ticker dir must be unlinked, never followed.
        The symlink target (outside the purge root) must survive.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        target = purge_env["tmp"] / "outside_target.txt"
        target.write_text("keep me")
        link = purge_env["results_dir"] / "600595" / "TradingAgentsStrategy_logs"
        link.parent.mkdir(parents=True)
        # Symlink-as-dir is rare but defensible: refuse to descend.
        link.symlink_to(target)

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        ).json()
        assert body["ok"] is True
        assert target.exists(), "symlink target must not be deleted"

    def test_unlinks_symlink_in_cache_without_following(self, client, purge_env):
        """Cache symlinks point at read-only vendors; we unlink the link,
        never the target.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        target = purge_env["tmp"] / "outside_cache.txt"
        target.write_text("keep me")
        (purge_env["cache_dir"] / "kline").mkdir(parents=True)
        (purge_env["cache_dir"] / "kline" / "vendor.csv").symlink_to(target)

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": True},
        ).json()
        assert body["ok"] is True
        assert target.exists(), "symlink target outside cache must survive"

    def test_refuses_to_iterate_forbidden_root(self, client, purge_env):
        """Belt-and-braces: if a buggy caller ever points the purge at
        ``/``, the helper refuses to descend rather than wipe the host.
        """
        from backend.core import history_cleanup as cleanup_mod
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        # Re-point the results dir at "/" — the helper must early-return
        # instead of rmtree-ing everything.
        monkey_results = type(cleanup_mod._RESULTS_DIR)("/")
        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(cleanup_mod, "_RESULTS_DIR", monkey_results)
            body = client.post(
                "/api/history/purge",
                json={
                    "confirmation": "CLEAR_ALL_HISTORY",
                    "include_cache": False,
                },
            ).json()
            assert body["ok"] is True
            # History metadata was still wiped (different root), but no
            # stray files from "/" were unlinked.
            assert body["history_deleted"] >= 1
        finally:
            monkeypatch.undo()

    def test_purge_auto_sweeps_zombie_tracker_with_terminal_metadata(
        self, client, purge_env,
    ):
        """Defensive: a tracker stays ``is_running=True`` in memory but
        the persisted history metadata has already been finalized
        (e.g. ``mark_error`` succeeded before a crash left the tracker
        entry stale). The purge service MUST sweep such stale trackers
        before checking the active set — otherwise the destructive
        action is permanently blocked by a zombie whose thread is gone.

        P2.32 hotfix — the prior "always block" behavior left users
        unable to clear history when an analysis crashed mid-finalize,
        because the in-memory tracker never got cleaned up.
        """
        from backend.core import tracker as tracker_mod
        from backend.core.history_store import get_history_store

        analysis_id, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="600595", trade_date="2026-07-18",
        )
        # Tracker stays running. Flip history status to "error" so the
        # tracker is now "stale" (no live thread, no live history entry
        # in active status) — exactly the user-reported bug.
        get_history_store().mark_error(analysis_id, error="prior crash")

        # Add a terminal sibling so we can prove the wipe still happens.
        get_history_store().create(
            "000001", "2026-07-18", status="completed", analysis_id="rid-completed",
        )

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text

        # The zombie tracker was swept — is_running flipped. The history
        # entry was wiped by the metadata sweep (it had status=error, so
        # it qualified for deletion).
        tracker_store = tracker_mod.TrackerStore.get_instance()
        assert tracker_store.get(analysis_id) is not None
        assert tracker_store.get(analysis_id).is_running is False
        assert get_history_store().get(analysis_id) is None
        assert get_history_store().get("rid-completed") is None

    def test_purge_auto_sweeps_zombie_tracker_with_no_metadata(
        self, client, purge_env,
    ):
        """Orphan tracker — the entry has ``is_running=True`` but no
        persisted history.json at all (e.g. tracker created in memory
        after the metadata write raced with a crash). Sweep must drop
        the tracker so purge can complete.
        """
        from backend.core import tracker as tracker_mod
        from backend.core.tracker import AnalysisTracker
        import uuid

        tracker_store = tracker_mod.TrackerStore.get_instance()
        analysis_id = f"600519_2026-07-18_{uuid.uuid4().hex[:8]}"
        orphan = AnalysisTracker(
            analysis_id=analysis_id, ticker="600519", trade_date="2026-07-18",
            is_running=True,
        )
        with tracker_store._store_lock:
            tracker_store._trackers[analysis_id] = orphan

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        assert tracker_store.get(analysis_id) is None, (
            "orphan tracker should have been swept from memory"
        )

    def test_purge_blocks_when_tracker_and_metadata_both_active(
        self, client, purge_env,
    ):
        """Legitimate live analysis — tracker is_running=True AND metadata
        status=running. Sweep MUST NOT touch it; purge returns 409.
        """
        from backend.core import tracker as tracker_mod

        analysis_id, _ = tracker_mod.TrackerStore.get_instance().create(
            ticker="600595", trade_date="2026-07-18",
        )
        # TrackerStore.create already wrote metadata status=running.

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 409, r.text
        body = r.json()
        assert body["detail"]["reason"] == "active_analyses"
        assert analysis_id in body["detail"]["active_ids"]
        # Tracker must still be running (sweep did NOT touch a live entry).
        assert (
            tracker_mod.TrackerStore.get_instance().get(analysis_id).is_running
            is True
        )

    def test_unlink_failure_increments_failed_items(self, client, purge_env):
        """When ``Path.unlink`` raises OSError the entry is counted in
        ``failed_items`` but the rest of the sweep continues.
        """
        from backend.core.history_store import get_history_store
        import backend.core.history_cleanup as cleanup_mod

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        # Drop a real report file so the unlink path runs at least once.
        report = (
            purge_env["results_dir"]
            / "600595"
            / "TradingAgentsStrategy_logs"
            / "full_states_log_2026-07-18.json"
        )
        report.parent.mkdir(parents=True)
        report.write_text("{}")

        real_unlink = cleanup_mod.Path.unlink
        calls = {"n": 0}

        def flaky_unlink(self, *a, **kw):
            calls["n"] += 1
            # Fail only the first call (history metadata); subsequent
            # unlinks (reports, cache) succeed normally so we can assert
            # the sweep continued past the failure.
            if calls["n"] == 1:
                raise OSError("synthetic failure")
            return real_unlink(self, *a, **kw)

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(cleanup_mod.Path, "unlink", flaky_unlink)
            body = client.post(
                "/api/history/purge",
                json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
            ).json()
            assert body["ok"] is True
            assert body["failed_items"] >= 1
            # The sweep continued past the first failure.
            assert body["reports_deleted"] >= 1
        finally:
            monkeypatch.undo()

    def test_rmtree_failure_increments_failed_items(self, client, purge_env):
        """When ``shutil.rmtree`` raises OSError the run dir is counted in
        ``failed_items`` but the metadata + report wipe still proceeds.
        """
        from backend.core.history_store import get_history_store
        import backend.core.history_cleanup as cleanup_mod

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        run_dir = purge_env["results_dir"] / "600595" / "2026-07-18_run01"
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text("{}")

        import shutil as _shutil
        real_rmtree = cleanup_mod.shutil.rmtree

        def flaky_rmtree(path, *a, **kw):
            if str(path).endswith("2026-07-18_run01"):
                raise OSError("synthetic rmtree failure")
            return real_rmtree(path, *a, **kw)

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(cleanup_mod.shutil, "rmtree", flaky_rmtree)
            body = client.post(
                "/api/history/purge",
                json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
            ).json()
            assert body["ok"] is True
            assert body["failed_items"] >= 1
            assert body["history_deleted"] >= 1
        finally:
            monkeypatch.undo()

    def test_unlinks_symlink_under_history_dir_without_following(
        self, client, purge_env
    ):
        """A symlink planted directly under ``_HISTORY_DIR`` must not be
        followed — unlink only the link.
        """
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        target = purge_env["tmp"] / "outside_history.txt"
        target.write_text("keep me")
        link = purge_env["history_dir"] / "evil.json"
        link.symlink_to(target)

        body = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        ).json()
        assert body["ok"] is True
        assert target.exists(), "symlink target outside history must survive"

    def test_refuses_to_iterate_forbidden_cache_root(self, client, purge_env):
        """If the cache root is somehow re-pointed at ``/``, the helper
        refuses to rmtree the host.
        """
        from backend.core import history_cleanup as cleanup_mod
        from backend.core.history_store import get_history_store

        get_history_store().create(
            "600595", "2026-07-18", status="completed", analysis_id="rid-1",
        )
        sentinel = purge_env["tmp"] / "do_not_delete.txt"
        sentinel.write_text("keep me")

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(cleanup_mod, "_CACHE_DIR", Path("/"))
            body = client.post(
                "/api/history/purge",
                json={
                    "confirmation": "CLEAR_ALL_HISTORY",
                    "include_cache": True,
                },
            ).json()
            assert body["ok"] is True
            # The sweep continued on the history metadata; the forbidden
            # cache root was refused without unlinking the sentinel.
            assert body["history_deleted"] >= 1
            assert body["cache_files_deleted"] == 0
            assert sentinel.exists()
        finally:
            monkeypatch.undo()
