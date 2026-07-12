# 定时分析 v0.6.0 — Design (Context / Goals / Decisions / Architecture / File-by-File)

## Context (现状)

v0.5.0 已有:
- `backend/core/job_queue.py` (500 行, JobQueue 单例 + ThreadPoolExecutor + 状态机 + 持久化)
- `web/components/batch_panel.py` (批量 UI)
- `web/components/portfolio_*.py` (7 文件, 持仓模块)
- `backend/core/portfolio_store.py` (单例 + RLock + JSON)
- hermes 已在 PC + 树莓派 (Pi 已装 podman 5.4.2 + hello-world 跑通)

## Goals

| # | 目标 |
|---|---|
| G1 | 用户能在 streamlit UI 上**随时配置**定时分析 (新增/编辑/启停/删除) |
| G2 | scheduler 后台跑, 用户无需开 streamlit |
| G3 | scheduler 跑完自动通知 (WeCom / Email / Desktop / Log) |
| G4 | 与现有 portfolio 联动 (持仓 ticker 自动分析) |
| G5 | 与现有 job_queue 联动 (复用 batch 任务调度) |

## Decisions (8 个技术决策)

### Decision 1: cron 表达式用 croniter
- **理由**: Python 事实标准, 0 依赖, 1KB, 2 亿次下载
- **不用**: APScheduler (大, 自带 job store 不需要)

### Decision 2: 调度是 polling, 不是事件驱动
- 60s tick 后台 thread
- 不用 Linux cron / at, 原因: 跨平台, 重启 streamlit 不丢任务 (持久化 JSON)

### Decision 3: scheduler 与 job_queue 严格分层
- scheduler = 上层 (cron 触发 ticker 源)
- job_queue = 下层 (执行)
- scheduler **永远不重写** job_queue
- scheduler 调 `job_queue.create_batch() + submit()` 然后注册 `BatchStatus` 回调

### Decision 4: ticker 源
- 持仓: `PortfolioStore.list_positions()` (你已有 3 条)
- 自选股: `WatchlistStore.list()` (新增)
- 手动: scheduler 配置里直接列
- **MVP: 持仓 + 自选股 + 手动**

### Decision 5: 通知模板
- 默认: Jinja2 模板, 摘要式 (`"⏰ {name} 完成: {ok} {partial} {error}  耗时 {duration}s"`)
- 高级用户可改 notify_template
- 失败 fallback: log 永远写, 其他 channel 失败不影响 scheduler

### Decision 6: 时区
- 硬编 Asia/Shanghai
- cron 表达式按本地时区
- 不用 UTC, 因为用户在中国

### Decision 7: 配置持久化
- 单文件 + 文件 lock (`fcntl.flock` 跨进程)
- 改 schedule → 立即 in-memory 更新 + 同步写 JSON
- streamlit 重启时 `Scheduler.get_instance().start()` 自动恢复

### Decision 8: 测试覆盖率
- 目标 ≥ 80% (跟 v0.5.0 portfolio 一致)
- scheduler.py 关键路径 100% 覆盖
- 通知 / watchlist ≥ 80%

## Architecture (架构)

```
┌──────────────────────────────────────────────────────┐
│  streamlit 8501 (UI)                                 │
│  ┌────────────────────────────────────────────────┐  │
│  │ ⏰ schedule_panel.py  (主页面)                 │  │
│  │  - 4 段布局 (列表/编辑/历史/全局)              │  │
│  │  - st_autorefresh 10s                          │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │ schedule_dialogs.py (新增/编辑 modal)          │  │
│  │  - cron helper (5 预置)                        │  │
│  │  - 表单: name / cron / source / notify / config │  │
│  └────────────────────────────────────────────────┘  │
└──────────────┬───────────────────────────────────────┘
               │ st.session_state + Scheduler.update_schedule()
               ▼
┌──────────────────────────────────────────────────────┐
│  backend/core/scheduler.py  (单例 + 1 thread)        │
│  - Schedule / ScheduleRun dataclass                  │
│  - _tick() 每 60s: 算哪些该跑                       │
│  - _run_schedule(): 拉 ticker → create_batch        │
│  - 持久化: ~/.tradingagents/schedules/schedules.json │
│  - 审计: ~/.tradingagents/schedules/runs/*.jsonl     │
└──────────────┬───────────────────────────────────────┘
               │ create_batch() + submit()
               ▼
┌──────────────────────────────────────────────────────┐
│  backend/core/job_queue.py  (复用 v0.5.0)            │
│  - 跑 batch (threading + ThreadPoolExecutor)         │
│  - 调 web/runner.run_analysis_in_thread()            │
│  - 完成回调: BatchStatus.on_complete                  │
└──────────────┬───────────────────────────────────────┘
               │ 回调
               ▼
┌──────────────────────────────────────────────────────┐
│  backend/core/notifier.py  (新)                      │
│  - 4 channel: WeCom / Email / Desktop / Log          │
│  - Jinja2 模板渲染                                   │
│  - 失败不影响 scheduler                              │
└──────────────────────────────────────────────────────┘
```

