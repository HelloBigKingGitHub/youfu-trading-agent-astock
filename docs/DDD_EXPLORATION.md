# Youfu-Trading-Agent-Astock DDD 领域模型探索 (read-only)

> **范围**: 13 个 `backend/core/` 模块的战术设计 + 代码现状 (read-only)
> **git HEAD**: `33b3a42` (P2.25 修 tracker + history_store + runner ID 一致性)
> **方法**: 逐文件读取 + `grep` 类定义, 提取 dataclass + 字段 + 不变量 + 持久化 + 已有事件性调用
> **不修改**: source code / pytest / pyproject.toml / spec
> **关系**: 战略设计已在 `docs/DDD_ANALYSIS.md` (654 行), 本文件**只做战术 + 代码现状**, 不重复战略层

---

## 0. TL;DR — 13 个聚合根速查

| # | 聚合根 | 模块 | 持久化 | 关键复杂度 |
|---|--------|------|--------|----------|
| 1 | `HistoryEntry` | history_store.py | JSON 文件 (per-id) | 状态机 + zombie/stuck 检测 |
| 2 | `BatchJob` + `Job` | job_queue.py | **in-memory only** | 双层聚合 + ThreadPoolExecutor |
| 3 | `LogTask` (per `{ticker}/{date}_run{NN}/`) | log_store.py | JSONL + meta.json | append-only + 旧结构降级 |
| 4 | `NotificationMessage` (隐式) | notifier.py | **无** (stateless) | Jinja2 模板 + 4 channel |
| 5 | `AlertRule` | portfolio_alerts.py (+ store) | alerts.json (via PortfolioStore) | 7 种 rule + 300s anti-repeat |
| 6 | `Position` | portfolio_store.py | positions.json | 持仓 ↔ Transaction 反向联动 |
| 7 | `Transaction` | portfolio_store.py | transactions.json | 6 种 action + 级联删除 |
| 8 | `Account` | portfolio_store.py | accounts.json | is_default 全局唯一 |
| 9 | `AnalysisTracker` | tracker.py | **in-memory only** (镜像到 HistoryStore) | 阶段状态机 + 600s 超时 |
| 10 | `Schedule` | scheduler.py | schedules.json | cron + 3 种 ticker 源 |
| 11 | `ScheduleRun` | scheduler.py | runs/{date}.jsonl | 30 天 prune |
| 12 | `ImportJob` (隐式) | portfolio_import.py | **无** (stateless parse) | 4 种 CSV 格式 + UTF-8 BOM |
| 13 | `WatchEntry` | watchlist.py | watchlist.json | VALID_TAGS 白名单 |

**Domain Services** (无状态计算函数, 不是聚合根):
- `portfolio_calc.py` — PositionMetrics / PortfolioSummary / XIRR / Sharpe / MaxDD / Brinson

**Application Service** (用例编排):
- `runner.py` — `_run_analysis` + `start_analysis` (thread 入口)

**统计**: 5471 行 backend/core/ 源码, 22 个 dataclass, 14 个 store/service, **0 个 Protocol/ABC** (实测 `grep -n "^class" backend/core/*.py` 全部是具体类).

---

## 1. 13 个聚合根详情 (按代码现状)

> 命名约定: `<Entity>` 字段 + `(可选 VO)` 标注值对象; `状态机` 列出代码中的合法转换.

### 1.1 HistoryEntry — `backend/core/history_store.py` (370 行)

**Root**: `HistoryEntry` (dataclass)

```python
@dataclass
class HistoryEntry:
    analysis_id: str            # PK, 格式 "{ticker}_{trade_date}_{uuid4[:8]}"
    ticker: str
    trade_date: str
    signal: str = ""            # "BUY" / "SELL" / "HOLD"
    elapsed: float = 0.0
    status: str = "pending"     # pending | running | completed | error
    error: str | None = None
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)  # report_key -> 500 字摘要
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    results_path: str = ""      # 指向 full_states_log_*.json
```

- **Entity**: HistoryEntry 本身 (扁平, 无嵌套 entity)
- **Value Objects**:
  - `analysis_id: str` — PK, 复用为 `_run_analysis` 入参 (P2.25 修 ID 一致性)
  - `signal: str` — 来自 LangGraph `final_trade_decision`
  - `stage_reports: dict[report_key, str]` — LangGraph chunk field 映射
- **状态机**:
  ```
  pending ─create()──▶ running ─mark_complete()──▶ completed
                          │
                          └──mark_error()─────▶ error
                          │
                          └──(server restart)──▶ zombie / stuck (P2.21)
  ```
- **Invariants**:
  - `analysis_id` 全局唯一 (UUID4 8 字节保证)
  - `status ∈ {pending, running, completed, error}` (字符串, 未用 Enum)
  - `completed_stages` 单调增 (append-only, 不删除)
- **持久化**:
  - JSON 文件: `~/.tradingagents/logs/history/<analysis_id>.json`
  - 写: `_write()` — 非原子 (直接 `write_text`, 无 `.tmp` + replace)
  - 读: `_read()` — 错误宽容 (JSON 损坏返回 None)
- **Zombie / Stuck 检测**:
  - `ZOMBIE_THRESHOLD_SEC = 60.0` — `status=running` + `elapsed==0` + 60s 未动
  - `STUCK_THRESHOLD_SEC = 600.0` — `status=running` + `elapsed>600s` (P2.21)
  - `cleanup_zombies()` — 启动时 sweep, 把 zombie/stuck 标 error
- **Repository**: `HistoryStore` (singleton, double-checked lock)
- **线程安全**: 类级 `_lock` (单例) + 实例级 `_lock_path` (写保护)

---

### 1.2 BatchJob + Job — `backend/core/job_queue.py` (423 行)

**Root 1**: `BatchJob` (聚合根, 包含 N 个 Job)

```python
@dataclass
class BatchJob:
    batch_id: str                # PK, "batch_{uuid4[:8]}"
    jobs: list[Job]
    created_at: float
    finished_count: int = 0      # ⚠️ 死代码, 实际从未更新 (Job.status 是单一事实源)
    error_count: int = 0         # ⚠️ 死代码, 同上

    @property
    def batch_status(self) -> str:  # 派生属性, 非字段
        # all completed → COMPLETED
        # all error/cancelled → FAILED
        # any running → RUNNING
        # 混合 → PARTIAL
```

**Root 2**: `Job` (子聚合根, 不通过 BatchJob 访问)

```python
@dataclass
class Job:
    job_id: str                  # PK, "{ticker}_{trade_date}_{uuid4[:8]}"
    analysis_id: str             # ⚠️ 与 HistoryEntry.analysis_id 重复 (复用)
    ticker: str
    trade_date: str
    status: str = "pending"      # pending | running | completed | error | cancelled
    current_stage: str = ""
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)
    signal: str = ""
    error: str | None = None
    elapsed: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    _lock: threading.Lock
    _cancel_requested: bool
```

- **Value Objects**:
  - `BatchStatus(str, Enum)` — `PENDING/RUNNING/COMPLETED/PARTIAL/FAILED/CANCELLED`
  - `Ticker` (隐式) — `TICKER_WHITELIST_RE` 校验 6 位 A 股
  - `job_id == analysis_id` — **代码注释明确 "复用为 history entry id"**
- **Invariants**:
  - `jobs` 非空 (创建时至少 1 个)
  - `status` 单向转换 (running → completed/error/cancelled, 不可回退)
  - `_cancel_requested` → 内部标志, 由 worker 检查
