"""Thread-safe job queue for batch analysis with stage-level progress tracking.

设计要点:
- 单例 `JobQueue` 持有一组 batch + 共享的 ThreadPoolExecutor(`max_workers` 默认 5)。
- 历史持久化统一走 `HistoryStore`,本模块不重复写盘 — 完整 `full_states_log_*.json`
  由 `graph._log_state()` 在分析完成时写入。
- 一个 job 抛异常不影响同 batch 其他 job;失败的 job 可以通过 `retry()` 重新入池。
- 东财 429/被封检测由 `_handle_em_block` 处理(指数退避一次,再失败才标记 error)。
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


# ── Ticker 白名单 ─────────────────────────────────────────────────────────────
# 严格 6 位 A 股代码段:沪市主板 60x/601/603/605 + 科创板 688 + 深市主板 000/001 +
# 中小板 002 + 深市主板 003 + 创业板 300/301 + 北交所 430。
TICKER_WHITELIST_RE = re.compile(
    r"^(60[0-5]\d{3}|688\d{3}|000\d{3}|001\d{3}|002\d{3}|003\d{3}"
    r"|300\d{3}|301\d{3}|430\d{3})$"
)


class BatchStatus(str, Enum):
    """Batch-level derived status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"  # all jobs completed
    PARTIAL = "partial"      # some completed, some error
    FAILED = "failed"        # all jobs error
    CANCELLED = "cancelled"  # all jobs cancelled


# 东财返回 429 / 403 / 空数据时的错误关键字,用于触发重试。
_EM_BLOCK_PATTERNS = (
    "429", "Too Many Requests", "Forbidden", "访问频",
    "触发限流", "blocked", "rate limit",
)


# ── 数据结构 ──────────────────────────────────────────────────────────────────


@dataclass
class Job:
    """Single analysis job in a batch."""

    job_id: str
    analysis_id: str
    ticker: str
    trade_date: str
    status: str = "pending"  # pending | running | completed | error | cancelled
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
    _cancel_requested: bool = field(default=False, repr=False)

    def stage_status(self, stage_id: str) -> str:
        with self._lock:
            if stage_id in self.completed_stages:
                return "done"
            if stage_id == self.current_stage:
                return "active"
            return "pending"

    def request_cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True

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

    @property
    def batch_status(self) -> str:
        # Derived state — derived from job statuses. No separate field.
        statuses = [j.status for j in self.jobs]
        if all(s == "completed" for s in statuses):
            return BatchStatus.COMPLETED.value
        if all(s in ("error", "cancelled") for s in statuses):
            return BatchStatus.FAILED.value
        if all(s == "cancelled" for s in statuses):
            return BatchStatus.CANCELLED.value
        if any(s == "completed" for s in statuses) and not any(
            s in ("pending", "running") for s in statuses
        ):
            return BatchStatus.PARTIAL.value
        if any(s == "running" for s in statuses):
            return BatchStatus.RUNNING.value
        return BatchStatus.PENDING.value


# ── Queue ─────────────────────────────────────────────────────────────────────