## File-by-File Spec

### 1. `backend/core/scheduler.py` (350 行)

```python
"""Scheduled analysis - cron + ticker source + job_queue."""
from __future__ import annotations
import croniter
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor  # 给 run_now 用
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

SCHEDULES_DIR = Path.home() / ".tradingagents" / "schedules"
SCHEDULES_FILE = SCHEDULES_DIR / "schedules.json"
RUNS_DIR = SCHEDULES_DIR / "runs"

VALID_CRON_HELPERS = {
    "工作日 18:00": "0 18 * * 1-5",
    "周一早 8:00": "0 8 * * 1",
    "每天 9:30": "30 9 * * *",
    "每月 1 号": "0 9 1 * *",
    "每 4 小时": "0 */4 * * *",
}

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

@dataclass
class Schedule:
    schedule_id: str
    name: str
    cron_expr: str
    source_type: SourceType
    source_config: dict = field(default_factory=dict)  # MANUAL: {"tickers": [...]} WATCHLIST: {"tag": "..."}
    enabled: bool = True
    notify_channels: list[str] = field(default_factory=lambda: ["log"])
    notify_template: str = "v0.6.0 default"
    config: dict = field(default_factory=dict)  # LLM config 透传 job_queue
    last_run_at: float | None = None
    last_run_batch_id: str | None = None
    last_run_status: str = RunStatus.NEVER.value
    last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    created_by: str = "user"

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "Schedule": ...

    def next_run_at(self, now: float | None = None) -> float | None:
        """下次执行时间 (unix ts) 或 None (cron 无效)."""
        try:
            itr = croniter(self.cron_expr, now or time.time())
            return next(itr)
        except Exception:
            return None

    def validate(self) -> str | None:
        """返回 None = ok, 或错误信息."""
        if not self.name.strip():
            return "名称不能为空"
        if not self.cron_expr.strip():
            return "cron 不能为空"
        if self.next_run_at() is None:
            return f"cron 表达式无效: {self.cron_expr!r}"
        if self.source_type == SourceType.MANUAL:
            tickers = self.source_config.get("tickers", [])
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

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "ScheduleRun": ...


class Scheduler:
    """单例, 后台 thread 每 60s tick."""
    _instance: "Scheduler | None" = None
    _init_lock = threading.Lock()
    _rlock = threading.RLock()
    POLL_INTERVAL = 60.0
    MAX_RUN_HISTORY_DAYS = 30

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sched-")
        self._schedules: dict[str, Schedule] = {}  # id -> Schedule
        self._last_tick_at: float | None = None
        SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def get_instance(cls) -> "Scheduler": ...
    def start(self) -> None: ...  # 启后台 thread (幂等)
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...

    # CRUD
    def add_schedule(self, sched: Schedule) -> str: ...  # 返回 schedule_id
    def update_schedule(self, sched: Schedule) -> str: ...
    def delete_schedule(self, schedule_id: str) -> bool: ...
    def list_schedules(self, enabled_only: bool = False) -> list[Schedule]: ...
    def get_schedule(self, schedule_id: str) -> Schedule | None: ...
    def pause_schedule(self, schedule_id: str) -> bool: ...
    def resume_schedule(self, schedule_id: str) -> bool: ...
    def run_now(self, schedule_id: str) -> str: ...  # 返回 batch_id
    def last_tick_at(self) -> float | None: ...

    #内部
    def _tick(self) -> None: ...  # 每 60s 算哪些该跑
    def _run_schedule(self, sched: Schedule) -> None: ...  # 真跑
    def _load_tickers(self, source: SourceType, cfg: dict) -> list[str]: ...
    def _load(self) -> None: ...  # 从 JSON 恢复
    def _save(self) -> None: ...  # 写 JSON (原子)
    def _append_run(self, run: ScheduleRun) -> None: ...
    def _prune_old_runs(self) -> None: ...  # 清 30 天前
    def _file_lock(self, fn): ...  # 上下文管理器 (fcntl)
    def _load_tickers_for_source(self, source: SourceType, cfg: dict) -> list[str]:
        """portfolio: 调 portfolio_store; watchlist: 调 watchlist_store; manual: 读 cfg."""
        if source == SourceType.PORTFOLIO:
            from backend.core.portfolio_store import get_portfolio_store
            store = get_portfolio_store()
            return [p.ticker for p in store.list_positions()]
        elif source == SourceType.WATCHLIST:
            from backend.core.watchlist import get_watchlist_store
            store = get_watchlist_store()
            tag = cfg.get("tag")
            return [e.ticker for e in store.list(tag=tag)]
        else:  # MANUAL
            return list(cfg.get("tickers", []))
```

