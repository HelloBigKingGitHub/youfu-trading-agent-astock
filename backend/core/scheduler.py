"""Scheduled analysis — cron + ticker source + job_queue + notifier.

设计要点：
  * 单例 Scheduler，后台 daemon thread 每 60s tick 一次
  * Schedule = cron + source_type (portfolio/watchlist/manual) + notify channels
  * ticker source：portfolio → PortfolioStore.list_positions / watchlist → WatchlistStore / manual → 配置
  * 跑批：JobQueue.create_batch + submit（不复用 web runner，全部经 job_queue 这条路）
  * 完成回调 → Notifier.send + 写 runs/YYYY-MM-DD.jsonl（审计）
  * 持久化：~/.tradingagents/schedules/schedules.json（原子写）
  * 30 天前 run 自动 prune
  * 预置 2 schedule：每日持仓复盘（enabled=默认启用）+ 周一前瞻（默认禁用）
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


# ── 模块级别导入（让测试可以 `patch("backend.core.scheduler.JobQueue")`） ────
# 这些类在测试里被 patch，所以必须是 module-level attribute。
from backend.core.job_queue import JobQueue as JobQueue  # noqa: E402, F401
from backend.core.portfolio_store import (  # noqa: E402, F401
    PortfolioStore as PortfolioStore,
)
from backend.core.watchlist import WatchlistStore as WatchlistStore  # noqa: E402, F401
from backend.core.notifier import Notifier as Notifier  # noqa: E402, F401


# ── 路径常量（模块级暴露 `SCHEDULES_FILE` / `RUNS_DIR` 以便测试 monkeypatch）──

_SCHEDULES_DIR: Path = Path.home() / ".tradingagents" / "schedules"
SCHEDULES_DIR: Path = _SCHEDULES_DIR
SCHEDULES_FILE: Path = _SCHEDULES_DIR / "schedules.json"
RUNS_DIR: Path = _SCHEDULES_DIR / "runs"


# ── 5 个常用 cron helper（UI 与 CLI 一致） ──────────────────────────────────

VALID_CRON_HELPERS: dict[str, str] = {
    "工作日 18:00": "0 18 * * 1-5",
    "周一早 8:00": "0 8 * * 1",
    "每天 9:30": "30 9 * * *",
    "每月 1 号": "0 9 1 * *",
    "每 4 小时": "0 */4 * * *",
}


# ── Enums ──────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    PORTFOLIO = "portfolio"
    WATCHLIST = "watchlist"
    MANUAL = "manual"


class RunStatus(str, Enum):
    NEVER = "never"
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    SKIPPED = "skipped"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class Schedule:
    schedule_id: str
    name: str
    cron_expr: str
    source_type: SourceType
    source_config: dict = field(default_factory=dict)
    enabled: bool = True
    notify_channels: list[str] = field(default_factory=lambda: ["log"])
    notify_template: str = "v0.6.0 default"
    config: dict = field(default_factory=dict)
    last_run_at: float | None = None
    last_run_batch_id: str | None = None
    last_run_status: str = RunStatus.NEVER.value
    last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    created_by: str = "user"

    def to_dict(self) -> dict:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "cron_expr": self.cron_expr,
            "source_type": self.source_type.value if isinstance(self.source_type, SourceType) else self.source_type,
            "source_config": dict(self.source_config),
            "enabled": self.enabled,
            "notify_channels": list(self.notify_channels),
            "notify_template": self.notify_template,
            "config": dict(self.config),
            "last_run_at": self.last_run_at,
            "last_run_batch_id": self.last_run_batch_id,
            "last_run_status": self.last_run_status,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        st = d.get("source_type", "portfolio")
        try:
            src = SourceType(st)
        except ValueError:
            src = SourceType.PORTFOLIO
        return cls(
            schedule_id=d.get("schedule_id") or _new_id(),
            name=d.get("name", ""),
            cron_expr=d.get("cron_expr", ""),
            source_type=src,
            source_config=dict(d.get("source_config", {})),
            enabled=bool(d.get("enabled", True)),
            notify_channels=list(d.get("notify_channels", ["log"])),
            notify_template=d.get("notify_template", "v0.6.0 default"),
            config=dict(d.get("config", {})),
            last_run_at=d.get("last_run_at"),
            last_run_batch_id=d.get("last_run_batch_id"),
            last_run_status=d.get("last_run_status", RunStatus.NEVER.value),
            last_error=d.get("last_error"),
            created_at=float(d.get("created_at", time.time())),
            created_by=d.get("created_by", "user"),
        )

    def next_run_at(self, now: float | None = None) -> float | None:
        """下次执行时间（unix ts），cron 无效则 None。"""
        try:
            from croniter import croniter
            base = time.time() if now is None else now
            itr = croniter(self.cron_expr, base)
            return float(next(itr))
        except Exception:  # noqa: BLE001 —— croniter 抛各种 ValidationError
            return None

    def validate(self) -> str | None:
        """返回 None = OK，否则为错误信息。"""
        if not (self.name or "").strip():
            return "名称不能为空"
        if not (self.cron_expr or "").strip():
            return "cron 表达式不能为空"
        if self.next_run_at() is None:
            return f"cron 表达式无效: {self.cron_expr!r}"
        if self.source_type == SourceType.MANUAL:
            tickers = self.source_config.get("tickers") or []
            if not tickers:
                return "手动源必须指定 tickers"
        return None


@dataclass
class ScheduleRun:
    run_id: str
    schedule_id: str
    started_at: float
    finished_at: float | None = None
    status: str = "running"
    batch_id: str | None = None
    job_ids: list[str] = field(default_factory=list)
    duration: float = 0.0
    summary: str = ""
    error: str | None = None
    ticker_count: int = 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "schedule_id": self.schedule_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "batch_id": self.batch_id,
            "job_ids": list(self.job_ids),
            "duration": self.duration,
            "summary": self.summary,
            "error": self.error,
            "ticker_count": self.ticker_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleRun":
        return cls(
            run_id=d.get("run_id") or _new_id(),
            schedule_id=d.get("schedule_id", ""),
            started_at=float(d.get("started_at", time.time())),
            finished_at=d.get("finished_at"),
            status=d.get("status", "running"),
            batch_id=d.get("batch_id"),
            job_ids=list(d.get("job_ids", [])),
            duration=float(d.get("duration", 0.0)),
            summary=d.get("summary", ""),
            error=d.get("error"),
            ticker_count=int(d.get("ticker_count", 0)),
        )


# ── Scheduler ───────────────────────────────────────────────────────────────


class Scheduler:
    """单例后台调度器。

    公开接口：add/update/delete/list/get/pause/resume/run_now，
    线程控制：start/stop/is_running/last_tick_at，
    内部：_tick / _run_schedule / _load / _save / _append_run / _prune_old_runs。
    """

    _instance: "Scheduler | None" = None
    _init_lock = threading.Lock()

    POLL_INTERVAL = 60.0
    MAX_RUN_HISTORY_DAYS = 30

    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="sched-runnow-"
        )
        self._schedules: dict[str, Schedule] = {}
        self._last_tick_at: float | None = None
        self._ensure_dirs()
        self._load()

    @classmethod
    def get_instance(cls) -> "Scheduler":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_singleton(cls) -> None:
        """测试用：关闭后台 thread + 清空单例。"""
        with cls._init_lock:
            if cls._instance is not None:
                cls._instance.stop()
                try:
                    cls._instance._executor.shutdown(wait=False)
                except Exception:  # noqa: BLE001
                    pass
            cls._instance = None

    # ── Public ────────────────────────────────────────────────────────────

    def add_schedule(self, sched: Schedule) -> str:
        """新增。返回 schedule_id（自动补 schedule_id / created_at）。"""
        err = sched.validate()
        if err:
            raise ValueError(err)
        with self._rlock:
            if not sched.schedule_id:
                sched.schedule_id = _new_id()
            sched.created_at = sched.created_at or time.time()
            self._schedules[sched.schedule_id] = sched
            self._save()
            return sched.schedule_id

    def update_schedule(self, sched: Schedule) -> None:
        """用 Schedule 对象原地替换（schedule_id 不可改）。"""
        with self._rlock:
            existing = self._schedules.get(sched.schedule_id)
            if existing is None:
                raise KeyError(f"schedule_id {sched.schedule_id!r} not found")
            err = sched.validate()
            if err:
                raise ValueError(err)
            self._schedules[sched.schedule_id] = sched
            self._save()

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._rlock:
            if schedule_id not in self._schedules:
                return False
            del self._schedules[schedule_id]
            self._save()
            return True

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        with self._rlock:
            return self._schedules.get(schedule_id)

    def list_schedules(self, enabled_only: bool = False) -> list[Schedule]:
        with self._rlock:
            items = list(self._schedules.values())
        if enabled_only:
            items = [s for s in items if s.enabled]
        items.sort(key=lambda s: (s.name, s.schedule_id))
        return items

    def pause_schedule(self, schedule_id: str) -> bool:
        return self._toggle(schedule_id, False)

    def resume_schedule(self, schedule_id: str) -> bool:
        return self._toggle(schedule_id, True)

    def _toggle(self, schedule_id: str, enabled: bool) -> bool:
        with self._rlock:
            sched = self._schedules.get(schedule_id)
            if sched is None:
                return False
            sched.enabled = enabled
            self._save()
            return True

    def run_now(self, schedule_id: str) -> str:
        """立即跑（异步）。返回一个 batch_id 占位串（不存在则 raise KeyError）。

        batch 真实创建在 `_run_schedule` 内异步完成；这里先返回一个
        `run-{short_id}` 字符串，让 CLI `run-now` 能立即 ack。
        """
        with self._rlock:
            sched = self._schedules.get(schedule_id)
            if sched is None:
                raise KeyError(f"schedule_id {schedule_id!r} not found")
            sched_copy = Schedule.from_dict(sched.to_dict())

        placeholder_bid = f"run-{_new_id()[:10]}"
        future = self._executor.submit(self._run_schedule, sched_copy, True)
        with self._rlock:
            sched._last_future = future  # type: ignore[attr-defined]
        return placeholder_bid

    # ── Daemon thread ─────────────────────────────────────────────────────

    def start(self) -> None:
        """启动后台 polling thread（幂等）。"""
        with self._rlock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._tick_loop,
                name="scheduler-tick",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._rlock:
            ev = self._stop_event
            t = self._thread
            self._thread = None
        if t is None:
            return
        ev.set()
        t.join(timeout=timeout)

    def is_running(self) -> bool:
        with self._rlock:
            t = self._thread
        return t is not None and t.is_alive()

    def last_tick_at(self) -> float | None:
        with self._rlock:
            return self._last_tick_at

    def _tick_loop(self) -> None:
        """后台 daemon thread 主循环。"""
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("scheduler _tick 出错: %s", exc)
            if self._stop_event.wait(timeout=self.POLL_INTERVAL):
                break

    def _tick(self) -> None:
        """每 60s 调用一次：算哪些 schedule 该跑。

        判定语义：
          1. 首次运行 (last_run_at=None)：用 cron 在「最近 5 分钟内」是否有过触发点。
             prev <= now 且 (now - prev) <= 300 → 立即跑一次。
             - `* * * * *`：prev = 当前分钟起点（30s 前）→ 跑
             - `0 18 * * 1-5`：prev = 上个工作日 18:00（数小时前）→ 不跑
             - `0 0 1 1 *`：prev = 上个 1 月 1 日（半年以上前）→ 不跑
          2. 正常运行：next_run_at(last_run) ≤ now 即视为到期。
        """
        now = time.time()
        with self._rlock:
            self._last_tick_at = now
            items = list(self._schedules.values())
        try:
            self._prune_old_runs()
        except Exception as exc:  # noqa: BLE001
            logger.warning("_prune_old_runs 失败: %s", exc)
        for sched in items:
            if not sched.enabled:
                continue
            last_run = sched.last_run_at
            if last_run is None:
                # 首次运行：仅当 cron 近期（≤5min）刚触发过时跑一次
                prev = self._prev_run_at(sched, now)
                if prev is None or now - prev > 300:
                    continue
                self._dispatch(sched, now)
                continue
            nra = sched.next_run_at(last_run)
            if nra is None:
                continue
            if nra <= now:
                self._dispatch(sched, now)

    def _dispatch(self, sched: Schedule, now: float) -> None:
        """提交 _run_schedule 到 executor + 更新 last_run_at。"""
        try:
            self._executor.submit(self._run_schedule, sched, False)
            with self._rlock:
                sched.last_run_at = now
                self._save()
        except Exception as exc:  # noqa: BLE001
            logger.warning("_run_schedule 提交失败: %s", exc)

    def _prev_run_at(self, sched: Schedule, now: float) -> float | None:
        """返回 cron 在 now 之前最近一次触发点（unix ts）。cron 无效则 None。"""
        try:
            from croniter import croniter
            itr = croniter(sched.cron_expr, now)
            return float(itr.get_prev())
        except Exception:  # noqa: BLE001
            return None

    def _prev_run_at(self, sched: Schedule, now: float) -> float | None:
        """返回 cron 在 now 之前最近一次触发点（unix ts）。cron 无效则 None。"""
        try:
            from croniter import croniter
            itr = croniter(sched.cron_expr, now)
            return float(itr.get_prev())
        except Exception:  # noqa: BLE001
            return None

    # ── _run_schedule ─────────────────────────────────────────────────────

    def _run_schedule(
        self,
        sched: Schedule,
        manual: bool = False,
    ) -> None:
        """真正执行一个 schedule。同步（线程内阻塞）。"""
        import datetime as _dt
        run_id = _new_id()
        started_at = time.time()
        run = ScheduleRun(
            run_id=run_id,
            schedule_id=sched.schedule_id,
            started_at=started_at,
        )
        try:
            tickers = self._load_tickers_for_source(
                sched.source_type, sched.source_config
            )
            if not tickers:
                run.status = RunStatus.SKIPPED.value
                run.summary = "无 ticker 可跑（持仓为空 / 自选股空 / 手动列表空）"
                run.finished_at = time.time()
                run.duration = run.finished_at - started_at
                self._append_run(run)
                self._update_after_run(sched, run)
                self._notify(sched, run)
                return

            run.ticker_count = len(tickers)
            trade_date = _dt.date.today().strftime("%Y-%m-%d")
            requests = [
                {"ticker": t, "trade_date": trade_date} for t in tickers
            ]
            self._append_run(run)

            q = JobQueue.get_instance()
            batch_id, batch = q.create_batch(requests)
            run.batch_id = batch_id
            run.job_ids = [j.job_id for j in batch.jobs]

            q.wait_for_batch(batch_id, timeout=600.0)
            batch = q.get_batch(batch_id)
            if batch is None:
                raise RuntimeError(f"batch {batch_id} disappeared")
            statuses = [j.status for j in batch.jobs]
            n_ok = sum(1 for s in statuses if s == "completed")
            n_err = sum(1 for s in statuses if s == "error")
            n_cxl = sum(1 for s in statuses if s == "cancelled")
            n_total = len(statuses)
            if n_ok == n_total:
                run.status = RunStatus.OK.value
            elif n_err == n_total or (n_ok == 0 and n_err > 0):
                run.status = RunStatus.ERROR.value
            else:
                run.status = RunStatus.PARTIAL.value
            run.summary = f"ok={n_ok} error={n_err} cancelled={n_cxl} total={n_total}"
            run.finished_at = time.time()
            run.duration = run.finished_at - started_at

            self._append_run(run)
            self._update_after_run(sched, run)
            self._notify(sched, run)
        except Exception as exc:  # noqa: BLE001
            run.status = RunStatus.ERROR.value
            run.error = str(exc)[:500]
            run.finished_at = time.time()
            run.duration = run.finished_at - started_at
            self._append_run(run)
            self._update_after_run(sched, run, error_msg=run.error)
            try:
                self._notify(sched, run)
            except Exception:  # noqa: BLE001
                pass

    def _complete_run_after_batch(
        self,
        sched: Schedule,
        batch: Any,
        tickers: list[str],
    ) -> None:
        """run_now 的延后路径：batch 已创建（run_now 内），这里只完成 + 通知。"""
        import datetime as _dt
        run_id = _new_id()
        started_at = time.time()
        run = ScheduleRun(
            run_id=run_id,
            schedule_id=sched.schedule_id,
            started_at=started_at,
        )
        try:
            q = JobQueue.get_instance()
            bid = batch.batch_id
            run.batch_id = bid
            run.job_ids = [j.job_id for j in batch.jobs]
            run.ticker_count = len(tickers)
            trade_date = _dt.date.today().strftime("%Y-%m-%d")
            self._append_run(run)

            q.wait_for_batch(bid, timeout=600.0)
            batch_now = q.get_batch(bid)
            if batch_now is None:
                raise RuntimeError(f"batch {bid} disappeared")
            statuses = [j.status for j in batch_now.jobs]
            n_ok = sum(1 for s in statuses if s == "completed")
            n_err = sum(1 for s in statuses if s == "error")
            n_cxl = sum(1 for s in statuses if s == "cancelled")
            n_total = len(statuses)
            if n_ok == n_total:
                run.status = RunStatus.OK.value
            elif n_err == n_total or (n_ok == 0 and n_err > 0):
                run.status = RunStatus.ERROR.value
            else:
                run.status = RunStatus.PARTIAL.value
            run.summary = f"ok={n_ok} error={n_err} cancelled={n_cxl} total={n_total}"
            run.finished_at = time.time()
            run.duration = run.finished_at - started_at
            self._append_run(run)
            self._update_after_run(sched, run)
            self._notify(sched, run)
        except Exception as exc:  # noqa: BLE001
            run.status = RunStatus.ERROR.value
            run.error = str(exc)[:500]
            run.finished_at = time.time()
            run.duration = run.finished_at - started_at
            try:
                self._append_run(run)
                self._update_after_run(sched, run, error_msg=run.error)
                self._notify(sched, run)
            except Exception:  # noqa: BLE001
                pass

    def _update_after_run(
        self,
        sched: Schedule,
        run: ScheduleRun,
        error_msg: str | None = None,
    ) -> None:
        with self._rlock:
            cur = self._schedules.get(sched.schedule_id)
            if cur is None:
                return
            cur.last_run_at = run.finished_at or time.time()
            cur.last_run_batch_id = run.batch_id
            cur.last_run_status = run.status
            cur.last_error = error_msg or run.error
            self._save()

    # ── ticker 源 ─────────────────────────────────────────────────────────

    def _load_tickers_for_source(
        self,
        source: SourceType,
        cfg: dict,
    ) -> list[str]:
        """3 种源：
          portfolio → PortfolioStore.list_positions → tickers
          watchlist → WatchlistStore.list(tag=...) → tickers
          manual → cfg['tickers']
        """
        if source == SourceType.PORTFOLIO:
            try:
                from backend.core.portfolio_store import get_portfolio_store
                store = get_portfolio_store()
                return [p.ticker for p in store.list_positions()]
            except Exception as exc:  # noqa: BLE001
                logger.warning("拉 portfolio tickers 失败: %s", exc)
                return []
        if source == SourceType.WATCHLIST:
            try:
                from backend.core.watchlist import get_watchlist_store
                store = get_watchlist_store()
                tag = cfg.get("tag") if cfg else None
                return [e.ticker for e in store.list(tag=tag)]
            except Exception as exc:  # noqa: BLE001
                logger.warning("拉 watchlist tickers 失败: %s", exc)
                return []
        tickers = (cfg or {}).get("tickers") or []
        return [str(t) for t in tickers if str(t).strip()]

    # ── 通知 ─────────────────────────────────────────────────────────────

    def _notify(self, sched: Schedule, run: ScheduleRun) -> None:
        try:
            # 使用模块路径延迟导入，便于测试 patch("backend.core.notifier.Notifier")
            from backend.core.notifier import Notifier as _Notifier
            n = _Notifier.get_instance()
            run_data = run.to_dict()
            run_data["run_id"] = run.run_id
            n.send(sched.notify_channels or ["log"], sched.name, run_data)
        except Exception as exc:  # noqa: BLE001 —— 通知失败绝对不能让调度挂
            logger.warning("通知失败: %s", exc)

    # ── 持久化 ───────────────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """从 schedules.json 恢复。

        Preset 创建规则：
          * 文件不存在 → 创建（首次启动）
          * 文件存在但 JSON 损坏 → 创建（兜底恢复）
          * 文件存在且为合法 JSON（即使为空 `[]`）→ 不创建（用户已显式清空）
        """
        if not SCHEDULES_FILE.exists():
            self._ensure_presets()
            self._save()
            return
        try:
            raw = SCHEDULES_FILE.read_text(encoding="utf-8")
        except OSError:
            self._ensure_presets()
            self._save()
            return
        if not raw.strip():
            # 空文件 → 当作"首次启动"创建 preset
            self._ensure_presets()
            self._save()
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # JSON 损坏 → 兜底恢复
            self._ensure_presets()
            self._save()
            return
        if not isinstance(data, list):
            self._ensure_presets()
            self._save()
            return
        # 文件存在 + 合法 JSON → 不创建 preset（用户主动清空也应保留空状态）
        for d in data:
            try:
                sched = Schedule.from_dict(d)
                self._schedules[sched.schedule_id] = sched
            except Exception as exc:  # noqa: BLE001
                logger.warning("跳过损坏 schedule: %s", exc)

    def _ensure_presets(self) -> None:
        """首次启动创建 2 个预置 schedule（幂等）。"""
        if any(s.name == "每日持仓复盘" for s in self._schedules.values()):
            return
        sched_daily = Schedule(
            schedule_id=_new_id(),
            name="每日持仓复盘",
            cron_expr=VALID_CRON_HELPERS["工作日 18:00"],
            source_type=SourceType.PORTFOLIO,
            source_config={},
            enabled=True,
            notify_channels=["log"],
            notify_template="v0.6.0 default",
            created_by="preset",
        )
        self._schedules[sched_daily.schedule_id] = sched_daily
        sched_monday = Schedule(
            schedule_id=_new_id(),
            name="周一前瞻",
            cron_expr=VALID_CRON_HELPERS["周一早 8:00"],
            source_type=SourceType.PORTFOLIO,
            source_config={},
            enabled=False,
            notify_channels=["log"],
            notify_template="v0.6.0 default",
            created_by="preset",
        )
        self._schedules[sched_monday.schedule_id] = sched_monday
        self._save()

    def _save(self) -> None:
        """原子写 schedules.json。"""
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SCHEDULES_FILE.with_suffix(SCHEDULES_FILE.suffix + ".tmp")
            data = [s.to_dict() for s in self._schedules.values()]
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(SCHEDULES_FILE)
        except OSError as exc:
            logger.warning("_save schedules.json 失败: %s", exc)

    def _append_run(self, run: ScheduleRun) -> None:
        """追加一行 run 到 runs/YYYY-MM-DD.jsonl（按天分文件）。"""
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            day = datetime.fromtimestamp(run.started_at).strftime("%Y-%m-%d")
            path = RUNS_DIR / f"{day}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(run.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("_append_run 失败: %s", exc)

    def _prune_old_runs(self, now: float | None = None) -> int:
        """删除 MAX_RUN_HISTORY_DAYS 天前的 runs/*.jsonl。返回删的文件数。"""
        if not RUNS_DIR.exists():
            return 0
        cutoff = (now or time.time()) - self.MAX_RUN_HISTORY_DAYS * 86400
        removed = 0
        try:
            for path in RUNS_DIR.iterdir():
                if not path.name.endswith(".jsonl"):
                    continue
                date_str = path.name[:10]
                try:
                    file_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
                if file_dt.timestamp() < cutoff:
                    path.unlink()
                    removed += 1
        except OSError as exc:
            logger.warning("_prune_old_runs 失败: %s", exc)
        return removed

    # ── 历史查询（CLI 用） ───────────────────────────────────────────────

    def list_runs(
        self,
        schedule_id: str | None = None,
        limit: int = 20,
    ) -> list[ScheduleRun]:
        """读 runs/*.jsonl，按 started_at 倒序，可按 schedule_id 过滤。"""
        if not RUNS_DIR.exists():
            return []
        out: list[ScheduleRun] = []
        try:
            files = sorted(RUNS_DIR.glob("*.jsonl"), reverse=True)
        except OSError:
            return []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if schedule_id and d.get("schedule_id") != schedule_id:
                    continue
                out.append(ScheduleRun.from_dict(d))
                if len(out) >= limit * 4:
                    break
            if len(out) >= limit * 4:
                break
        out.sort(key=lambda r: r.started_at, reverse=True)
        return out[:limit]


# ── 模块级 helper ────────────────────────────────────────────────────────────


def _install_presets() -> None:
    """模块级 helper：调用 Scheduler.get_instance() 确保 2 个预置已建。

    幂等 —— 已存在则 no-op。CLI / install script 调用入口。
    """
    SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    s = Scheduler.get_instance()
    s._ensure_presets()
    s._save()


def get_scheduler() -> Scheduler:
    """模块级便捷访问。"""
    return Scheduler.get_instance()
