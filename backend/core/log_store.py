"""Log store — read & write per-task log files.

Each analysis task lives in ~/.tradingagents/logs/{ticker}/{date}_run{NN}/
and has:
  - meta.json: task metadata
  - llm_messages.jsonl: stream chunks of type=llm
  - tool_calls.jsonl:   stream chunks of type=tool
  - agent_outputs.jsonl: stream chunks of type=agent_output

Compatible with legacy ~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/
via the read-compat shim.
"""

from __future__ import annotations

import fcntl
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"
_CHUNK_TYPES = ("llm_messages", "tool_calls", "agent_outputs")
_TYPE_FROM_FILENAME = {
    "llm_messages.jsonl": "llm",
    "tool_calls.jsonl": "tool",
    "agent_outputs.jsonl": "agent_output",
}
_FILENAME_FROM_TYPE = {v: k for k, v in _TYPE_FROM_FILENAME.items()}

_LEGACY_DIR_NAME = "TradingAgentsStrategy_logs"
_LEGACY_FILENAME_PREFIX = "full_states_log_"

_SIGNAL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("BUY", "Buy"),
    ("SELL", "Sell"),
    ("HOLD", "Hold"),
)


@dataclass
class TaskSummary:
    """Lightweight summary for the UI ticker list / task list."""

    analysis_id: str
    ticker: str
    trade_date: str
    task_dir_name: str
    status: str
    signal: str
    elapsed_sec: float
    started_at: float
    finished_at: float | None
    chunk_counts: dict[str, int] = field(default_factory=dict)
    is_legacy: bool = False


@dataclass
class LogChunk:
    """One stream chunk read from a .jsonl file."""

    ts: float
    type: str  # "llm" | "tool" | "agent_output"
    agent: str
    role: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    content: str | None = None
    tool: str | None = None
    input: dict | None = None
    output: str | None = None
    report_key: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _extract_signal(ftd: Any) -> str:
    """Extract Buy/Sell/Hold from a final_trade_decision string. Empty if unknown."""
    if not isinstance(ftd, str):
        return ""
    upper = ftd.upper()
    for kw, mapped in _SIGNAL_KEYWORDS:
        if kw in upper:
            return mapped
    return ""