### 2. `backend/core/watchlist.py` (150 行)

```python
"""Watchlist store - 自选股 (跟 portfolio_store 风格一致)."""
from __future__ import annotations
import json
import logging
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

WATCHLIST_FILE = Path.home() / ".tradingagents" / "watchlist.json"
TICKER_RE = re.compile(r"^\d{6}$")
VALID_TAGS = {"长线", "短线", "观察", "T0", "T1", "T2"}

@dataclass
class WatchEntry:
    entry_id: str  # uuid4 前 12 位
    ticker: str  # 6 位
    tag: str = "观察"
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "WatchEntry": ...

class WatchlistStore:
    """单例 + RLock, JSON 持久化."""
    _instance = None
    _init_lock = threading.Lock()
    _rlock = threading.RLock()

    def __init__(self):
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, WatchEntry] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "WatchlistStore": ...

    def add(self, ticker: str, tag: str = "观察", note: str = "") -> str:
        if not TICKER_RE.match(ticker):
            raise ValueError(f"ticker 必须是 6 位: {ticker!r}")
        if tag not in VALID_TAGS:
            raise ValueError(f"tag 必须是 {VALID_TAGS} 之一: {tag!r}")
        entry = WatchEntry(entry_id=uuid.uuid4().hex[:12], ticker=ticker, tag=tag, note=note)
        with self._rlock:
            self._entries[entry.entry_id] = entry
            self._save()
        return entry.entry_id

    def remove(self, entry_id: str) -> bool: ...
    def list(self, tag: str | None = None) -> list[WatchEntry]: ...  # tag 过滤
    def count(self) -> int: ...
    def _load(self) -> None: ...
    def _save(self) -> None: ...
```

### 3. `backend/core/notifier.py` (200 行)

```python
"""Multi-channel notifier for schedule completion."""
from __future__ import annotations
import json
import logging
import os
import smtplib
import sys
from dataclasses import dataclass
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any

import jinja2

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = """⏰ {{ schedule_name }} {{ status_emoji }} {{ status_text }}
- 开始: {{ started_at }}
- 耗时: {{ duration }}s
- 摘要: {{ summary }}
- batch_id: {{ batch_id }}
- 详情: 查看 ~/.tradingagents/schedules/runs/{{ run_id }}.json
"""

class Channel(str, Enum):
    WECOM = "wecom"
    EMAIL = "email"
    DESKTOP = "desktop"
    LOG = "log"

class ChannelConfig:
    """用户配置: 在 ~/.tradingagents/schedules/channels.yaml."""
    wecom_webhook: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_to: str | None = None

class Notifier:
    """单例, 多 channel 发送通知."""
    def __init__(self):
        self._env = jinja2.Environment()
        self._config = self._load_config()

    def _load_config(self) -> ChannelConfig: ...  # 从 ~/.tradingagents/schedules/channels.yaml
    def send(self, channels: list[str], schedule_name: str, run_data: dict) -> dict[str, bool]:
        """返回每个 channel 成功/失败."""
        results = {}
        for ch in channels:
            try:
                self._send_one(ch, schedule_name, run_data)
                results[ch] = True
            except Exception as e:
                logger.warning(f"通知 channel {ch} 失败: {e}")
                results[ch] = False
        return results

    def _send_one(self, channel: str, schedule_name: str, run_data: dict) -> None:
        text = self._render(schedule_name, run_data)
        if channel == Channel.WECOM:
            self._send_wecom(text)
        elif channel == Channel.EMAIL:
            self._send_email(schedule_name, text)
        elif channel == Channel.DESKTOP:
            self._send_desktop(schedule_name, text)
        elif channel == Channel.LOG:
            logger.info(f"[notify] {schedule_name}: {text}")

    def _render(self, schedule_name, run_data) -> str: ...
    def _send_wecom(self, text: str) -> None:
        # 用 webhook, 失败 raise
        import requests
        r = requests.post(self._config.wecom_webhook, json={"msgtype": "markdown", "markdown": {"content": text}}, timeout=10)
        r.raise_for_status()
    def _send_email(self, subject, body) -> None: ...
    def _send_desktop(self, title, body) -> None:
        """Linux 桌面通知 (用 notify-send 或 zenity)."""
        subprocess.run(["notify-send", title, body], check=False)
```

