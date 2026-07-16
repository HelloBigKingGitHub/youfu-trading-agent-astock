"""Unified history store — single source of truth for all analysis history.

All analysis history lives in ~/.tradingagents/logs/history/{analysis_id}.json.
The full analysis results (full_states_log_*.json) are written by
tradingagents.graph.TradingAgentsGraph._log_state() and are NOT moved or
merged — this store only manages the history metadata entries.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_HISTORY_DIR = Path.home() / ".tradingagents" / "logs" / "history"
_RESULTS_DIR = Path.home() / ".tradingagents" / "logs"

# P2.14 hotfix: a "zombie" analysis is one whose history.json claims
# status=running but the worker thread that should be progressing it was
# SIGKILL'd during a uvicorn restart. The file persists, no thread ever
# updates it again, and it sits forever at elapsed=0 / stages=[]. We treat
# any running entry that has not progressed within this many seconds as
# a zombie on backend startup.
ZOMBIE_THRESHOLD_SEC = 60.0


@dataclass
class HistoryEntry:
    """A single history entry persisted to disk."""

    analysis_id: str
    ticker: str
    trade_date: str
    signal: str = ""
    elapsed: float = 0.0
    status: str = "pending"  # pending | running | completed | error
    error: str | None = None
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    results_path: str = ""  # path to full_states_log_*.json

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "signal": self.signal,
            "elapsed": self.elapsed,
            "status": self.status,
            "error": self.error,
            "completed_stages": self.completed_stages,
            "stage_reports": self.stage_reports,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results_path": self.results_path,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HistoryEntry":
        return cls(
            analysis_id=d.get("analysis_id", ""),
            ticker=d.get("ticker", ""),
            trade_date=d.get("trade_date", ""),
            signal=d.get("signal", ""),
            elapsed=d.get("elapsed", 0.0),
            status=d.get("status", "pending"),
            error=d.get("error"),
            completed_stages=d.get("completed_stages", []),
            stage_reports=d.get("stage_reports", {}),
            created_at=d.get("created_at", time.time()),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            results_path=d.get("results_path", ""),
        )


class HistoryStore:
    """Thread-safe singleton history store backed by JSON files.

    All analysis history (both from Streamlit web UI and FastAPI backend)
    is written to and read from this single store.
    """

    _instance: "HistoryStore | None" = None
    _lock = __import__("threading").Lock()

    def __init__(self) -> None:
        self._lock_path = __import__("threading").Lock()

    @classmethod
    def get_instance(cls) -> "HistoryStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── write ──────────────────────────────────────────────────────────────────

    def create(
        self,
        ticker: str,
        trade_date: str,
        status: str = "running",
    ) -> HistoryEntry:
        """Create a new history entry (call when analysis starts)."""
        entry = HistoryEntry(
            analysis_id=f"{ticker}_{trade_date}_{uuid.uuid4().hex[:8]}",
            ticker=ticker,
            trade_date=trade_date,
            status=status,
            created_at=time.time(),
        )
        self._write(entry)
        return entry

    def update(self, entry: HistoryEntry) -> None:
        """Update an existing entry (call on stage complete, error, etc.)."""
        self._write(entry)

    def mark_running(self, analysis_id: str) -> HistoryEntry | None:
        """Mark an entry as running."""
        entry = self._read(analysis_id)
        if not entry:
            return None
        entry.status = "running"
        entry.started_at = time.time()
        self._write(entry)
        return entry

    def mark_stage_done(
        self,
        analysis_id: str,
        stage_id: str,
        report: str = "",
    ) -> None:
        """Mark a stage as done and optionally save a report snippet."""
        entry = self._read(analysis_id)
        if not entry:
            return
        if stage_id not in entry.completed_stages:
            entry.completed_stages.append(stage_id)
        if report:
            entry.stage_reports[stage_id] = report[:500]
        self._write(entry)

    def mark_complete(
        self,
        analysis_id: str,
        signal: str,
        elapsed: float,
        completed_stages: list[str],
    ) -> None:
        """Mark an entry as completed."""
        entry = self._read(analysis_id)
        if not entry:
            return
        entry.status = "completed"
        entry.signal = signal
        entry.elapsed = elapsed
        entry.completed_stages = completed_stages
        entry.finished_at = time.time()
        self._write(entry)

    def mark_error(self, analysis_id: str, error: str, elapsed: float = 0.0) -> None:
        """Mark an entry as errored."""
        entry = self._read(analysis_id)
        if not entry:
            return
        entry.status = "error"
        entry.error = error
        entry.elapsed = elapsed
        entry.finished_at = time.time()
        self._write(entry)

    def set_results_path(self, analysis_id: str, path: str) -> None:
        """Set the path to the full_states_log_*.json file."""
        entry = self._read(analysis_id)
        if not entry:
            return
        entry.results_path = path
        self._write(entry)

    def delete(self, analysis_id: str) -> None:
        """Delete a history entry."""
        path = _HISTORY_DIR / f"{analysis_id}.json"
        if path.exists():
            path.unlink()

    # ── read ───────────────────────────────────────────────────────────────────

    def get(self, analysis_id: str) -> HistoryEntry | None:
        return self._read(analysis_id)

    def list_all(
        self,
        ticker: str | None = None,
        signal: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        """List entries with optional filters, returns (entries, total)."""
        if not _HISTORY_DIR.exists():
            return [], 0

        entries: list[HistoryEntry] = []
        for f in _HISTORY_DIR.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            entry = HistoryEntry.from_dict(d)

            if ticker and ticker.upper() not in entry.ticker.upper():
                continue
            if signal and entry.signal != signal:
                continue
            if status and entry.status != status:
                continue
            entries.append(entry)

        entries.sort(key=lambda e: e.created_at, reverse=True)
        total = len(entries)
        return entries[offset : offset + limit], total

    def find_by_ticker_date(self, ticker: str, trade_date: str) -> HistoryEntry | None:
        """Find the most recent entry for a ticker + trade_date combination."""
        entries, _ = self.list_all(ticker=ticker, limit=100, offset=0)
        for e in entries:
            if e.ticker == ticker and e.trade_date == trade_date:
                return e
        return None

    # ── P2.14 hotfix: zombie detection ─────────────────────────────────────────

    @staticmethod
    def is_zombie(entry: HistoryEntry, now: float | None = None) -> bool:
        """Return True if entry claims to be running but is suspiciously stale.

        A zombie is an entry where:
          - status == "running"
          - elapsed == 0 (never progressed)
          - completed_stages == [] (no stage ever finished)
          - created_at older than ZOMBIE_THRESHOLD_SEC (default 60s)

        Root cause: a uvicorn restart SIGKILL'd the worker thread while the
        history.json was already on disk with status=running. The file
        persists but no thread ever updates it again, so it sits at 0/0/0
        forever. Used by the backend startup hook to mark these as error.
        """
        if now is None:
            now = time.time()
        return (
            entry.status == "running"
            and entry.elapsed == 0.0
            and not entry.completed_stages
            and (now - entry.created_at) > ZOMBIE_THRESHOLD_SEC
        )

    def cleanup_zombies(self, now: float | None = None) -> list[str]:
        """Mark all zombie entries as error. Returns list of analysis_ids cleaned.

        Called from ``backend.main`` on FastAPI startup so the recent-list
        UI never shows a permanently-stuck entry. Idempotent — re-running
        on a clean store is a no-op.
        """
        if now is None:
            now = time.time()
        cleaned: list[str] = []
        entries, _ = self.list_all(limit=1000, offset=0)
        for entry in entries:
            if self.is_zombie(entry, now=now):
                self.mark_error(
                    entry.analysis_id,
                    error="分析被中断 (server restart, thread was SIGKILL'd)",
                    elapsed=entry.elapsed or 0.0,
                )
                cleaned.append(entry.analysis_id)
        return cleaned

    # ── internal ───────────────────────────────────────────────────────────────

    def _path(self, analysis_id: str) -> Path:
        return _HISTORY_DIR / f"{analysis_id}.json"

    def _read(self, analysis_id: str) -> HistoryEntry | None:
        path = self._path(analysis_id)
        if not path.exists():
            return None
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return HistoryEntry.from_dict(d)
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, entry: HistoryEntry) -> None:
        try:
            _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            path = self._path(entry.analysis_id)
            path.write_text(
                json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # Non-critical


def get_history_store() -> HistoryStore:
    return HistoryStore.get_instance()