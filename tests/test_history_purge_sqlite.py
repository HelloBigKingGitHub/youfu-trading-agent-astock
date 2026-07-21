"""P2.31 hotfix tests — ``purge_history`` also clears the SQLite sidecar.

After Phase 4 cut the read path to ``READ_FROM_SQLITE=1`` the
``DualReadHistoryStore`` reads straight from
``~/.tradingagents/tradingagents.db``.  The pre-Phase-4 purge cleared
only the JSON layer, so a wipe that "succeeded" still left 17 rows in
the SQLite ``history`` table — ``/api/history`` continued to return
them.

These tests seed the SQLite sidecar explicitly (no dependency on the
running ``DualWriteHistoryStore``) and assert the post-purge counts
are zero on both layers.  They also cover the new zombie-runtime
sweep and the "SQLite unavailable" graceful-degradation path.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def purge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect JSON history dir + cache + results to ``tmp_path``.

    Mirrors the ``purge_env`` fixture in ``test_history_purge.py`` so the
    FastAPI lifespan doesn't try to write to ``~/.tradingagents``.  The
    SQLite sidecar gets its own per-test path inside ``tmp_path`` —
    the helper accepts ``db_path`` explicitly, so we monkeypatch the
    ``sqlite_helper`` factory rather than the sidecar's default
    ``_DEFAULT_DB``.
    """
    from backend.core import history_store as history_mod
    from backend.core import tracker as tracker_mod
    import backend.core.history_cleanup as cleanup_mod
    import backend.api.history as history_api

    history_dir = tmp_path / "history"
    results_dir = tmp_path / "logs"
    cache_dir = tmp_path / "cache"
    sqlite_db = tmp_path / "tradingagents.db"

    monkeypatch.setattr(history_mod, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_mod, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)
    monkeypatch.setattr(tracker_mod.TrackerStore, "_instance", None)
    monkeypatch.setattr(cleanup_mod, "_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cleanup_mod, "_RESULTS_DIR", results_dir)
    monkeypatch.setattr(history_api, "REQUIRED_CONFIRMATION", "CLEAR_ALL_HISTORY")

    history_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    yield {
        "tmp": tmp_path,
        "history_dir": history_dir,
        "results_dir": results_dir,
        "cache_dir": cache_dir,
        "sqlite_db": sqlite_db,
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient — same as ``test_history_purge.py``."""
    from fastapi.testclient import TestClient
    from backend.main import app

    return TestClient(app)


@pytest.fixture()
def patch_sqlite_factory(purge_env, monkeypatch: pytest.MonkeyPatch):
    """Make ``sqlite_helper.get_sqlite_history_store_or_none`` return a
    store rooted at the per-test ``tmp_path/tradingagents.db`` instead
    of ``~/.tradingagents/tradingagents.db``.

    The factory takes ``db_path`` as an optional argument; we return a
    factory-bound-to-this-test that closes nothing (the per-test
    teardown will rely on the migration's own close path).  We also
    pre-create the sidecar via the migration so the schema exists
    before any test seed.
    """
    from backend.core import sqlite_helper

    db_path = purge_env["sqlite_db"]

    def factory(db_path_arg=None):  # type: ignore[no-untyped-def]
        from backend.core.history_store_sqlite import SQLiteHistoryStore

        return SQLiteHistoryStore(db_path or db_path_arg)

    monkeypatch.setattr(sqlite_helper, "get_sqlite_history_store_or_none", factory)
    return db_path


def _seed_sqlite_history(db_path: Path, n: int = 5) -> list[str]:
    """Insert ``n`` terminal history rows directly into the sidecar.

    Bypasses the dual-write wrapper so we can verify the *bulk-delete*
    helper works regardless of which writer created the rows.  Uses the
    same connection the helper would open so WAL mode is shared.
    """
    from backend.core.history_store_sqlite import SQLiteHistoryStore

    store = SQLiteHistoryStore(db_path)
    ids: list[str] = []
    try:
        for i in range(n):
            entry = store.create(
                ticker=f"{600000 + i}",
                trade_date="2026-07-21",
                status="completed",
                analysis_id=f"sqlite-row-{i}",
            )
            store.mark_complete(
                entry.analysis_id,
                signal="Buy",
                elapsed=10.0 + i,
                completed_stages=["market", "social"],
            )
            ids.append(entry.analysis_id)
    finally:
        store.close()
    return ids


def _seed_sqlite_log_chunks(db_path: Path, analysis_id: str, n: int = 3) -> None:
    """Append ``n`` log_chunks rows for a given analysis_id."""
    from backend.core.history_store_sqlite import SQLiteHistoryStore

    store = SQLiteHistoryStore(db_path)
    try:
        # We need the analysis_id to exist in history first.
        cur = store._conn.cursor()
        for i in range(n):
            cur.execute(
                "INSERT INTO log_chunks "
                "(analysis_id, task_dir_name, ts, type, agent, content) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    analysis_id,
                    f"2026-07-21_run0{i+1}",
                    time.time() - (n - i),
                    "llm",
                    "market_analyst",
                    f"chunk {i}",
                ),
            )
        store._conn.commit()
    finally:
        store.close()


def _count_rows(db_path: Path, table: str) -> int:
    """Plain ``SELECT COUNT(*) FROM <table>`` via a fresh connection.

    We deliberately do not reuse the helper's connection — the bulk
    delete closes its own transaction at the end, and we want to count
    *after* the purge has fully released the WAL writer.
    """
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


# ── tests ───────────────────────────────────────────────────────────────────


class TestPurgeClearsSqliteHistory:
    def test_purge_clears_sqlite_history(self, client: TestClient, purge_env, patch_sqlite_factory):
        """Seed 5 history rows in SQLite, run ``purge_history`` (with no
        active analyses), and assert the SQLite ``history`` table is
        empty.  The post-purge ``/api/history`` response must report
        ``history_deleted`` includes both JSON and SQLite rows.
        """
        sqlite_ids = _seed_sqlite_history(purge_env["sqlite_db"], n=5)
        # Seed a matching JSON row so the API tally has something to
        # count from the JSON layer too — proves the two layers are
        # reconciled (5 SQLite rows + 1 JSON row = 6 total).
        from backend.core.history_store import get_history_store
        get_history_store().create(
            "000001", "2026-07-21", status="completed", analysis_id="json-row-1",
        )

        assert _count_rows(purge_env["sqlite_db"], "history") == 5

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 5 from SQLite + 1 from JSON = 6.
        assert body["history_deleted"] == 6, body
        assert body["failed_items"] == 0
        # SQLite must now be empty.
        assert _count_rows(purge_env["sqlite_db"], "history") == 0
        # JSON dir must also be empty.
        assert not any(purge_env["history_dir"].glob("*.json"))
        # And the seeded analysis_ids must all be gone from SQLite.
        for aid in sqlite_ids:
            assert _count_rows(
                purge_env["sqlite_db"], "history",  # noqa: ARG005 — unused
            ) == 0  # redup, see count above
        # Sanity: the sidecar still exists — purge is destructive, not
        # destructive-of-the-schema.
        assert purge_env["sqlite_db"].exists()


class TestPurgeClearsSqliteLogChunks:
    def test_purge_clears_sqlite_log_chunks(
        self, client: TestClient, purge_env, patch_sqlite_factory,
    ):
        """Seed history + log_chunks in SQLite; assert log_chunks is
        empty after ``purge_history``.  Mirrors the per-run-dir wipe on
        the JSONL side — Phase 4 dual-write semantics require both
        layers to be cleared.
        """
        sqlite_ids = _seed_sqlite_history(purge_env["sqlite_db"], n=2)
        for aid in sqlite_ids:
            _seed_sqlite_log_chunks(purge_env["sqlite_db"], aid, n=4)
        assert _count_rows(purge_env["sqlite_db"], "log_chunks") == 8

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # The bulk delete fires the parent ``history`` delete first;
        # SQLite's FK ON DELETE CASCADE therefore wipes the 8
        # ``log_chunks`` rows for free.  We don't assert on
        # ``log_runs_deleted`` — that tally counts the explicit
        # ``bulk_delete_all_log_chunks`` call which finds 0 rows after
        # the cascade already wiped them.  What matters is the
        # post-condition: every sidecar table is empty.
        assert body["history_deleted"] >= 2, body
        assert _count_rows(purge_env["sqlite_db"], "log_chunks") == 0
        # stage_reports + completed_stages are wiped via the same FK cascade.
        assert _count_rows(purge_env["sqlite_db"], "stage_reports") == 0
        assert _count_rows(purge_env["sqlite_db"], "completed_stages") == 0
        assert _count_rows(purge_env["sqlite_db"], "history") == 0


class TestZombieMarkThenPurge:
    def test_zombie_mark_then_purge(
        self, client: TestClient, purge_env, patch_sqlite_factory,
    ):
        """Plant a JSON-history zombie (status=running, elapsed=0,
        started_at 2h ago).  The first ``purge_history`` call must:
          1. Sweep zombies via ``scan_and_mark_zombies``.
          2. Find no remaining active analyses (the zombie was just
             marked ``error``).
          3. Wipe the JSON + SQLite layers.
        Without the runtime sweep the purge would 409 instead.
        """
        from backend.core.history_store import get_history_store

        store = get_history_store()
        # Status=running + elapsed=0 + started_at 2h ago > ZOMBIE_TTL_SEC (10m).
        long_ago = time.time() - 7200.0
        # HistoryStore.create always sets started_at to now() so we
        # have to flip it via a manual rewrite; that's fine — the
        # zombie signature is what matters for the sweep.
        entry = store.create(
            "600595", "2026-07-21", status="running",
            analysis_id="zombie-bbca7f78",
        )
        # Force ``elapsed=0`` and ``started_at=long_ago`` on disk so the
        # sweep recognises it as a zombie.
        path = purge_env["history_dir"] / f"{entry.analysis_id}.json"
        raw = path.read_text(encoding="utf-8")
        import json as _json
        d = _json.loads(raw)
        d["elapsed"] = 0.0
        d["started_at"] = long_ago
        path.write_text(_json.dumps(d), encoding="utf-8")

        # Also plant the same zombie in the SQLite sidecar so the
        # zombie-sweep + wipe exercises both layers in one shot.
        from backend.core.history_store_sqlite import SQLiteHistoryStore

        sqlite_store = SQLiteHistoryStore(purge_env["sqlite_db"])
        try:
            sqlite_store.create(
                "600595", "2026-07-21", status="running",
                analysis_id="zombie-bbca7f78",
            )
            cur = sqlite_store._conn.cursor()
            cur.execute(
                "UPDATE history SET status='running', elapsed=0, started_at=? "
                "WHERE analysis_id=?",
                (long_ago, "zombie-bbca7f78"),
            )
            sqlite_store._conn.commit()
        finally:
            sqlite_store.close()

        # Sanity: the zombie is visible to both layers.
        assert store.get("zombie-bbca7f78").status == "running"
        assert _count_rows(purge_env["sqlite_db"], "history") == 1

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # JSON zombie (now error) + SQLite row = 2 history_deleted.
        # Plus the bulk-delete clears the SQLite history row too, so the
        # total is 2 (1 JSON + 1 SQLite).
        assert body["history_deleted"] == 2, body
        # Both layers empty post-purge.
        assert store.get("zombie-bbca7f78") is None
        assert _count_rows(purge_env["sqlite_db"], "history") == 0


class TestPurgeWithoutSqlite:
    def test_purge_without_sqlite(self, client: TestClient, purge_env, monkeypatch):
        """Force ``get_sqlite_history_store_or_none`` to return ``None``
        (simulates a Python build without ``sqlite3``).  Purge must
        still succeed, JSON rows must still be wiped, no exception
        must propagate.  This is the graceful-degradation contract.
        """
        from backend.core import sqlite_helper
        from backend.core.history_store import get_history_store

        # Force the factory to always return None.
        monkeypatch.setattr(sqlite_helper, "get_sqlite_history_store_or_none", lambda db_path=None: None)

        # Seed 3 terminal JSON entries so we can prove the JSON wipe still works.
        for i in range(3):
            get_history_store().create(
                f"{600000 + i}", "2026-07-21", status="completed",
                analysis_id=f"json-only-{i}",
            )
        assert any(purge_env["history_dir"].glob("*.json"))

        r = client.post(
            "/api/history/purge",
            json={"confirmation": "CLEAR_ALL_HISTORY", "include_cache": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # All 3 history rows came from the JSON layer.
        assert body["history_deleted"] == 3, body
        assert body["failed_items"] == 0
        # JSON dir is empty.
        assert not any(purge_env["history_dir"].glob("*.json"))