class LogStore:
    """Read-only API for the UI to list tasks and stream chunks."""

    LOGS_ROOT = _LOGS_ROOT
    CHUNK_TYPES = _CHUNK_TYPES

    # ── list ────────────────────────────────────────────────────────────────
    def list_tickers(self) -> list[str]:
        """Return tickers that have ANY log (new or legacy), sorted desc by most-recent mtime."""
        if not _LOGS_ROOT.exists():
            return []

        results: list[tuple[str, float]] = []
        for ticker_dir in _LOGS_ROOT.iterdir():
            if not ticker_dir.is_dir():
                continue

            max_mtime = 0.0
            # New structure: {ticker}/{date}_run{NN}/meta.json
            for meta_file in ticker_dir.glob("*/meta.json"):
                try:
                    mtime = meta_file.stat().st_mtime
                except OSError:
                    continue
                if mtime > max_mtime:
                    max_mtime = mtime

            # Legacy: {ticker}/TradingAgentsStrategy_logs/full_states_log_*.json
            legacy_dir = ticker_dir / _LEGACY_DIR_NAME
            if legacy_dir.is_dir():
                for legacy_file in legacy_dir.glob(f"{_LEGACY_FILENAME_PREFIX}*.json"):
                    try:
                        mtime = legacy_file.stat().st_mtime
                    except OSError:
                        continue
                    if mtime > max_mtime:
                        max_mtime = mtime

            if max_mtime > 0:
                results.append((ticker_dir.name, max_mtime))

        results.sort(key=lambda x: x[1], reverse=True)
        return [ticker for ticker, _ in results]

    def list_tasks(self, ticker: str) -> list[TaskSummary]:
        """Return all tasks for a ticker, sorted by started_at desc.

        New structure wins over legacy when both exist for the same trade_date.
        """
        ticker_dir = _LOGS_ROOT / ticker
        if not ticker_dir.is_dir():
            return []

        tasks: list[TaskSummary] = []
        seen_dates: set[str] = set()

        # New structure first (takes precedence)
        for meta_file in sorted(ticker_dir.glob("*/meta.json")):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            trade_date = meta.get("trade_date", "")
            seen_dates.add(trade_date)

            try:
                fallback_mtime = meta_file.stat().st_mtime
            except OSError:
                fallback_mtime = 0.0

            tasks.append(TaskSummary(
                analysis_id=meta.get("analysis_id", ""),
                ticker=meta.get("ticker", ticker),
                trade_date=trade_date,
                task_dir_name=meta_file.parent.name,
                status=meta.get("status", "running"),
                signal=meta.get("signal", ""),
                elapsed_sec=float(meta.get("elapsed_sec", 0.0)),
                started_at=float(meta.get("started_at", fallback_mtime)),
                finished_at=meta.get("finished_at"),
                chunk_counts=meta.get(
                    "chunk_counts", {"llm": 0, "tool": 0, "agent_output": 0}
                ),
                is_legacy=False,
            ))

        # Legacy: skip dates already covered by new entries
        legacy_dir = ticker_dir / _LEGACY_DIR_NAME
        if legacy_dir.is_dir():
            for legacy_file in sorted(legacy_dir.glob(f"{_LEGACY_FILENAME_PREFIX}*.json")):
                stem = legacy_file.stem  # e.g. "full_states_log_2026-06-10"
                if not stem.startswith(_LEGACY_FILENAME_PREFIX):
                    continue
                date_part = stem[len(_LEGACY_FILENAME_PREFIX):]
                if date_part in seen_dates:
                    continue
                try:
                    state = json.loads(legacy_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                try:
                    mtime = legacy_file.stat().st_mtime
                except OSError:
                    continue

                tasks.append(TaskSummary(
                    analysis_id=f"legacy_{ticker}_{date_part}",
                    ticker=ticker,
                    trade_date=date_part,
                    task_dir_name=f"{date_part}_run01",
                    status="completed",
                    signal=_extract_signal(state.get("final_trade_decision", "")),
                    elapsed_sec=0.0,
                    started_at=mtime,
                    finished_at=mtime,
                    chunk_counts={"llm": 0, "tool": 0, "agent_output": 0},
                    is_legacy=True,
                ))

        tasks.sort(key=lambda t: t.started_at, reverse=True)
        return tasks

    # ── meta ────────────────────────────────────────────────────────────────
    def get_meta(self, ticker: str, task_dir_name: str) -> dict:
        """Read meta.json or fallback to legacy. Raises FileNotFoundError."""
        new_path = _LOGS_ROOT / ticker / task_dir_name / "meta.json"
        if new_path.exists():
            return json.loads(new_path.read_text(encoding="utf-8"))

        legacy_date = task_dir_name.split("_run")[0]
        legacy_path = (
            _LOGS_ROOT / ticker / _LEGACY_DIR_NAME
            / f"{_LEGACY_FILENAME_PREFIX}{legacy_date}.json"
        )
        if legacy_path.exists():
            state = json.loads(legacy_path.read_text(encoding="utf-8"))
            mtime = legacy_path.stat().st_mtime
            return {
                "analysis_id": f"legacy_{ticker}_{legacy_date}",
                "ticker": ticker,
                "trade_date": legacy_date,
                "task_dir_name": task_dir_name,
                "status": "completed",
                "signal": _extract_signal(state.get("final_trade_decision", "")),
                "elapsed_sec": 0.0,
                "started_at": mtime,
                "finished_at": mtime,
                "error": None,
                "stages_completed": [],
                "chunk_counts": {"llm": 0, "tool": 0, "agent_output": 0},
                "is_legacy": True,
                "legacy_state": state,
            }
        raise FileNotFoundError(
            f"No log for {ticker}/{task_dir_name} (neither new nor legacy)"
        )

    # ── chunks ──────────────────────────────────────────────────────────────
    def count_chunks(self, ticker: str, task_dir_name: str) -> dict[str, int]:
        """Return {type: count}. Legacy tasks return all zeros."""
        task_dir = self._task_dir(ticker, task_dir_name)
        if not (task_dir / "meta.json").exists():
            return {"llm": 0, "tool": 0, "agent_output": 0}

        result: dict[str, int] = {}
        for jsonl_name, chunk_type in _TYPE_FROM_FILENAME.items():
            path = task_dir / jsonl_name
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        result[chunk_type] = sum(1 for _ in f)
                except OSError:
                    result[chunk_type] = 0
            else:
                result[chunk_type] = 0
        return result

    def stream_chunks(
        self,
        ticker: str,
        task_dir_name: str,
        type_filter: str | None = None,
    ) -> Iterator[LogChunk]:
        """Yield LogChunks in chronological order.

        type_filter: None=全部, 'llm'/'tool'/'agent_output'=只 yield 该类型.
        Legacy tasks yield nothing.
        """
        task_dir = self._task_dir(ticker, task_dir_name)
        if not (task_dir / "meta.json").exists():
            return  # Legacy: yield nothing

        # Decide which jsonl files to read based on type_filter
        files_to_read: list[tuple[str, Path]] = []
        for jsonl_name, chunk_type in _TYPE_FROM_FILENAME.items():
            if type_filter is not None and type_filter != chunk_type:
                continue
            path = task_dir / jsonl_name
            if path.exists():
                files_to_read.append((chunk_type, path))

        chunks: list[LogChunk] = []
        for chunk_type, path in files_to_read:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        chunks.append(_chunk_from_dict(data))
            except OSError:
                continue

        chunks.sort(key=lambda c: c.ts)
        yield from chunks

    # ── internal ────────────────────────────────────────────────────────────
    def _task_dir(self, ticker: str, task_dir_name: str) -> Path:
        return _LOGS_ROOT / ticker / task_dir_name


def _chunk_from_dict(data: dict) -> LogChunk:
    """Build a LogChunk from a JSONL line dict."""
    return LogChunk(
        ts=float(data.get("ts", 0.0)),
        type=data.get("type", "llm"),
        agent=data.get("agent", ""),
        role=data.get("role"),
        tokens_in=data.get("tokens_in"),
        tokens_out=data.get("tokens_out"),
        content=data.get("content"),
        tool=data.get("tool"),
        input=data.get("input"),
        output=data.get("output"),
        report_key=data.get("report_key"),
    )


class LogWriter:
    """Append-only writer for a single running task. Used by web/runner.py."""

    def __init__(self, analysis_id: str, ticker: str, trade_date: str) -> None:
        """Pick next run{NN} for {ticker}/{date} and create dir.

        Raises FileExistsError if dir already exists (caller should pick a
        different analysis_id).
        """
        ticker_dir = _LOGS_ROOT / ticker

        existing = sorted(p.name for p in ticker_dir.glob(f"{trade_date}_run*"))
        if existing:
            last_n = max(int(p.split("_run")[1]) for p in existing)
            run_nn = f"run{last_n + 1:02d}"
        else:
            run_nn = "run01"

        self.task_dir = ticker_dir / f"{trade_date}_{run_nn}"
        self.task_dir.mkdir(parents=True, exist_ok=False)
        self.task_dir_name = self.task_dir.name
        self.analysis_id = analysis_id
        self.ticker = ticker
        self.trade_date = trade_date
        self.started_at = time.time()
        self.chunk_counts: dict[str, int] = {"llm": 0, "tool": 0, "agent_output": 0}

        self._write_meta({
            "analysis_id": analysis_id,
            "ticker": ticker,
            "trade_date": trade_date,
            "task_dir_name": self.task_dir_name,
            "status": "running",
            "signal": "",
            "elapsed_sec": 0.0,
            "started_at": self.started_at,
            "finished_at": None,
            "error": None,
            "stages_completed": [],
            "chunk_counts": dict(self.chunk_counts),
            "created_at": self.started_at,
        })

    def append_chunk(self, chunk: LogChunk) -> None:
        """Append one chunk to the appropriate jsonl file. Uses fcntl.flock for safety."""
        if chunk.type not in _FILENAME_FROM_TYPE:
            raise ValueError(f"Unknown chunk type: {chunk.type!r}")
        filename = _FILENAME_FROM_TYPE[chunk.type]
        path = self.task_dir / filename
        line = json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n"

        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        self.chunk_counts[chunk.type] = self.chunk_counts.get(chunk.type, 0) + 1

        # Update meta chunk_counts every 10 chunks (avoid fs churn)
        total = sum(self.chunk_counts.values())
        if total % 10 == 0:
            self._write_meta_field("chunk_counts", dict(self.chunk_counts))

    def update_stages(self, completed_stages: list[str]) -> None:
        """Update stages_completed in meta.json. Idempotent."""
        self._write_meta_field("stages_completed", completed_stages)

    def finalize(
        self,
        signal: str,
        elapsed_sec: float,
        error: str | None = None,
        completed_stages: list[str] | None = None,
    ) -> None:
        """Mark task as completed or errored. Update meta.json."""
        status = "error" if error else "completed"
        updates: dict[str, Any] = {
            "status": status,
            "signal": signal,
            "elapsed_sec": elapsed_sec,
            "finished_at": time.time(),
            "error": error,
            "chunk_counts": dict(self.chunk_counts),
        }
        if completed_stages is not None:
            updates["stages_completed"] = completed_stages
        for k, v in updates.items():
            self._write_meta_field(k, v)

    # ── internal ────────────────────────────────────────────────────────────
    def _meta_path(self) -> Path:
        return self.task_dir / "meta.json"

    def _write_meta(self, data: dict) -> None:
        """Atomic write (write to .tmp, then rename)."""
        tmp = self._meta_path().with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._meta_path())

    def _write_meta_field(self, field: str, value: Any) -> None:
        """Read meta, update one field, write back."""
        path = self._meta_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data[field] = value
        self._write_meta(data)


# ── Module-level singleton for LogStore (read-only) ────────────────────────
_log_store_singleton: LogStore | None = None


def get_log_store() -> LogStore:
    """Return module-level singleton LogStore (read-only)."""
    global _log_store_singleton
    if _log_store_singleton is None:
        _log_store_singleton = LogStore()
    return _log_store_singleton