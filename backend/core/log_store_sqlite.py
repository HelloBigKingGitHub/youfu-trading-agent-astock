"""SQLite sidecar implementation for the Phase 3c log migration.

The JSONL implementation in :mod:`backend.core.log_store` remains the
runtime source of truth during Phase 3c.  The classes in this module are a
separate, compatibility-shaped sidecar used by the dual-write wrapper.

The sidecar stores task metadata in ``history`` and stream events in
``log_chunks``.  ``stage_reports`` and ``completed_stages`` mirror the stage
list maintained by ``LogWriter.update_stages``.  No code in the legacy log
store is imported for behaviour; only its public dataclasses are reused so
that callers receive the same objects.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from backend.core.log_store import LogChunk, TaskSummary
from backend.storage.schema_migrations.migrate import migrate

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path.home() / ".tradingagents" / "tradingagents.db"
_CHUNK_TYPES = ("llm", "tool", "agent_output")
_RUN_RE = re.compile(r"_run(\d+)$")


class _SQLiteBase:
    """Common connection, PRAGMA, locking, and transaction helpers."""

    def __init__(self, db_path: Path | None) -> None:
        self.db = Path(db_path) if db_path is not None else _DEFAULT_DB
        self.db.parent.mkdir(parents=True, exist_ok=True)

        # Make an independently-created sidecar usable.  The migration runner
        # is idempotent and does not change any legacy JSON runtime path.
        list(migrate(db_path=self.db))

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()

    def _apply_pragmas(self) -> None:
        """Apply connection-local PRAGMAs exactly once after connect."""
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA cache_size = -64000")
        self._conn.execute("PRAGMA temp_store = MEMORY")

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[None]:
        """Run a write in an explicit IMMEDIATE transaction."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()


