"""Thread-safe in-memory store for analysis trackers + unified history."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.history_store import HistoryEntry, get_history_store


@dataclass
class AnalysisTracker:
    """Mutable state container for a single analysis run."""

    analysis_id: str
    ticker: str = ""
    trade_date: str = ""
    start_time: float = field(default_factory=time.time)

    is_running: bool = False
    is_complete: bool = False
    error: str | None = None

    current_stage: str = ""
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)

    final_state: dict[str, Any] = field(default_factory=dict)
    signal: str = ""

    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    def mark_stage_active(self, stage_id: str) -> None:
        with self._lock:
            self.current_stage = stage_id

    def mark_stage_done(self, stage_id: str, report: str = "") -> None:
        with self._lock:
            if stage_id not in self.completed_stages:
                self.completed_stages.append(stage_id)
            if report:
                self.stage_reports[stage_id] = report
            self.current_stage = ""
        get_history_store().mark_stage_done(self.analysis_id, stage_id, report)

    def mark_complete(self, final_state: dict, signal: str) -> None:
        with self._lock:
            self.final_state = final_state
            self.signal = signal
            self.is_running = False
            self.is_complete = True
        get_history_store().mark_complete(
            self.analysis_id,
            signal=signal,
            elapsed=self.elapsed,
            completed_stages=list(self.completed_stages),
        )

    def mark_error(self, err: str) -> None:
        with self._lock:
            self.error = err
            self.is_running = False
        get_history_store().mark_error(self.analysis_id, err, self.elapsed)

    def update_stats(self, llm: int, tool: int, tok_in: int, tok_out: int) -> None:
        with self._lock:
            self.llm_calls = llm
            self.tool_calls = tool
            self.tokens_in = tok_in
            self.tokens_out = tok_out

    def stage_status(self, stage_id: str) -> str:
        with self._lock:
            if stage_id in self.completed_stages:
                return "done"
            if stage_id == self.current_stage:
                return "active"
            return "pending"

    def to_progress_dict(self) -> dict:
        with self._lock:
            return {
                "status": "error" if self.error else ("complete" if self.is_complete else "running"),
                "ticker": self.ticker,
                "trade_date": self.trade_date,
                "current_stage": self.current_stage,
                "completed_stages": list(self.completed_stages),
                "stage_reports": dict(self.stage_reports),
                "stats": {
                    "llm_calls": self.llm_calls,
                    "tool_calls": self.tool_calls,
                    "tokens_in": self.tokens_in,
                    "tokens_out": self.tokens_out,
                },
                "elapsed": self.elapsed,
                "signal": self.signal,
                "error": self.error,
            }


class TrackerStore:
    """Singleton thread-safe in-memory store for all analysis trackers."""

    _instance: "TrackerStore | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._trackers: dict[str, AnalysisTracker] = {}
        self._store_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TrackerStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def create(
        self,
        ticker: str,
        trade_date: str,
    ) -> tuple[str, AnalysisTracker]:
        """Create a new tracker and return (analysis_id, tracker)."""
        analysis_id = f"{ticker}_{trade_date}_{uuid.uuid4().hex[:8]}"
        tracker = AnalysisTracker(
            analysis_id=analysis_id,
            ticker=ticker,
            trade_date=trade_date,
            is_running=True,
        )
        with self._store_lock:
            self._trackers[analysis_id] = tracker
        get_history_store().create(ticker, trade_date, status="running")
        return analysis_id, tracker

    def get(self, analysis_id: str) -> AnalysisTracker | None:
        with self._store_lock:
            return self._trackers.get(analysis_id)

    def delete(self, analysis_id: str) -> None:
        with self._store_lock:
            self._trackers.pop(analysis_id, None)
        get_history_store().delete(analysis_id)

    def list_all(self) -> list[AnalysisTracker]:
        with self._store_lock:
            return list(self._trackers.values())


def get_store() -> TrackerStore:
    return TrackerStore.get_instance()