- **持久化**: ⚠️ **in-memory only** (JobQueue 单例, 无磁盘镜像)
  - 持久化由 HistoryStore 兜底 (`tracker.mark_*()`)
- **Repository**: `JobQueue` (singleton, ThreadPoolExecutor `max_workers=5`)
- **并发**:
  - 类级 `_singleton_lock` (单例)
  - 实例级 `_store_lock` (CRUD) + `_submit_lock` (submit + stagger 期间)
  - Job 内部 `_lock` (cancel / status 转换)
  - `_stagger_seconds = 1.5` — 相邻 job 提交间隔, 防东财 429
- **重试**: `_handle_em_block()` — 东财 429 退避 8s 后重试 1 次, 仍失败则 raise
- **取消**: `cancel_job` / `cancel_batch` — 双重检查 (pending 直接 cancelled, running 标记 `_cancel_requested` 由 worker 检查)

---

### 1.3 LogTask — `backend/core/log_store.py` (458 行)

> 注意: 实际**没有**显式 `LogTask` class, 而是用目录结构 (`{ticker}/{date}_run{NN}/`) + `meta.json` 隐式表达.

**Root (implicit)**: `{ticker}/{date}_run{NN}/` 目录 (含 4 文件)

```
~/.tradingagents/logs/{ticker}/{trade_date}_run{NN}/
├── meta.json              # TaskSummary 等价物
├── llm_messages.jsonl     # chunks type=llm
├── tool_calls.jsonl       # chunks type=tool
└── agent_outputs.jsonl    # chunks type=agent_output
```

**显式 dataclass**:

```python
@dataclass
class TaskSummary:               # UI 列表用, 不是聚合根
    analysis_id: str
    ticker: str
    trade_date: str
    task_dir_name: str           # "{date}_run{NN}"
    status: str
    signal: str
    elapsed_sec: float
    started_at: float
    finished_at: float | None
    chunk_counts: dict[str, int] # {"llm": N, "tool": N, "agent_output": N}
    is_legacy: bool = False      # 旧结构兼容标志

@dataclass
class LogChunk:                  # VO, 单条流式 chunk
    ts: float
    type: str                    # "llm" | "tool" | "agent_output"
    agent: str
    role: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    content: str | None = None
    tool: str | None = None
    input: dict | None = None
    output: str | None = None
    report_key: str | None = None
```

- **聚合根实际载体**: `LogWriter` (写) + `LogStore` (读) + 文件系统
- **Value Objects**:
  - `TaskDirName` (隐式) — `{trade_date}_run{NN}` (NN 自增, `run01` → `runNN`)
  - `ChunkType` — 字符串枚举 (无 Enum 包装)
  - `Signal` — 提取自 `final_trade_decision`, `_SIGNAL_KEYWORDS = ((BUY, Buy), ...)`
- **Invariants**:
  - 同一 `(ticker, trade_date)` 允许多次 run, 自增 NN
  - meta.json 原子写 (`.tmp` + `replace`)
  - jsonl append-only (fcntl.flock 锁)
  - 每 10 chunk 刷新 meta.chunk_counts (避免 fs churn)
- **持久化**:
  - 路径: `~/.tradingagents/logs/{ticker}/{date}_run{NN}/`
  - 旧结构: `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json` (兼容读, `is_legacy=True`)
- **Repository**:
  - `LogStore` — 读 API (`list_tickers` / `list_tasks` / `get_meta` / `stream_chunks`)
  - `LogWriter` — 写 API (`__init__` 创目录 + meta, `append_chunk`, `update_stages`, `finalize`)
- **线程安全**:
  - LogStore: 无锁 (read-only)
  - LogWriter: `fcntl.flock(LOCK_EX)` (jsonl append)

---

### 1.4 NotificationMessage (implicit) — `backend/core/notifier.py` (396 行)

> 实际**没有** `NotificationMessage` dataclass, message 是 `_render()` 临时拼装的 str.

**聚合根载体**: `Notifier` (singleton) + `ChannelConfig` (dataclass)

```python
@dataclass
class ChannelConfig:
    wecom_webhook: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_to: str | None = None
    smtp_use_tls: bool = True
    enabled_channels: list[str] = field(default_factory=lambda: ["log"])

class Channel(str, Enum):
    WECOM = "wecom"
    EMAIL = "email"
    DESKTOP = "desktop"
    LOG = "log"
```

**Runtime payload** (scheduler 调用时构造的 dict):
```python
{
    "schedule_name": str,
    "status": "ok" | "partial" | "error" | "skipped" | "never",
    "started_at": float,
    "duration": float,
    "summary": str,
    "batch_id": str,
    "run_id": str,
    "ticker_count": int,
}
```

- **Value Objects**:
  - `Channel` (Enum) — 4 渠道
  - `status_emoji: dict[str, str]` — `STATUS_EMOJI = {"ok": "✅", ...}`
  - `status_text: dict[str, str]` — 中文文案
- **Invariants**:
  - `enabled_channels` 决定哪些 channel 参与
  - 每个 channel 缺配置 → `is_configured()` 返回 False → skip
  - 单 channel 失败不影响其他 channel (`results: dict[str, bool]`)
- **持久化**: ⚠️ **无** — Notifier 是 stateless wrapper, 配置从 `~/.tradingagents/schedules/channels.yaml` 启动时读一次
- **Repository**: 无 (无 Repository 抽象)
- **线程安全**:
  - 单例 `_init_lock`
  - `_send_*()` 各自 try/except 隔离异常
- **Jinja2 模板**: `DEFAULT_TEMPLATE` — 6 字段 (schedule_name / status_emoji / status_text / started_at / duration / summary / batch_id / detail_link)

---

### 1.5 AlertRule — `backend/core/portfolio_alerts.py` (175 行) + portfolio_store.py

> AlertRule 聚合根实际定义在 `portfolio_store.py`, `portfolio_alerts.py` 只是评估器.

**Root**: `AlertRule` (在 portfolio_store.py)

```python
@dataclass
class AlertRule:
    rule_id: str                  # PK, uuid4[:12]
    ticker: str                   # 6 位
    rule_type: str                # 7 种 (MVP 只 2 种实现)
    threshold: float              # 非零 (pnl_pct 可负)
    enabled: bool = True
    note: str = ""
    created_at: float = field(default_factory=time.time)
    last_triggered_at: float | None = None
    last_triggered_price: float | None = None
    trigger_count: int = 0
```

**Evaluator 输出的 Value Object**:

```python
@dataclass
class AlertTrigger:               # 不是聚合根, 是触发事件的事实记录
    rule_id: str
    ticker: str
    rule_type: str
    threshold: float
    current_value: float
    triggered_at: float
    message: str                  # 中文: "价格突破 7.00，当前 7.05 (+0.71%)"
```

- **Value Objects**:
  - `RuleType` — 7 种字符串 (Enum 无显式包装, 用 frozenset 校验)
  - `VALID_ALERT_RULE_TYPES` — `{"price_above", "price_below", "pct_change", "pnl_pct", "take_profit", "stop_loss", "trailing_stop"}`
  - `Threshold` — float, 非零 (pnl_pct 用负数表示亏损阈值)
- **Invariants**:
  - `rule_type ∈ VALID_ALERT_RULE_TYPES` (PortfolioStore.add_alert 校验)
  - `threshold != 0`
  - Anti-repeat: `last_triggered_at` 距今 < 300s 跳过 (`ANTI_REPEAT_WINDOW_SEC = 300`)
