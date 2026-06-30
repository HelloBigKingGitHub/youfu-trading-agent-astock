"""Thread-safe job queue for batch analysis with stage-level progress tracking."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_HISTORY_DIR = Path.home() / ".tradingagents" / "logs" / "history"


@dataclass
class Job:
    """A single analysis job within a batch."""

    job_id: str
    analysis_id: str
    ticker: str
    trade_date: str
    status: str = "pending"  # pending | running | completed | error
    current_stage: str = ""
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)
    signal: str = ""
    error: str | None = None
    elapsed: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def stage_status(self, stage_id: str) -> str:
        with self._lock:
            if stage_id in self.completed_stages:
                return "done"
            if stage_id == self.current_stage:
                return "active"
            return "pending"

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id,
                "analysis_id": self.analysis_id,
                "ticker": self.ticker,
                "trade_date": self.trade_date,
                "status": self.status,
                "current_stage": self.current_stage,
                "completed_stages": list(self.completed_stages),
                "stage_reports": dict(self.stage_reports),
                "signal": self.signal,
                "error": self.error,
                "elapsed": self.elapsed,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


@dataclass
class BatchJob:
    """A batch of analysis jobs."""

    batch_id: str
    jobs: list[Job]
    created_at: float = field(default_factory=time.time)
    finished_count: int = 0
    error_count: int = 0


class JobQueue:
    """Thread-safe singleton job queue for batch analysis."""

    _instance: "JobQueue | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._batches: dict[str, BatchJob] = {}
        self._jobs: dict[str, Job] = {}  # job_id -> Job
        self._store_lock = threading.Lock()
        self._running_threads: dict[str, threading.Thread] = {}

    @classmethod
    def get_instance(cls) -> "JobQueue":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def create_batch(
        self,
        requests: list[dict],
    ) -> tuple[str, BatchJob]:
        """Create a batch of jobs from a list of {ticker, trade_date} dicts."""
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        jobs: list[Job] = []

        for req in requests:
            job_id = f"{req['ticker']}_{req['trade_date']}_{uuid.uuid4().hex[:8]}"
            job = Job(
                job_id=job_id,
                analysis_id=job_id,
                ticker=req["ticker"],
                trade_date=req["trade_date"],
            )
            jobs.append(job)

        batch = BatchJob(batch_id=batch_id, jobs=jobs)
        with self._store_lock:
            self._batches[batch_id] = batch
            for job in jobs:
                self._jobs[job.job_id] = job

        # Save history entries for all jobs
        for job in jobs:
            self._save_job_history(job, "pending")

        return batch_id, batch

    def get_job(self, job_id: str) -> Job | None:
        with self._store_lock:
            return self._jobs.get(job_id)

    def get_batch(self, batch_id: str) -> BatchJob | None:
        with self._store_lock:
            return self._batches.get(batch_id)

    def list_all_jobs(self) -> list[Job]:
        with self._store_lock:
            return list(self._jobs.values())

    def list_batches(self) -> list[BatchJob]:
        with self._store_lock:
            return list(self._batches.values())

    def start_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        with job._lock:
            job.status = "running"
            job.started_at = time.time()
        self._save_job_history(job, "running")

    def update_job_stage(
        self,
        job_id: str,
        stage_id: str,
        report: str = "",
        is_done: bool = False,
    ) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        with job._lock:
            job.current_stage = stage_id
            if is_done and stage_id not in job.completed_stages:
                job.completed_stages.append(stage_id)
                if report:
                    job.stage_reports[stage_id] = report[:500]
                job.current_stage = ""
                job.elapsed = (job.started_at or time.time()) - job.created_at
        self._save_job_history(job, job.status)

    def complete_job(self, job_id: str, signal: str, final_state: dict) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        with job._lock:
            job.status = "completed"
            job.signal = signal
            job.finished_at = time.time()
            job.elapsed = job.finished_at - (job.started_at or job.created_at)
        self._save_job_history(job, "completed")

        # Also save to log directory
        self._save_log_file(job, final_state)

    def error_job(self, job_id: str, error: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        with job._lock:
            job.status = "error"
            job.error = error
            job.finished_at = time.time()
            job.elapsed = job.finished_at - (job.started_at or job.created_at)
        self._save_job_history(job, "error")

    def _save_job_history(self, job: Job, status: str) -> None:
        """Persist a job entry to history JSON file."""
        try:
            _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            entry = {
                "job_id": job.job_id,
                "batch_id": getattr(job, "batch_id", ""),
                "analysis_id": job.analysis_id,
                "ticker": job.ticker,
                "trade_date": job.trade_date,
                "signal": job.signal,
                "elapsed": job.elapsed,
                "status": status,
                "error": job.error,
                "completed_stages": list(job.completed_stages),
                "current_stage": job.current_stage,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }
            path = _HISTORY_DIR / f"{job.analysis_id}.json"
            path.write_text(
                __import__("json").dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _save_log_file(self, job: Job, final_state: dict) -> None:
        """Save the full analysis result to the log directory."""
        try:
            log_root = Path.home() / ".tradingagents" / "logs"
            ticker_dir = log_root / job.ticker
            ticker_dir.mkdir(parents=True, exist_ok=True)
            path = ticker_dir / f"full_states_log_{job.trade_date}.json"
            path.write_text(
                __import__("json").dumps(final_state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


def get_job_queue() -> JobQueue:
    return JobQueue.get_instance()