class JobQueue:
    """Thread-safe singleton job queue for batch analysis.

    Persists history entries via `HistoryStore` (no double-write).
    """

    _instance: "JobQueue | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._batches: dict[str, BatchJob] = {}
        self._jobs: dict[str, Job] = {}
        self._store_lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._max_workers: int = int(os.environ.get("BATCH_MAX_WORKERS", "5"))
        self._stagger_seconds: float = float(os.environ.get("BATCH_STAGGER", "1.5"))

    @classmethod
    def get_instance(cls) -> "JobQueue":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # 显式重置,测试时用。
    @classmethod
    def _reset_singleton(cls) -> None:
        with cls._singleton_lock:
            if cls._instance is not None and cls._instance._executor is not None:
                cls._instance._executor.shutdown(wait=False)
            cls._instance = None

    # ── Executor ───────────────────────────────────────────────────────────────

    def _get_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            with self._store_lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix="batch-worker",
                    )
        return self._executor

    # ── Batch lifecycle ────────────────────────────────────────────────────────

    def create_batch(
        self,
        requests: list[dict],
    ) -> tuple[str, BatchJob]:
        """Create a batch of jobs from a list of {ticker, trade_date} dicts.

        Does NOT start threads — call `submit()` separately.
        """
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        jobs: list[Job] = []
        for req in requests:
            ticker = str(req.get("ticker", "")).strip()
            trade_date = str(req.get("trade_date", "")).strip()
            job_id = f"{ticker}_{trade_date}_{uuid.uuid4().hex[:8]}"
            analysis_id = job_id  # 复用为 history entry id
            jobs.append(
                Job(
                    job_id=job_id,
                    analysis_id=analysis_id,
                    ticker=ticker,
                    trade_date=trade_date,
                )
            )
        batch = BatchJob(batch_id=batch_id, jobs=jobs)
        with self._store_lock:
            self._batches[batch_id] = batch
            for job in jobs:
                self._jobs[job.job_id] = job
        return batch_id, batch

    def submit(
        self,
        batch_id: str,
        jobs: list[Job],
        configs: list[dict] | None = None,
    ) -> list[Future]:
        """Schedule all jobs through the shared ThreadPoolExecutor.

        Args:
            batch_id: 所属 batch。
            jobs: 任务列表。
            configs: 每个 job 对应的 config dict;若为 None,所有 job 用空 config。

        Returns:
            list of Futures (test/debug only,生产代码不需要 await)。
        """
        if configs is None:
            configs = [{}] * len(jobs)
        assert len(configs) == len(jobs), "configs 长度必须等于 jobs 长度"

        executor = self._get_executor()
        futures: list[Future] = []
        # stagger:相邻 job 提交间隔 `_stagger_seconds`,防东财瞬时并发。
        for i, job in enumerate(jobs):
            if i > 0:
                time.sleep(self._stagger_seconds)
            futures.append(
                executor.submit(self._run_one, batch_id, job.job_id, configs[i])
            )
        return futures

    def _run_one(self, batch_id: str, job_id: str, config: dict) -> None:
        """Execute a single job. Catches all exceptions so the batch survives."""
        job = self.get_job(job_id)
        if not job:
            return

        # 取消检查:入队前已被取消
        with job._lock:
            if job._cancel_requested:
                job.status = "cancelled"
                job.finished_at = time.time()
                return
            job.status = "running"
            job.started_at = time.time()

        try:
            self._run_pipeline(job, config)
            with job._lock:
                # 取消可能在执行期间发生
                if job._cancel_requested:
                    job.status = "cancelled"
                else:
                    job.status = "completed"
                job.finished_at = time.time()
                job.elapsed = job.finished_at - (job.started_at or job.finished_at)
        except Exception as exc:  # noqa: BLE001
            err_msg = str(exc)
            self._handle_em_block(job, err_msg)
            with job._lock:
                if job.status != "completed":
                    if job._cancel_requested:
                        job.status = "cancelled"
                    else:
                        job.status = "error"
                        job.error = err_msg[:500]
                    job.finished_at = time.time()
                    job.elapsed = job.finished_at - (job.started_at or job.finished_at)

    def _run_pipeline(self, job: Job, config: dict) -> None:
        """实际跑 pipeline。

        默认调用 `web.runner._run` — 同一份代码被 web UI 和 batch 复用,确保
        stage 解析、HistoryStore 写入、stats 上报行为完全一致。
        """
        # 延迟 import,避免 backend 包 import 时拉起整个 tradingagents 栈
        from web.runner import _run as web_run

        # 创建一个 web 用的 ProgressTracker,把 stage 写回 Job
        from web.progress import ProgressTracker

        tracker = ProgressTracker(ticker=job.ticker, trade_date=job.trade_date)
        tracker.is_running = True
        tracker.analysis_id = job.analysis_id

        # 用闭包劫持 tracker 的 stage_done,把 stage 状态镜像回 job
        original_mark_done = tracker.mark_stage_done

        def mirror_mark_done(stage_id: str, report: str = "") -> None:
            with job._lock:
                if stage_id not in job.completed_stages:
                    job.completed_stages.append(stage_id)
                if report:
                    job.stage_reports[stage_id] = str(report)[:500]
                if job.current_stage == stage_id:
                    job.current_stage = ""
            original_mark_done(stage_id, report)

        def mirror_mark_active(stage_id: str) -> None:
            with job._lock:
                job.current_stage = stage_id
            from web.progress import ProgressTracker as _PT
            _PT.mark_stage_active(tracker, stage_id)

        tracker.mark_stage_done = mirror_mark_done  # type: ignore[assignment]
        tracker.mark_stage_active = mirror_mark_active  # type: ignore[assignment]

        web_run(job.ticker, job.trade_date, config, tracker, job.analysis_id)

        # 写回 signal
        with job._lock:
            job.signal = tracker.signal or ""

    def _handle_em_block(self, job: Job, err: str) -> None:
        """东财 429/被封:退避一次后重试一次。仍然失败则记 error。"""
        if not any(p.lower() in err.lower() for p in _EM_BLOCK_PATTERNS):
            return
        backoff = float(os.environ.get("EM_BLOCK_BACKOFF", "8.0"))
        logger.warning(
            "Job %s hit eastmoney rate limit, backing off %.1fs and retrying once",
            job.job_id, backoff,
        )
        time.sleep(backoff)
        try:
            self._run_pipeline(job, {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retry after eastmoney block failed: %s", exc)
            # 抛出让上层记录 error
            raise

    # ── Cancellation / retry ───────────────────────────────────────────────────

    def cancel_job(self, job_id: str) -> bool:
        """取消一个 job(若未开始则直接 cancelled,若正在跑则标记 _cancel_requested
        由 worker 检查并退出)。已结束的 job 不受影响。
        """
        job = self.get_job(job_id)
        if not job:
            return False
        with job._lock:
            if job.status in ("completed", "error", "cancelled"):
                return False
            job._cancel_requested = True
            if job.status == "pending":
                job.status = "cancelled"
                job.finished_at = time.time()
        return True

    def cancel_batch(self, batch_id: str) -> int:
        """取消一个 batch 内所有 pending/running 的 job。返回取消的数量。"""
        batch = self.get_batch(batch_id)
        if not batch:
            return 0
        n = 0
        for job in batch.jobs:
            if self.cancel_job(job.job_id):
                n += 1
        return n

    def retry(self, job_id: str, config: dict | None = None) -> bool:
        """重置一个失败/取消的 job 并重新入池。"""
        job = self.get_job(job_id)
        if not job:
            return False
        with job._lock:
            if job.status == "running":
                return False
            job.status = "pending"
            job.error = None
            job.signal = ""
            job.completed_stages = []
            job.stage_reports = {}
            job.current_stage = ""
            job.started_at = None
            job.finished_at = None
            job.elapsed = 0.0
            job._cancel_requested = False

        # 用一个临时 batch 提交这个 job
        executor = self._get_executor()
        executor.submit(self._run_one, "", job.job_id, config or {})
        return True

    def wait_for_batch(self, batch_id: str, timeout: float = 300.0) -> bool:
        """阻塞直到 batch 内所有 job 都到终态,或超时。返回是否完整完成。"""
        deadline = time.time() + timeout
        batch = self.get_batch(batch_id)
        if not batch:
            return True
        terminal = {"completed", "error", "cancelled"}
        while time.time() < deadline:
            with self._store_lock:
                statuses = [j.status for j in batch.jobs]
            if all(s in terminal for s in statuses):
                return True
            time.sleep(0.2)
        return False

    # ── Lookup ─────────────────────────────────────────────────────────────────

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


def get_job_queue() -> JobQueue:
    return JobQueue.get_instance()