- **持久化**: `~/.tradingagents/portfolio/alerts.json` (via PortfolioStore)
- **Repository**: `PortfolioStore.list_alerts()` / `add_alert` / `update_alert` / `delete_alert` / `record_trigger`
- **Domain Service**: `evaluate_alerts(store, current_prices, now)` → 遍历 enabled 规则, 防重复, 调 `store.record_trigger()` 写回
- **MVP 限制**: 仅 `price_above` / `price_below` 实现; 其他 5 种抛 `NotImplementedError`

---

### 1.6 Position — `backend/core/portfolio_store.py` (923 行)

**Root**: `Position` (dataclass)

```python
@dataclass
class Position:
    position_id: str              # PK, uuid4[:12]
    ticker: str                   # 6 位 (whitelist 校验)
    name: str
    cost_basis: float
    quantity: int                 # ≥ 0
    first_buy_date: str           # ISO YYYY-MM-DD
    last_trade_date: str
    account: str                  # FK → Account.name
    asset_class: str = "stock"    # 5 种枚举
    notes: str = ""
    created_at: float = field(default_factory=time.time)
```

- **Value Objects**:
  - `Ticker` — `_normalize_ticker()` 防御性 import (a_stock 不可用时退化为 strip)
  - `AssetClass` — `VALID_ASSET_CLASSES = {"stock", "bond", "overseas", "cash", "fund"}`
  - `Account` (FK 引用, 字符串而非 ORM 外键)