### 4. `cli/schedule.py` (180 行)

```python
"""CLI: schedule list/add/pause/resume/run-now/delete."""
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False)
console = Console()

@app.command()
def list(enabled_only: bool = False):
    """列出所有 schedule."""
    from backend.core.scheduler import Scheduler
    s = Scheduler.get_instance()
    for sched in s.list_schedules(enabled_only=enabled_only):
        ...

@app.command()
def add(name: str, cron: str, source: str = "portfolio", tickers: str = "", tag: str = ""):
    """新增 schedule. --tickers "600595,688017" 或 --tag 长线 (watchlist)."""
    ...

@app.command()
def run_now(schedule_id: str):
    """立即跑一次."""
    ...

@app.command()
def pause(schedule_id: str): ...
@app.command()
def resume(schedule_id: str): ...
@app.command()
def delete(schedule_id: str): ...
@app.command()
def runs(schedule_id: str = "", limit: int = 20):
    """看运行历史."""
    ...

if __name__ == "__main__":
    app()
```

### 5. `web/components/schedule_panel.py` (280 行)

```python
"""⏰ 定时分析主页面 (4 段布局)."""
from __future__ import annotations
import streamlit as st
from streamlit_autorefresh import st_autorefresh

def render_schedule_panel() -> None:
    # 1. 自动刷新 (10s)
    st_autorefresh(interval=10 * 1000, key="schedules_refresh")
    
    # 2. 标题 + 工具栏
    st.markdown("## ⏰ 定时分析")
    cols = st.columns([1, 1, 1, 1])
    with cols[0]: 
        if st.button("➕ 新增", use_container_width=True):
            st.session_state.editing_schedule = "new"
    with cols[1]: 
        if st.button("▶ 立即跑全部", use_container_width=True):
            # 跑所有 enabled=true
            ...
    with cols[2]: 
        if st.button("⏸ 停止调度器", use_container_width=True):
            ...
    with cols[3]: 
        if st.button("⟳ 刷新", use_container_width=True):
            st.rerun()
    
    # 3. 段 1: 调度列表
    _render_schedule_list()
    
    # 4. 段 2: 新增/编辑 dialog
    if st.session_state.get("editing_schedule"):
        _render_edit_dialog()
    
    # 5. 段 3: 运行历史
    _render_runs_history()
    
    # 6. 段 4: 全局状态
    _render_global_status()

def _render_schedule_list(): ...
def _render_edit_dialog(): ...
def _render_runs_history(): ...
def _render_global_status(): ...
```

### 6. `web/components/schedule_dialogs.py` (220 行)

```python
"""Add/Edit schedule dialogs with cron picker."""
from __future__ import annotations
import streamlit as st
from croniter import croniter

CRON_HELPERS = {
    "工作日 18:00": "0 18 * * 1-5",
    "周一早 8:00": "0 8 * * 1",
    "每天 9:30": "30 9 * * *",
    "每月 1 号": "0 9 1 * *",
    "每 4 小时": "0 */4 * * *",
}

@st.dialog("新增 / 编辑 schedule")
def _add_edit_dialog(schedule_id: str | None = None):
    # name / cron / source / notify / model / enabled
    ...
    # cron helper 5 个按钮 (一键填入)
    ...
    # ticker 源: 持仓 / 自选 / 手动
    ...
    # 通知: 4 个 checkbox
    ...
    # 预览: 下次执行时间 (用 croniter.get_next())
    next_run = croniter(cron_expr, time.time()).get_next()
    st.caption(f"⏰ 下次执行: {next_run}")
```

### 7. 测试文件 (4 个)

| 文件 | 行 | 测试数 |
|---|---|---|
| `tests/test_scheduler.py` | 300 | 25 (cron 匹配 / tick / 源 / 通知 / 持久化) |
| `tests/test_watchlist.py` | 100 | 10 (CRUD / tag / 持久化 / 并发) |
| `tests/test_notifier.py` | 150 | 10 (4 channel / 模板 / 失败) |
| `tests/test_schedule_panel.py` | 200 | 10 (4 段 / 新增 / 编辑 / 启停) |

## Migration / 风险

| 风险 | 缓解 |
|---|---|
| 配置文件并发写 | fcntl.flock 锁 |
| cron 表达式错误 | `validate()` 函数 + UI 红字 |
| scheduler 线程 hang | daemon thread + join(timeout) |
| 用户误删 schedule | 二次确认 dialog |
| 通知 channel 阻 | log 永远写, 其他失败 fallback |
| 树莓派跑 cron 但 token 缺 | 配置文件 (.env.example 留 TODO) |