class SQLiteLogStore(_SQLiteBase):
    """SQLite implementation with the public read API of ``LogStore``.

    Reads from this class are intentionally not installed into the running
    application in Phase 3c.  ``DualWriteLogStore`` keeps JSONL as the read
    source of truth until the later read-cutover phase.
    """

    def list_tickers(self) -> list[str]:
        """Return tickers with history/log rows, newest ticker first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker, MAX(created_at) AS latest FROM history "
                "GROUP BY ticker ORDER BY latest DESC, ticker ASC"
            ).fetchall()
            return [str(row["ticker"]) for row in rows]

    def list_tasks(self, ticker: str) -> list[TaskSummary]:
        """Return task summaries for ``ticker``, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM history WHERE ticker = ? "
                "ORDER BY created_at DESC, analysis_id ASC",
                (ticker,),
            ).fetchall()
            return [self._task_summary(row) for row in rows]

    def get_meta(self, ticker: str, task_dir_name: str) -> dict[str, Any]:
        """Return a JSON-compatible meta dict for one task.

        The legacy store raises ``FileNotFoundError`` for an unknown task; the
        SQLite compatibility implementation preserves that contract.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT h.* FROM history h "
                "LEFT JOIN log_chunks c ON c.analysis_id = h.analysis_id "
                "WHERE h.ticker = ? AND (c.task_dir_name = ? OR "
                "(c.analysis_id IS NULL AND h.trade_date = ?)) "
                "ORDER BY h.created_at DESC LIMIT 1",
                (ticker, task_dir_name, task_dir_name.split("_run", 1)[0]),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(
                    f"No SQLite log for {ticker}/{task_dir_name}"
                )
            return self._meta_for_row(row, task_dir_name=task_dir_name)

    def count_chunks(self, ticker: str, task_dir_name: str) -> dict[str, int]:
        """Return counts grouped by chunk type for one ticker/task."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.type, COUNT(*) AS n FROM log_chunks c "
                "JOIN history h ON h.analysis_id = c.analysis_id "
                "WHERE h.ticker = ? AND c.task_dir_name = ? GROUP BY c.type",
                (ticker, task_dir_name),
            ).fetchall()
            counts = {kind: 0 for kind in _CHUNK_TYPES}
            for row in rows:
                if row["type"] in counts:
                    counts[row["type"]] = int(row["n"])
            return counts

    def stream_chunks(
        self,
        ticker: str,
        task_dir_name: str,
        type_filter: str | None = None,
    ) -> Iterator[LogChunk]:
        """Yield chunks in timestamp order, optionally filtered by type."""
        with self._lock:
            sql = (
                "SELECT c.* FROM log_chunks c "
                "JOIN history h ON h.analysis_id = c.analysis_id "
                "WHERE h.ticker = ? AND c.task_dir_name = ?"
            )
            params: list[Any] = [ticker, task_dir_name]
            if type_filter is not None:
                sql += " AND c.type = ?"
                params.append(type_filter)
            sql += " ORDER BY c.ts ASC, c.id ASC"
            rows = self._conn.execute(sql, params).fetchall()

        # Materialise under the connection lock, then yield after releasing
        # it.  This avoids holding a SQLite connection lock while a UI renders.
        for row in rows:
            yield self._chunk_from_row(row)

    def _task_summary(self, row: sqlite3.Row) -> TaskSummary:
        task_dir_name = self._task_dir_for_analysis(str(row["analysis_id"]), row)
        return TaskSummary(
            analysis_id=str(row["analysis_id"]),
            ticker=str(row["ticker"]),
            trade_date=str(row["trade_date"]),
            task_dir_name=task_dir_name,
            status=str(row["status"]),
            signal=row["signal"] or "",
            elapsed_sec=float(row["elapsed"] or 0.0),
            started_at=float(row["started_at"] or row["created_at"]),
            finished_at=row["finished_at"],
            chunk_counts=self._counts_for_analysis(str(row["analysis_id"])),
            is_legacy=False,
        )

    def _meta_for_row(
        self, row: sqlite3.Row, task_dir_name: str | None = None
    ) -> dict[str, Any]:
        analysis_id = str(row["analysis_id"])
        task_dir_name = task_dir_name or self._task_dir_for_analysis(analysis_id, row)
        stages = self._conn.execute(
            "SELECT stage_id FROM completed_stages WHERE analysis_id = ? "
            "ORDER BY sequence ASC",
            (analysis_id,),
        ).fetchall()
        return {
            "analysis_id": analysis_id,
            "ticker": str(row["ticker"]),
            "trade_date": str(row["trade_date"]),
            "task_dir_name": task_dir_name,
            "status": str(row["status"]),
            "signal": row["signal"] or "",
            "elapsed_sec": float(row["elapsed"] or 0.0),
            "started_at": float(row["started_at"] or row["created_at"]),
            "finished_at": row["finished_at"],
            "error": row["error"],
            "stages_completed": [str(stage["stage_id"]) for stage in stages],
            "chunk_counts": self._counts_for_analysis(analysis_id),
            "created_at": float(row["created_at"]),
        }

    def _task_dir_for_analysis(
        self, analysis_id: str, row: sqlite3.Row | None = None
    ) -> str:
        chunk_row = self._conn.execute(
            "SELECT task_dir_name FROM log_chunks WHERE analysis_id = ? "
            "ORDER BY id ASC LIMIT 1",
            (analysis_id,),
        ).fetchone()
        if chunk_row is not None:
            return str(chunk_row["task_dir_name"])
        if row is None:
            row = self._conn.execute(
                "SELECT trade_date FROM history WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return ""
        return f"{row['trade_date']}_run01"

    def _counts_for_analysis(self, analysis_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT type, COUNT(*) AS n FROM log_chunks "
            "WHERE analysis_id = ? GROUP BY type",
            (analysis_id,),
        ).fetchall()
        counts = {kind: 0 for kind in _CHUNK_TYPES}
        for row in rows:
            if row["type"] in counts:
                counts[row["type"]] = int(row["n"])
        return counts

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> LogChunk:
        raw_input = row["input_json"]
        try:
            input_value = json.loads(raw_input) if raw_input is not None else None
        except (TypeError, json.JSONDecodeError):
            input_value = None
        return LogChunk(
            ts=float(row["ts"]),
            type=str(row["type"]),
            agent=str(row["agent"] or ""),
            role=row["role"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            content=row["content"],
            tool=row["tool"],
            input=input_value,
            output=row["output"],
            report_key=row["report_key"],
        )


class SQLiteLogWriter(_SQLiteBase):
    """SQLite implementation with the public write API of ``LogWriter``."""

    def __init__(
        self,
        analysis_id: str,
        ticker: str,
        trade_date: str,
        db_path: Path | None = None,
    ) -> None:
        super().__init__(db_path)
        self.analysis_id = analysis_id
        self.ticker = ticker
        self.trade_date = trade_date
        self.started_at = time.time()
        self.chunk_counts: dict[str, int] = {kind: 0 for kind in _CHUNK_TYPES}

        # log_chunks has a foreign key to history.  When Phase 3b history
        # dual-write is not enabled, create the minimal parent row here so
        # DUAL_WRITE_LOGS=1 remains independently usable.
        with self._transaction():
            self._conn.execute(
                "INSERT OR IGNORE INTO history "
                "(analysis_id, ticker, trade_date, signal, elapsed, status, "
                "error, results_path, started_at, finished_at, created_at) "
                "VALUES (?, ?, ?, '', 0, 'running', NULL, '', ?, NULL, ?)",
                (analysis_id, ticker, trade_date, self.started_at, self.started_at),
            )
        self.task_dir_name = self._next_task_dir_name()

    def _next_task_dir_name(self) -> str:
        """Choose the next ``{trade_date}_runNN`` used by this ticker/date."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT c.task_dir_name FROM log_chunks c "
                "JOIN history h ON h.analysis_id = c.analysis_id "
                "WHERE h.ticker = ? AND h.trade_date = ?",
                (self.ticker, self.trade_date),
            ).fetchall()
        max_run = 0
        for row in rows:
            match = _RUN_RE.search(str(row["task_dir_name"]))
            if match:
                max_run = max(max_run, int(match.group(1)))
        return f"{self.trade_date}_run{max_run + 1:02d}"

    def append_chunk(self, chunk: LogChunk) -> None:
        """Insert one chunk and update this writer's in-memory count."""
        if chunk.type not in _CHUNK_TYPES:
            raise ValueError(f"Unknown chunk type: {chunk.type!r}")
        input_json = (
            json.dumps(chunk.input, ensure_ascii=False, separators=(",", ":"))
            if chunk.input is not None
            else None
        )
        with self._transaction():
            self._conn.execute(
                "INSERT INTO log_chunks "
                "(analysis_id, task_dir_name, ts, type, agent, role, tokens_in, "
                "tokens_out, content, tool, input_json, output, report_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.analysis_id,
                    self.task_dir_name,
                    chunk.ts,
                    chunk.type,
                    chunk.agent,
                    chunk.role,
                    chunk.tokens_in,
                    chunk.tokens_out,
                    chunk.content,
                    chunk.tool,
                    input_json,
                    chunk.output,
                    chunk.report_key,
                ),
            )
        self.chunk_counts[chunk.type] = self.chunk_counts.get(chunk.type, 0) + 1

    def update_stages(self, completed_stages: list[str]) -> None:
        """Replace completed stage order and mirror stage-report keys."""
        with self._transaction():
            self._update_stages_unlocked(completed_stages)

    def finalize(
        self,
        signal: str = "",
        elapsed_sec: float = 0.0,
        error: str | None = None,
        stages: list[str] | None = None,
        completed_stages: list[str] | None = None,
    ) -> None:
        """Finalize the parent history row and, optionally, stage children."""
        stage_list = completed_stages if completed_stages is not None else stages
        status = "error" if error else "completed"
        with self._transaction():
            self._conn.execute(
                "UPDATE history SET status = ?, signal = ?, elapsed = ?, "
                "error = ?, finished_at = ? WHERE analysis_id = ?",
                (
                    status,
                    signal,
                    elapsed_sec,
                    error or None,
                    time.time(),
                    self.analysis_id,
                ),
            )
            if stage_list is not None:
                self._update_stages_unlocked(stage_list)

    def _update_stages_unlocked(self, completed_stages: list[str]) -> None:
        self._conn.execute(
            "DELETE FROM completed_stages WHERE analysis_id = ?",
            (self.analysis_id,),
        )
        self._conn.execute(
            "DELETE FROM stage_reports WHERE analysis_id = ?",
            (self.analysis_id,),
        )
        now = time.time()
        for sequence, stage_id in enumerate(completed_stages, start=1):
            self._conn.execute(
                "INSERT INTO completed_stages "
                "(analysis_id, stage_id, completed_at, sequence) VALUES (?, ?, ?, ?)",
                (self.analysis_id, stage_id, now, sequence),
            )
            # update_stages receives only stage IDs (the legacy API has no
            # report payload).  A blank report row preserves the relational
            # child shape; actual chunk content remains in log_chunks.
            self._conn.execute(
                "INSERT INTO stage_reports "
                "(analysis_id, report_key, stage_id, content, created_at) "
                "VALUES (?, ?, ?, '', ?)",
                (self.analysis_id, stage_id, stage_id, now),
            )


__all__ = ["SQLiteLogStore", "SQLiteLogWriter"]