- **Invariants**:
  - `position_id` 不可改 (update_position 抛 ValueError)
  - `ticker` 不可改 (同上)
  - `quantity >= 0`
  - `account` 必须指向已存在 Account.name (否则抛 `账户不存在`)
  - `asset_class` ∈ VALID_ASSET_CLASSES
  - (ticker + account) 唯一 — 代码**未强制**, 可能创建重复 (技术债 #?)
- **持久化**: `~/.tradingagents/portfolio/positions.json` (JSON list)
- **Repository**: `PortfolioStore.add_position` / `update_position` / `delete_position` / `get_position` / `list_positions`
- **级联删除**: `delete_position` 自动删关联 Transaction (避免悬挂流水)
- **联动**: `add_transaction` 反向更新 `Position.quantity` (buy +=, sell -=) + `last_trade_date` (max)

---

### 1.7 Transaction — `backend/core/portfolio_store.py` (923 行)

**Root**: `Transaction` (dataclass)

```python
@dataclass
class Transaction:
    tx_id: str                    # PK, uuid4[:12]
    position_id: str              # FK → Position.position_id
    ticker: str                   # 冗余 (可从 Position 派生, 加速 list 过滤)
    date: str                     # ISO YYYY-MM-DD
    action: str                   # 6 种
    price: float
    quantity: int                 # > 0
    fees: float = 0.0
    notes: str = ""
    created_at: float = field(default_factory=time.time)
```

- **Value Objects**:
  - `Action` — `VALID_TRANSACTION_ACTIONS = {"buy", "sell", "dividend", "split", "merge", "rights"}`
  - `Date` — ISO 字符串 (无 date 对象, 序列化友好)
- **Invariants**:
  - `action ∈ VALID_TRANSACTION_ACTIONS`
  - `quantity > 0`
  - `sell` 不可超过 Position.quantity (否则抛 `sell quantity X exceeds held`)
  - `position_id` 必须存在 (否则 KeyError)
- **持久化**: `~/.tradingagents/portfolio/transactions.json`
- **Repository**: `PortfolioStore.add_transaction` / `list_transactions(ticker, since)`
- **联动**: 反向更新 Position (见 1.6)

---

### 1.8 Account — `backend/core/portfolio_store.py` (923 行)

**Root**: `Account` (dataclass, v0.5.0 新增)

```python
@dataclass
class Account:
    account_id: str               # PK, uuid4[:12]
    name: str                     # 唯一键, 中文友好
    broker: str = ""
    account_number_tail: str = ""
    asset_class: str = "stock"    # 账户级默认
    notes: str = ""
    is_default: bool = False      # 全局至多 1 个
    created_at: float = field(default_factory=time.time)
```

- **Value Objects**:
  - `Name` — 唯一键 (非空, 不可重复)
  - `AssetClass` — 同 Position
- **Invariants**:
  - `name` 非空 + 全局唯一
  - `is_default=True` 全局至多 1 个 (新加 default 自动让其它降级)
  - `asset_class` ∈ VALID_ASSET_CLASSES
- **持久化**: `~/.tradingagents/portfolio/accounts.json`
- **Repository**: `PortfolioStore.add_account` / `update_account` / `delete_account` / `get_account` / `get_account_by_name` / `list_accounts` / `set_default_account` / `ensure_default_account`
- **删除阻断**: `delete_account` — 若下有 Position 则抛 `账户下还有 X 只持仓`
- **启动幂等**: `ensure_default_account()` 在 `__init__` 调 — 文件空则建默认, 有但无 default 则把最早创建的提升

---

### 1.9 AnalysisTracker — `backend/core/tracker.py` (192 行)

**Root**: `AnalysisTracker` (dataclass, mutable state container)

```python
@dataclass
class AnalysisTracker:
    analysis_id: str              # PK, 与 HistoryEntry 共享
    ticker: str = ""
    trade_date: str = ""
    start_time: float = field(default_factory=time.time)

    is_running: bool = False
    is_complete: bool = False
    error: str | None = None

    current_stage: str = ""       # 11 stage 之一
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)

    final_state: dict[str, Any] = field(default_factory=dict)
    signal: str = ""

    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    _lock: threading.Lock
```

- **Value Objects**:
  - `StageId` — 11 个: `market / social / news / fundamentals / policy / hot_money / lockup / debate / trader / risk / pm` (runner.py `stage_map` 硬编码)
  - `Signal` — Buy/Sell/Hold (派生自 final_trade_decision)
  - `Stats` — llm_calls / tool_calls / tokens_in / tokens_out
- **Invariants**:
  - `is_running=True` → `is_complete=False`, `error=None` (互斥)
  - `current_stage` 单调 (P2.21 修: 不再 mark_stage_done 时清空 current_stage)
  - `elapsed = time.time() - start_time` (property)
- **持久化**: ⚠️ **in-memory only** (TrackerStore 单例)
  - 通过 `mark_*()` 方法**镜像**到 HistoryStore (事实源在 disk)
- **Repository**: `TrackerStore` (singleton, double-checked lock)
- **P2.25 修**: `TrackerStore.create(ticker, trade_date)` 现在生成 `analysis_id` 并传给 `HistoryStore.create(analysis_id=...)`, 确保两边 ID 一致
- **P2.23 修**: `_run_analysis` 加 600s `MAX_RUN_SEC` 硬超时, 触发 `tracker.mark_error()`

---

### 1.10 Schedule — `backend/core/scheduler.py` (889 行)

**Root**: `Schedule` (dataclass)

```python
@dataclass
class Schedule:
    schedule_id: str              # PK, uuid4[:12]
    name: str                     # 唯一显示名 (中文)
    cron_expr: str                # croniter 解析
    source_type: SourceType       # 3 种
    source_config: dict = field(default_factory=dict)
    enabled: bool = True
    notify_channels: list[str] = field(default_factory=lambda: ["log"])
    notify_template: str = "v0.6.0 default"
    config: dict = field(default_factory=dict)  # provider/deep_model/quick_model/wait_timeout/stagger
    last_run_at: float | None = None
    last_run_batch_id: str | None = None
    last_run_status: str = RunStatus.NEVER.value
    last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    created_by: str = "user"      # "user" | "preset"
```

**Enum**:
```python
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
```

- **Value Objects**:
  - `SourceType` (Enum)
  - `CronExpr` — 5 个常用 helper (`VALID_CRON_HELPERS`)
  - `NotifyChannel` — list[str] (复用 notifier.py Channel)
- **Invariants** (在 `validate()` 中检查):
  - `name` 非空
  - `cron_expr` 非空 + croniter 可解析
  - `source_type == MANUAL` → `source_config["tickers"]` 非空
- **持久化**: `~/.tradingagents/schedules/schedules.json` (原子写)
- **Repository**: `Scheduler.add_schedule` / `update_schedule` / `delete_schedule` / `get_schedule` / `list_schedules` / `pause_schedule` / `resume_schedule` / `run_now`
- **Daemon thread**:
  - 60s polling (`POLL_INTERVAL = 60.0`)
  - 首次启动判定: cron 5 分钟内有触发点 → 跑
  - 正常运行: `next_run_at(last_run) <= now` → 跑
- **预置**: 2 个 — "每日持仓复盘" (工作日 18:00, enabled) + "周一前瞻" (周一 8:00, disabled)

---

### 1.11 ScheduleRun — `backend/core/scheduler.py` (889 行)

**Root**: `ScheduleRun` (dataclass, 每次执行实例)

```python
@dataclass
class ScheduleRun:
    run_id: str                   # PK, uuid4[:12]
    schedule_id: str              # FK → Schedule.schedule_id
    started_at: float
    finished_at: float | None = None
    status: str = "running"       # running | ok | partial | error | skipped
    batch_id: str | None = None   # FK → BatchJob.batch_id
    job_ids: list[str] = field(default_factory=list)
    duration: float = 0.0
    summary: str = ""             # "ok=3 error=1 cancelled=0 total=4"
    error: str | None = None
    ticker_count: int = 0
```

- **Value Objects**:
  - `RunStatus` (Enum, 同 1.10)
  - `BatchId` (字符串引用, 无 FK 约束)
- **Invariants**:
  - `started_at` 必填
  - `status == "running"` → `finished_at is None`
  - `status ∈ {"ok", "partial", "error", "skipped"}` → `finished_at` 必填
  - `summary` 包含 `ok=X error=Y cancelled=Z total=N` 4 元组
- **持久化**: `~/.tradingagents/schedules/runs/YYYY-MM-DD.jsonl` (按天分文件, append-only)
- **Repository**: `Scheduler.list_runs(schedule_id, limit)`
- **Prune**: `_prune_old_runs()` — 删 30 天前文件 (`MAX_RUN_HISTORY_DAYS = 30`)
- **通知**: `_notify()` — 完成后调 `Notifier.send()`, 失败仅 warning 不挂调度

---

### 1.12 ImportJob (implicit) — `backend/core/portfolio_import.py` (494 行)

> 实际**没有** `ImportJob` dataclass, 是 stateless 函数集合, 但代表清晰的 use case.

**Use case 流程** (4 步):

```python
# 1. detect_format(csv_path) → 'eastmoney' | 'ths' | 'xueqiu' | 'generic' | None
# 2. parse_csv(csv_path, format) → list[dict{ticker, name, cost, quantity, date}]
# 3. preview_import(parsed, existing) → {"new": [...], "conflicts": [...], "invalid": [...]}
# 4. apply_import(store, preview, strategy) → list[Position]
```

**Value Objects**:

```python
CSV_FORMATS: dict[str, dict[str, str | list[str]]] = {
    "eastmoney": {                     # 东财 — 精确列名
        "code": "证券代码",
        "name": "证券名称",
        "cost": "成本价",
        "quantity": "持有数量",
        "date": "建仓日期",
    },
    "ths": {                           # 同花顺 — 精确列名
        "code": "股票代码", "name": "股票名称",
        "cost": "成本价", "quantity": "持仓数量", "date": "买入日期",
    },
    "xueqiu": {                        # 雪球 — 英文列名
        "code": "symbol", "name": "name",
        "cost": "cost_price", "quantity": "quantity", "date": "created_at",
    },
    "generic": {                       # 通用 — 候选列表 (按序找首个命中)
        "code": ["ticker", "code", "代码"],
        "name": ["name", "名称"],
        "cost": ["cost", "成本价", "cost_basis"],
        "quantity": ["quantity", "数量", "qty"],
        "date": ["date", "日期", "buy_date"],
    },
}
```

**导出 VO**:
- `export_csv(positions, transactions=None) → Path` — 10 列 (代码/名称/成本价/持仓数量/持仓金额/浮动盈亏/盈亏比例/首次买入日期/账户/备注)
- `export_transactions_csv(transactions) → Path` — 8 列 (日期/代码/动作/价格/数量/手续费/账户/备注)

- **Invariants**:
  - `format ∈ CSV_FORMATS` (否则 ValueError)
  - 跳过规则: `cost < 0` / `quantity <= 0` / `date` 无法解析 / `ticker` 空
  - `score < 3` → `detect_format()` 返回 None
  - `resolution_strategy ∈ {"overwrite", "skip", "merge"}` (merge → NotImplementedError)
- **持久化**: ⚠️ **无** (parse 时不存, apply 时直接调 `store.add_position`)
- **Repository**: 无 (直接 import PortfolioStore)
- **日期归一化**: `_normalize_date()` 支持 5 种格式:
  - `YYYY/MM/DD`, `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY年MM月DD日`, `YYYYMMDD`
- **BOM 兼容**: UTF-8 BOM (`utf-8-sig`) — Excel 友好

---

### 1.13 WatchEntry — `backend/core/watchlist.py` (204 行)

**Root**: `WatchEntry` (dataclass)

```python
@dataclass
class WatchEntry:
    entry_id: str                   # PK, uuid4[:12]
    ticker: str                     # 6 位 (whitelist 校验)
    tag: str = "观察"               # 6 种白名单
    note: str = ""
    created_at: float = field(default_factory=time.time)

VALID_TAGS: frozenset[str] = frozenset({"长线", "短线", "观察", "T0", "T1", "T2"})
_TICKER_RE = re.compile(r"^\d{6}$")
```

- **Value Objects**:
  - `Tag` — `VALID_TAGS` 6 种枚举 (中文 + T0/T1/T2)
  - `Ticker` — 6 位数字 (regex `_TICKER_RE`)
- **Invariants**:
  - `ticker` 必须匹配 `^\d{6}$` (否则 ValueError)
  - `tag ∈ VALID_TAGS` (否则 ValueError)
  - 同一 ticker 可有多个 entry (不同 tag) — **未强制 ticker 唯一**
- **持久化**: `~/.tradingagents/watchlist.json` (原子写, `.tmp` + `replace`)
- **Repository**: `WatchlistStore.add` / `remove` / `list(tag=None)` / `count` / `clear`
- **线程安全**:
  - 类级 `_init_lock` (单例)
  - 实例级 `RLock` (CRUD, 支持重入 — `add()` 内部调 `_save()` 不死锁)
- **空缓存**: 模块启动时 `_load()`, 文件不存在 / 损坏 / 非 list → `_cache = []`

---

## 2. Domain Services (无状态计算)

### 2.1 portfolio_calc.py (743 行) — 纯函数模块

**核心 dataclass 输出**:

```python
@dataclass
class PositionMetrics:           # 单只持仓指标
    current_value: float
    cost_value: float
    pnl_abs: float
    pnl_pct: float
    today_pnl: float
    today_pnl_pct: float
    holding_days: int
    cost_basis: float             # input echo
    current_price: float          # input echo
    prev_close: float             # input echo

@dataclass
class PortfolioSummary:          # 组合汇总 + 归因
    total_value: float
    total_cost: float
    total_pnl_abs: float
    total_pnl_pct: float
    today_pnl: float
    positions_count: int
    by_industry: dict[str, float]
    by_sector: dict[str, float]
    by_asset_class: dict[str, float]
    by_account: dict[str, float]
    concentration_top5_pct: float
```

**Domain Services 清单**:

| 函数 | 输入 | 输出 | 算法 |
|------|------|------|------|
| `compute_position_metrics` | Position + price + prev_close + tx | PositionMetrics | 简单乘法 |
| `compute_portfolio_summary` | positions + prices + get_industry_fn + get_sector_fn | PortfolioSummary | 聚合 + 板块均摊 |
| `_extract_cashflows` | transactions + current_value + as_of | (cashflows, dates) | 按 action 转换方向 |
| `compute_xirr` | transactions + current_value + as_of | float | scipy.brentq NPV=0 |
| `compute_max_drawdown` | equity_curve | float | 滚动 peak-trough |
| `compute_sharpe` | daily_returns + rf | float | (mean-rf)/std × sqrt(252) |
| `compute_brinson_attribution` | positions + benchmark_returns | dict | selection + allocation |
| `compute_annual_return` | — | — | (stub) |
| `get_rebalance_signals` | — | — | (stub, 调 HistoryStore) |
| `group_by_sector` | — | — | (废弃, 保留兼容) |

- **纯函数特征**:
  - 无 IO (除 `get_rebalance_signals` 调 HistoryStore)
  - 无副作用 (不写盘、不发请求、不渲染 UI)
  - 数值稳定 (除零 / 空输入 → 0.0, UI 层显示 "N/A")
- **依赖**: numpy + scipy (项目既有依赖)
- **常量**: `TRADING_DAYS_PER_YEAR=252` / `DEFAULT_RISK_FREE_RATE=0.025` / `XIRR_LO=-0.99` / `XIRR_HI=10.0`

---

## 3. Application Service — `backend/core/runner.py` (203 行)

> 不是聚合根, 是用例编排层.

**2 个函数**:

```python
def _run_analysis(analysis_id, config, tracker) -> None:
    """Thread target: 调 LangGraph + 镜像 progress 到 tracker."""
    # 1. 创建 web_tracker 桥接
    # 2. stage_map 11 字段 → stage_id 映射
    # 3. for chunk in graph.stream():
    #    - 硬超时 600s 检查 (P2.23)
    #    - 更新 stage + stats
    #    - time.sleep(0.5)
    # 4. tracker.mark_complete(last_chunk, signal)
    # 5. graph._log_state(trade_date, last_chunk)
    # 异常: TimeoutError → tracker.mark_error; 其他 → raise

def start_analysis(request: AnalyzeRequest) -> tuple[str, AnalysisTracker]:
    """FastAPI 入口: 创建 tracker + spawn daemon thread."""
    # 1. store.create(ticker, trade_date) → analysis_id, tracker
    # 2. 合并 DEFAULT_CONFIG + request overrides
    # 3. threading.Thread(target=_run_analysis, daemon=True).start()
```

**stage_map** (硬编码):
```python
{
    "market_report": "market",
    "sentiment_report": "social",
    "news_report": "news",
    "fundamentals_report": "fundamentals",
    "policy_report": "policy",
    "hot_money_report": "hot_money",
    "lockup_report": "lockup",
    "investment_debate_state": "debate",
    "trader_investment_plan": "trader",
    "risk_debate_state": "risk",
    "final_trade_decision": "pm",
}
```

- **职责**: 桥接 FastAPI ↔ web/runner.run_analysis_in_thread, 把 ProgressTracker ↔ AnalysisTracker 双向同步
- **P2.21 修**: 不再 `tracker.mark_stage_active("")` 清空 current_stage
- **P2.23 修**: 600s 硬超时 → TimeoutError → mark_error
- **P2.25 修**: stage_map 11 字段 (覆盖 A 股 7 analyst + 4 决策)

---

## 4. 领域事件 (从代码反推)

> 严格说, **当前没有 EventBus / 显式 event dataclass**, 但从 `mark_*()` / `record_*()` 方法可以反推**事实事件**:

| 事件 (推断) | 触发方法 | 模块 | 接收方 |
|------|---------|------|--------|
| `AnalysisStarted` | `HistoryStore.create()` / `TrackerStore.create()` | history_store / tracker | (同步镜像, 无订阅) |
| `StageActivated` | `tracker.mark_stage_active(stage_id)` | tracker | HistoryStore (无镜像, 仅内存) |
| `StageCompleted` | `HistoryStore.mark_stage_done(aid, stage_id, report, report_key)` | history_store | (无订阅, 纯写盘) |
| `AnalysisCompleted` | `HistoryStore.mark_complete(aid, signal, elapsed, stages)` | history_store | (无订阅) |
| `AnalysisFailed` | `HistoryStore.mark_error(aid, error, elapsed)` | history_store | (无订阅) |
| `ZombieCleanedUp` | `HistoryStore.cleanup_zombies()` 返回 analysis_ids 列表 | history_store | (日志) |
| `JobEnqueued` | `JobQueue.create_batch()` + `submit()` | job_queue | (无订阅) |
| `JobCancelled` | `JobQueue.cancel_job()` / `cancel_batch()` | job_queue | (无订阅, 改 _cancel_requested) |
| `JobRetried` | `JobQueue.retry()` | job_queue | (无订阅) |
| `BatchEMBlockRetried` | `JobQueue._handle_em_block()` | job_queue | (logger.warning) |
| `LogTaskCreated` | `LogWriter.__init__()` | log_store | (无订阅) |
| `LogChunkAppended` | `LogWriter.append_chunk()` | log_store | (每 10 chunk 刷 meta) |
| `LogTaskFinalized` | `LogWriter.finalize()` | log_store | (无订阅) |
| `AlertRuleCreated` | `PortfolioStore.add_alert()` | portfolio_store | (audit.log) |
| `AlertTriggered` | `PortfolioStore.record_trigger(rule_id, price)` | portfolio_alerts | (audit.log) |
| `PositionCreated` | `PortfolioStore.add_position()` | portfolio_store | (audit.log) |
| `TransactionAdded` | `PortfolioStore.add_transaction()` | portfolio_store | (audit.log, 反向更新 Position) |
| `PositionDeleted` | `PortfolioStore.delete_position()` | portfolio_store | (audit.log, 级联删 tx) |
| `AccountCreated` / `AccountDefaultChanged` | `add_account()` / `set_default_account()` | portfolio_store | (audit.log) |
| `NotificationSent` | `Notifier.send()` 返回 `{channel: success_bool}` | notifier | (UI 显示) |
| `ScheduleAdded` | `Scheduler.add_schedule()` | scheduler | (无订阅) |
| `ScheduleRunStarted` | `_run_schedule()` 调 `_append_run(run)` | scheduler | (无订阅) |
| `ScheduleRunCompleted` | `_run_schedule()` 调 `_append_run(run)` + `_notify()` | scheduler | Notifier |
| `ScheduleRunFailed` | 同上 (exception path) | scheduler | Notifier |
| `TickProcessed` | `Scheduler._tick()` 每 60s | scheduler | (logger) |
| `WatchEntryAdded` | `WatchlistStore.add()` | watchlist | (无订阅) |

**共同特征**:
- **无 EventBus 抽象** — 都是直接 method call
- **无异步派发** — 全部同步调用
- **接收方 = 0** — 多数事件**只是写到磁盘或日志**, 不触发任何业务副作用
- **唯一跨上下文通信**: `Scheduler._run_schedule` → `Notifier.send` (显式)

**重构路径** (如未来引入 EventBus):
```python
# 目标 API
class EventBus:
    def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, event_type: type, handler: Callable) -> None: ...

# 现有 mark_*() 改造
def mark_complete(self, ...):
    self._write(entry)
    self._bus.publish(AnalysisCompleted(...))
```

---

## 5. Repository 接口 (DIP 违反现状)

> 当前所有 store 是**具体类 + 单例**, 无 Protocol / ABC. 测试用 `monkeypatch.setattr`, 不是依赖注入.

**Repository 实现清单**:

| Repository | 实现类 | 持久化 | Protocol 抽象 (理想) |
|------------|--------|--------|---------------------|
| HistoryRepository | `HistoryStore` | JSON 文件 | `IHistoryRepository` |
| BatchJobRepository | `JobQueue` | **in-memory** | `IBatchJobRepository` |
| LogTaskRepository (读) | `LogStore` | JSONL + meta.json | `ILogTaskReader` |
| LogTaskRepository (写) | `LogWriter` | 同上 | `ILogTaskWriter` |
| NotificationGateway | `Notifier` | **无** | `INotifier` |
| PortfolioRepository | `PortfolioStore` | 5 个 JSON + audit.log | `IPortfolioRepository` |
| AnalysisTrackerRepository | `TrackerStore` | **in-memory** (镜像到 HistoryStore) | `IAnalysisTrackerRepository` |
| ScheduleRepository | `Scheduler` | schedules.json + runs/*.jsonl | `IScheduleRepository` |
| WatchlistRepository | `WatchlistStore` | watchlist.json | `IWatchlistRepository` |
| AlertEvaluator | `evaluate_alerts()` 函数 | (无) | `IAlertEvaluator` |

**测试隔离** (mock 模式):
```python
# pytest fixture 风格 (实测代码)
monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
monkeypatch.setattr("backend.core.history_store._HISTORY_DIR", tmp_path / "history")
```

**DIP 违反的体现**:
- `runner.py` 直接 `from backend.core.tracker import AnalysisTracker, get_store`
- `scheduler.py` 直接 `from backend.core.job_queue import JobQueue as JobQueue`
- `portfolio_alerts.py` 直接 `from backend.core.portfolio_store import AlertRule, PortfolioStore`
- `portfolio_calc.py` 直接 `from backend.core.portfolio_store import Position, Transaction`
- 总计 **26 处直接 import** (`grep -rn "import.*get_"` 测得)

**抽象难度**: scheduler 模块顶部 import 4 个具体类专门为测试 monkeypatch:
```python
# backend/core/scheduler.py:38-43
from backend.core.job_queue import JobQueue as JobQueue  # noqa: E402, F401
from backend.core.portfolio_store import PortfolioStore as PortfolioStore  # noqa: E402, F401
from backend.core.watchlist import WatchlistStore as WatchlistStore  # noqa: E402, F401
from backend.core.notifier import Notifier as Notifier  # noqa: E402, F401
```
**说明**: 这是 anti-pattern — 应该用 Protocol 注入, 而不是依赖 import 路径做 monkeypatch.

---

## 6. 现有架构债务 (按代码现状)

### Debt #1: TrackerStore 与 HistoryStore ID 不一致 ✅ 部分修 (P2.25)

**位置**: `backend/core/tracker.py:155-176` (TrackerStore.create)

**现状**:
```python
# P2.25 修后: TrackerStore.create 现在生成 analysis_id 并传给 HistoryStore.create
analysis_id = f"{ticker}_{trade_date}_{uuid.uuid4().hex[:8]}"
tracker = AnalysisTracker(analysis_id=analysis_id, ...)
get_history_store().create(ticker, trade_date, status="running", analysis_id=analysis_id)
```

**残留**: `HistoryStore.create()` 仍允许 `analysis_id=None` (backward compat), 直接调用者可能生成不同 ID. 没有静态检查保证 `tracker.analysis_id == history_entry.analysis_id`.

**严重度**: 🟡 中 (修了一半, 还有 fallback 路径可触发不一致)

---

### Debt #2: 多 in-memory 单例, 重启丢数据

**位置**: `backend/core/job_queue.py:149` (JobQueue), `backend/core/tracker.py:137` (TrackerStore)

**现状**:
- `JobQueue` — `_batches: dict` / `_jobs: dict` 全 in-memory
- `TrackerStore` — `_trackers: dict` 全 in-memory
- `ScheduleRun` 完成后只写 `runs/{date}.jsonl`, Schedule 本身已持久化 OK

**后果**:
- uvicorn 重启 → 所有 running job 丢失 tracker, 历史 JSON 里 `status=running` 永远卡住
- 已有缓解: `HistoryStore.cleanup_zombies()` + `cleanup_stuck()` (P2.14 + P2.21)
- 但 zombie sweep 需要 60s/600s 阈值 → 启动后短时间内 UI 仍显示僵尸

**严重度**: 🟠 高 (僵尸条目是用户实际遇到的痛点)

---

### Debt #3: Repository 接口未抽象 (违反 DIP)

**位置**: 全部 9 个 Store

**现状**: 0 个 Protocol / ABC (`grep -n "Protocol\|ABC\|abstractmethod" backend/core/*.py` 全部 0 命中)

**后果**:
- 测试隔离靠 `monkeypatch.setattr` (模块路径依赖)
- 无法注入 mock / in-memory fake 实现
- scheduler.py 顶部专门 import 4 个类只为测试 (anti-pattern)

**严重度**: 🟡 中 (不影响功能, 但限制测试和未来可扩展性)

---

### Debt #4: 领域事件未实现 (无 EventBus)

**位置**: 全局

**现状**: `mark_*()` / `record_*()` 方法**只写盘**, 不触发任何订阅者. 见 §4 列表 25+ 事件全部"无订阅方".

**后果**:
- 跨上下文通信只能显式 method call (如 Scheduler → Notifier)
- 无法加新副作用 (如 AnalysisCompleted → 自动触发 portfolio rebalance)
- audit.log 是唯一的事件溯源

**严重度**: 🟢 低 (业务规模小, 显式调用已够用)

---

### Debt #5: 聚合根 invariant 校验不全

**位置**: 多处

**5.1 Position 重复**:
- 代码**未强制** (ticker + account) 唯一
- `add_position()` 允许同一 ticker+account 创建多条 Position
- spec 没明示; 用户可能误操作

**5.2 WatchEntry 重复**:
- `WatchlistStore.add()` 不检查 ticker 是否已存在
- 同 ticker 可加 6 次不同 tag (技术上不算 bug, 但 list 时可能困惑)

**5.3 HistoryEntry 状态机**:
- `mark_complete()` / `mark_error()` 都可以从任何状态调 (无前置检查)
- 已 completed 的 entry 可被改成 running

**5.4 BatchStatus finished_count / error_count 死代码**:
- `BatchJob.finished_count` 和 `error_count` 字段定义但**从未更新**
- 实际唯一状态源是 `job.status`

**严重度**: 🟡 中 (多数不影响功能, 但增加认知负担)

---

### Debt #6: 跨 Context 无 ACL (直接 method call)

**位置**: 多处

**现状**:
- `Scheduler._run_schedule()` 直接调 `JobQueue.create_batch()` + `submit()`
- `JobQueue._run_one()` 直接调 `from web.runner import run_one_analysis` (注: 但这其实是 `web/runner.py`, 不是 backend; Lazy import 是好的)
- `evaluate_alerts()` 直接 `store.list_alerts()` + `store.record_trigger()`
- `_load_tickers_for_source()` 直接 `get_portfolio_store().list_positions()` / `get_watchlist_store().list()`

**后果**:
- 耦合度高, 改一个 store 影响所有调用方
- 单元测试必须 mock 整条链

**严重度**: 🟢 低 (规模小, 显式调用清晰)

---

### Debt #7 (bonus): job_queue 与 scheduler 之间 stagger 泄漏风险

**位置**: `backend/core/scheduler.py:512-549`

**现状**:
```python
with q._submit_lock:
    original_stagger = q._stagger_seconds
    if stagger_override is not None:
        q._stagger_seconds = max(0.0, float(stagger_override))
    try:
        ...
        q.submit(...)
    finally:
        q._stagger_seconds = original_stagger  # 防御性恢复
```

**评论**: 防御性写法正确, 但暴露 `q._stagger_seconds` 是**私有属性**给外部修改. 应该加 setter 或 `q.set_stagger(value)`.

**严重度**: 🟢 低 (代码注释承认 race window, 但实测正确)

---

### Debt #8 (bonus): portfolio_calc.get_rebalance_signals 仍是 stub

**位置**: `backend/core/portfolio_calc.py:740+` (文档提及 "调仓推送")

**现状**: 文档说"diff Bull/Bear 信号", 但代码仅占位, 没真实实现.

**严重度**: 🟡 中 (UI banner 永远空)

---

### Debt #9 (bonus): notify 模板固定, 无自定义路径

**位置**: `backend/core/notifier.py:39-46`

**现状**: `DEFAULT_TEMPLATE` 硬编码, `notify_template` 字段在 Schedule 存在但代码忽略.

**严重度**: 🟢 低 (MVP 够用)

---

## 7. 重构建议 (按 ROI 排序)

### 短期 (1-2 周, ★★★★★)

**R1. 抽 Protocol 接口 (DIP 修复)** ★★★★★
- 新建 `backend/core/repositories.py` 定义 9 个 Protocol:
  - `IHistoryRepository` / `IBatchJobRepository` / `ILogTaskReader` + `ILogTaskWriter`
  - `INotifier` / `IPortfolioRepository` / `IAnalysisTrackerRepository`
  - `IScheduleRepository` / `IWatchlistRepository` / `IAlertEvaluator`
- 各 store 加 `__implements__ = (Ixxx,)` 标记 (运行时 isinstance 检查)
- 26 处直接 `get_*()` import 改为构造函数注入
- **收益**: 测试可注入 in-memory fake; 未来换 SQLite 不改业务代码

**R2. 引入 EventBus (in-process)** ★★★★☆
- 新建 `backend/core/event_bus.py`:
  ```python
  class EventBus:
      def publish(self, event: DomainEvent) -> None
      def subscribe(self, event_type: type, handler: Callable) -> Callable  # 返回 unsubscribe
  ```
- 25 个 `mark_*()` / `record_*()` 方法末尾加 `bus.publish(...)`
- 现有 audit.log 改写为 audit subscriber
- **收益**: 跨 context 解耦; 未来加 rebalance / portfolio update 不改 scheduler

**R3. 持久化 TrackerStore** ★★★☆☆
- `TrackerStore._trackers` 加定时 snapshot 到 `~/.tradingagents/tracker_snapshot.json`
- 启动时 read + 验证 (status in {running, completed, error}) + 过期清理
- **收益**: 缓解 Debt #2, 不再丢正在跑的 job tracker

**R4. 修复 zombie 启动延迟** ★★★★☆
- `HistoryStore.cleanup_zombies()` 当前在 `backend.main` startup 调, 但要等 list_all 扫盘
- 加缓存 `~/.tradingagents/zombie_cache.json` 记录已 cleanup id, 启动 5s 内立即标灰
- **收益**: 用户刷新 UI 看不到僵尸

### 中期 (1 个月, ★★★★☆)

**R5. AnalysisId 值对象** ★★★★☆
- 新建 `backend/domain/value_objects.py`:
  ```python
  @dataclass(frozen=True)
  class AnalysisId:
      value: str  # "{ticker}_{date}_{uuid4[:8]}"
      def __post_init__(self): ...  # 校验格式
  ```
- `HistoryEntry.analysis_id` / `Job.analysis_id` / `AnalysisTracker.analysis_id` 全部类型化为 `AnalysisId`
- **收益**: 静态类型检查保证 ID 格式一致; Debt #1 根除

**R6. ACL 适配层** ★★★☆☆
- 新建 `backend/contexts/` 子包:
  ```
  contexts/
    analysis/
      acl.py     # 对外暴露: create_analysis, get_progress
    portfolio/
      acl.py     # 对外暴露: list_positions_summary
    scheduling/
      acl.py     # 对外暴露: list_due_schedules
  ```
- Scheduler 不再直接 `get_portfolio_store()`, 改调 `portfolio_acl.list_tickers_for_source()`
- **收益**: 依赖单向, 改 portfolio 不影响 scheduler

**R7. 真实化 portfolio_calc.get_rebalance_signals** ★★★☆☆
- 实现 Bull/Bear 信号 vs Position 比较, 生成 {ticker, action: buy/sell, urgency} 列表
- **收益**: Debt #8 根除, portfolio banner 有内容

### 长期 (1 季度, ★★★★☆)

**R8. SQLite 迁移** ★★★★☆
- portfolio 5 个 JSON → SQLite 1 个 `portfolio.db`
- history JSON → `history.db`
- schedules JSON + runs jsonl → `schedules.db`
- **优势**:
  - 原子事务 (JSON 临时文件 + replace 是 fake 原子)
  - 查询性能 (list_all 当前每次 glob + parse)
  - 索引 (按 ticker / status / created_at)
- **风险**: 测试 fixture 改造量大 (当前 26+ 测试 monkeypatch 路径)
- **建议**: 分阶段 — portfolio 先, history 后

**R9. apprise 替换 Notifier** ★★★☆☆
- 当前 4 channel 手写 (WeCom webhook / SMTP / notify-send / log)
- `apprise` 库支持 80+ 渠道统一 API
- **收益**: 加钉钉 / 飞书 / Slack 不改代码
- **风险**: 多一个依赖 (apprise ~10MB)

**R10. 真实 trail-stop 实现** ★★☆☆☆
- 当前 `trailing_stop` 是 stub (`rule_type` 接受但语义同 `stop_loss`)
- 需要历史 K 线 (push2his 已有) + 维护每个 rule 的 high-water mark
- **收益**: AlertRule 7 种全部可用

---

## 8. 跨模块引用图 (call graph)

```
                          ┌─────────────────┐
                          │  web/runner.py  │
                          │ run_one_analysis│
                          └────────┬────────┘
                                   │ creates HistoryEntry
                                   ▼
                          ┌─────────────────┐
                          │ HistoryStore    │
                          │ (singleton)     │
                          └────────┬────────┘
                                   │ mirror
                                   ▼
                          ┌─────────────────┐
                          │ TrackerStore    │
                          │ AnalysisTracker │
                          └─────────────────┘
                                   ▲
                                   │ create/start_analysis
                          ┌────────┴────────┐
                          │ backend/runner  │
                          │ _run_analysis   │
                          └─────────────────┘

  ┌─────────────────┐         ┌─────────────────┐
  │ JobQueue        │ ◀────── │ Scheduler       │
  │ create_batch    │  submit │ _run_schedule   │
  │ submit          │         │ _tick (60s)     │
  └────────┬────────┘         └────────┬────────┘
           │                            │
           │ _run_one                  │ _load_tickers
           ▼                            ▼
  ┌─────────────────┐         ┌─────────────────┐
  │ web/runner      │         │ PortfolioStore  │
  │ run_one_analysis│         │ WatchlistStore  │
  └─────────────────┘         └─────────────────┘
                                       ▲
                                       │ add_position / add_transaction
                                       │
                              ┌────────┴────────┐
                              │ portfolio_import│
                              │ apply_import    │
                              └─────────────────┘

  ┌─────────────────┐         ┌─────────────────┐
  │ PortfolioStore  │ ◀────── │ evaluate_alerts │
  │ list_alerts     │  record │ (portfolio_     │
  │ record_trigger  │  trigger│  alerts.py)     │
  └─────────────────┘         └─────────────────┘
```

**关键耦合点**:
1. **HistoryStore ↔ TrackerStore** (双写镜像, P2.25 修 ID 一致性)
2. **JobQueue → web/runner** (Lazy import 避免循环)
3. **Scheduler → JobQueue** (直接 method call, 用 `_submit_lock` 串行)
4. **Scheduler → Notifier** (直接 method call, 失败容忍)
5. **Scheduler → PortfolioStore + WatchlistStore** (ticker source, 直接 import)

---

## 9. 测试覆盖度参考 (现有, 不重测)

| 模块 | 行数 | 测试数 | 覆盖率 |
|------|------|--------|--------|
| portfolio_store.py | 923 | 90+ | 98% |
| portfolio_calc.py | 743 | 90+ | 95% |
| portfolio_alerts.py | 175 | 35+ | 97% |
| portfolio_import.py | 494 | 50+ | 96% |
| scheduler.py | 889 | — | — |
| history_store.py | 370 | — | — |
| tracker.py | 192 | — | — |
| job_queue.py | 423 | — | — |
| log_store.py | 458 | 16 + 7 = 23 | — |
| notifier.py | 396 | — | — |
| watchlist.py | 204 | — | — |
| runner.py (backend) | 203 | — | — |

**已知测试盲点**:
- scheduler.py — 时序 + daemon thread 测试薄弱
- history_store zombie/stuck — 边界条件 (正好 60s / 600s)
- notifier.py — Jinja2 模板 fallback 路径
- JobQueue._handle_em_block — 退避 8s 后重试逻辑

---

## 10. 总结

### 13 个聚合根分类

**实体根** (有独立生命周期): HistoryEntry, BatchJob+Job, Position, Transaction, Account, AnalysisTracker, Schedule, ScheduleRun, WatchEntry, AlertRule (10 个)

**隐式根** (载体为目录或函数): LogTask (目录), NotificationMessage (template render), ImportJob (stateless function) (3 个)

### 核心结论

1. **13 个模块, 22 个 dataclass, 0 个 Protocol** — 战术层完整但抽象层缺失
2. **9 个 singleton store + RLock/Lock** — 线程安全 OK, 但 DIP 违反
3. **持久化混合** — JSON 文件 (6) / in-memory (3) / 无 (3) — Debt #2 是最大隐患
4. **事件 25+ 但 0 订阅者** — 当前业务规模够用, EventBus ROI 中等
5. **P2.21/P2.23/P2.25 持续修 zombie + ID + timeout** — 已有 4 次 hotfix, 说明聚合根 invariant 边界在演进
6. **scheduler 是胶水层** — 直接 import 4 个具体类 (anti-pattern, 但 lazy import + monkeypatch 短期可接受)

### 优先行动 (按 ROI)

| 优先级 | 行动 | 工作量 | 收益 |
|--------|------|--------|------|
| 🥇 | R1 Protocol 抽象 | 1 周 | 测试解耦, 未来 SQLite 迁移无侵入 |
| 🥈 | R2 EventBus | 1 周 | 跨 context 解耦, 25+ 事件可观测 |
| 🥉 | R5 AnalysisId 值对象 | 2 天 | 静态保证 ID 一致, Debt #1 根除 |
| 4 | R3 持久化 TrackerStore | 3 天 | Debt #2 缓解, 启动更干净 |
| 5 | R6 ACL 适配层 | 2 周 | 跨 context 依赖单向 |

---

## 附录 A: 路径速查

| 数据 | 路径 |
|------|------|
| HistoryEntry | `~/.tradingagents/logs/history/<analysis_id>.json` |
| LogTask | `~/.tradingagents/logs/{ticker}/{date}_run{NN}/{meta,llm_messages,tool_calls,agent_outputs}.json` |
| Position / Transaction / AlertRule / Account | `~/.tradingagents/portfolio/{positions,transactions,alerts,accounts}.json` |
| Portfolio audit | `~/.tradingagents/portfolio/audit.log` |
| Schedule | `~/.tradingagents/schedules/schedules.json` |
| ScheduleRun | `~/.tradingagents/schedules/runs/YYYY-MM-DD.jsonl` |
| Notifier config | `~/.tradingagents/schedules/channels.yaml` |
| Watchlist | `~/.tradingagents/watchlist.json` |

## 附录 B: 状态机速查

### HistoryEntry
```
pending ─create()──▶ running ─mark_complete()──▶ completed
                       │
                       ├──mark_error()─────▶ error
                       └──(server restart)──▶ zombie / stuck (P2.21 cleanup)
```

### Job
```
pending ─_run_one()──▶ running ─success─────▶ completed
                          │
                          ├──exception──────▶ error
                          └──_cancel_requested──▶ cancelled
                             │
                             └──retry()────▶ pending (重置)
```

### BatchStatus (派生)
```
all_completed → COMPLETED
all_error/cancelled → FAILED
all_cancelled → CANCELLED
mixed completed + none_pending/running → PARTIAL
any running → RUNNING
default → PENDING
```

### ScheduleRun
```
running ─ok────▶ ok
       ─partial▶ partial
       ─error──▶ error
       ─no tickers→ skipped
       (NONE 状态: "never")
```

### AlertRule
```
created ─enabled=true──▶ armed
       ─triggered + record_trigger()──▶ cooldown (300s)
       ─cooldown elapsed──▶ armed
       ─enabled=false──▶ disabled
```

### WatchEntry
```
created (无状态机, 仅 CRUD)
```

### Account.is_default
```
created (is_default=False)
   │
   ├─is_default=True──▶ set_default()──▶ unique default (其它让位)
   │
   └─ensure_default_account() (启动)
       ├─空文件──▶ 创建 default
       ├─已有 default──▶ noop
       └─无 default──▶ 把最早创建的提升为 default
```