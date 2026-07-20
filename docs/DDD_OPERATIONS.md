# TradingAgents A 股 运维管理类 DDD 深入探索（read-only）

> **git HEAD**: `33b3a42` (P2.25 source code)
> **范围**: 日志记录 (`backend/core/log_store.py`) + 历史持久化 (`backend/core/history_store.py`) + 5 个 logs API + 5 个 history API + Streamlit 日志面板
> **本文是第五轮 DDD 战术探索**，聚焦 **Operations / Infrastructure 层**：运行时日志 streaming、history metadata 持久化、path safety、zombie / stuck cleanup、并发模型与重构路径。
> **互补关系**：本文不重复 `DDD_EXPLORATION.md`（13 后端聚合根）、`DDD_AGENTS_DEEP_DIVE.md`（16 Agent）、`DDD_DATAFLOWS_INFRA.md` / `DDD_DATAFLOWS_DEEP.md`（dataflows + 工具集），只深入"日志 / 历史 / 运维管理"这条纵向管线。

---

## 0. 调研摘要 (Empirical Snapshot @ `33b3a42`)

| 维度 | 数据 |
|---|---|
| `log_store.py` 总行数 | **458** |
| `history_store.py` 总行数 | **370** |
| `api/logs.py` 总行数 | **196** |
| `api/history.py` 总行数 | **185** |
| `logs_panel.py` 总行数 | **178** |
| `~/.tradingagents/logs/` 总量 | 440 KB（dev box） |
| 历史 entry 数 | **67** 文件 |
| 历史 entry 样本 `600595_2026-07-17_07b480ae` | `status=running`, `elapsed=0`, `completed_stages=[]`, `started_at=null` ← **P2.14 僵尸**（startup sweep 应清掉） |
| 600595 ticker 任务数 | 20 个 `runNN`（run01 ~ run20），其中 18 error / 2 running |
| meta.json vs 实际 jsonl 行数 | 当前 0 vs 0 一致（这些 run 全是 pre-graph 失败，没产生 chunk） |
| `fcntl.flock` 实际使用点 | 仅 1 处：`LogWriter.append_chunk`（line 391, 395）|
| `HistoryStore._lock_path` | **存在但从未使用**（line 108 声明，0 处引用） |
| `cleanup_zombies` 调用点 | `backend/main.py:45` startup lifespan hook |
| 取消 / 手动清理 API | `POST /api/analyze/{id}/mark_error` (P2.14) + `POST .../cancel` (P2.21) |
| Legacy `TradingAgentsStrategy_logs/` | dev box 已无，新代码未写入（v0.3.0 之后兼容读取 shim 保留） |

> ⚠️ **关键警告**：本文**没有改任何代码**。所有"应该改"都是建议，重构 roadmap 在 §7。

---

## 1. 三个聚合根 (Aggregate Roots)

### 1.1 `TaskSummary` — LogContext 的"任务卡片"聚合根

#### 1.1.1 元数据

```python
# backend/core/log_store.py:47-61
@dataclass
class TaskSummary:
    analysis_id: str
    ticker: str
    trade_date: str
    task_dir_name: str       # 格式: "{YYYY-MM-DD}_run{NN}"
    status: str              # pending | running | completed | error
    signal: str              # "" | "Buy" | "Sell" | "Hold"
    elapsed_sec: float
    started_at: float        # epoch seconds
    finished_at: float | None
    chunk_counts: dict[str, int]   # {"llm": int, "tool": int, "agent_output": int}
    is_legacy: bool = False
```

#### 1.1.2 DDD 角色分解

| 概念 | 类型 | 说明 |
|---|---|---|
| **聚合根** | `TaskSummary`（值对象化） | UI 列表 / 详情卡片 |
| **Entities** | （不强） | TaskSummary 本身是 read-model，没有子聚合 |
| **Value Objects** | `Ticker` (6 位代码), `TradeDate` (YYYY-MM-DD), `TaskDirName` (date_runNN), `AnalysisId`, `Signal`, `Status` | 无独立类，靠 string 约束 |
| **Domain Events** | （隐式）| `task.created` / `task.started` / `task.stage_completed` / `task.finalized` — 通过 meta.json 字段变化表达，无显式事件总线 |
| **Invariants** | 1. `task_dir_name` 格式 = `{YYYY-MM-DD}_runNN`<br>2. `chunk_counts` 总和 == 实际 jsonl 行数（**没强制校验**，见 §6.4）<br>3. `status ∈ {pending, running, completed, error}`（**schema 校验缺**） | |
| **持久化** | `~/.tradingagents/logs/{ticker}/{date}_run{NN}/meta.json` | |
| **生命周期** | `LogWriter.__init__` → append_chunk (每次更新 chunk_counts，每 10 chunk flush meta) → `update_stages` → `finalize` | |

#### 1.1.3 关键字段语义

```python
# backend/core/log_store.py:366-380 — LogWriter.__init__ 写初始 meta
{
  "analysis_id": "<uuid>",
  "ticker": "600595",
  "trade_date": "2026-07-17",
  "task_dir_name": "2026-07-17_run01",
  "status": "running",           # 初始
  "signal": "",
  "elapsed_sec": 0.0,
  "started_at": 1784250518.319,  # epoch seconds (float)
  "finished_at": null,
  "error": null,
  "stages_completed": [],
  "chunk_counts": {"llm":0, "tool":0, "agent_output":0},
  "created_at": 1784250518.319
}
```

```python
# backend/core/log_store.py:417-428 — finalize() 覆盖字段
updates = {
    "status": "completed" | "error",
    "signal": "<Buy|Sell|Hold|>",
    "elapsed_sec": <float>,
    "finished_at": time.time(),
    "error": <str | None>,
    "chunk_counts": <dict>,
}
```

#### 1.1.4 反模式识别 (Anti-patterns)

1. **TaskSummary 是 dataclass，但被当作 DTO + Entity 双重角色**：
   - 作为 Entity：它有 identity (`analysis_id`) 和 lifecycle (running → completed)
   - 作为 DTO：它从 meta.json 直接 deserialize，没有领域方法（`start()` / `complete()` / `fail()`）
   - **缺领域方法** → 所有状态转换逻辑散在 `LogWriter._write_meta_field`
2. **Status / Signal 没有 Enum**：字符串散在 4+ 处（`log_store.py` × 2、`api/logs.py` × 1、`web/components/logs_panel.py` × 1、`_SIGNAL_KEYWORDS` × 1）
3. **schema 无版本号**：未来加字段（比如 `model` / `provider`）靠 `from_dict.get(key, default)` 隐式迁移，老 meta.json 会缺字段 → silent default

---

### 1.2 `LogChunk` — LogContext 的"流式事件"子实体

#### 1.2.1 元数据

```python
# backend/core/log_store.py:64-81
@dataclass
class LogChunk:
    ts: float                # epoch seconds
    type: str                # "llm" | "tool" | "agent_output"
    agent: str               # "market_analyst" | "tool" | ...
    role: str | None = None  # 仅 LLM: "user" | "assistant"
    tokens_in: int | None = None
    tokens_out: int | None = None
    content: str | None = None   # llm 或 agent_output
    tool: str | None = None      # 仅 tool
    input: dict | None = None    # 仅 tool
    output: str | None = None    # 仅 tool
    report_key: str | None = None # 仅 agent_output (e.g. "market_report")

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}
```

#### 1.2.2 DDD 角色分解

| 概念 | 类型 | 说明 |
|---|---|---|
| **聚合根** | `LogChunk`（append-only 不可变值对象） | 每条 chunk 是事实，append-only |
| **Entities** | （无） | 没有独立 lifecycle |
| **Value Objects** | `Type ∈ {"llm", "tool", "agent_output"}`, `Agent`, `Role`, `TokensIn/Out`, `ReportKey`, `Timestamp` | |
| **Invariants** | 1. `type ∈ {"llm", "tool", "agent_output"}` (line 384 校验)<br>2. 文件名 == `_FILENAME_FROM_TYPE[type]` (双向映射)<br>3. **ts 必须递增**（**没强制**，但 stream_chunks 排序 by ts） | |
| **持久化** | per-task `~/.tradingagents/logs/{ticker}/{date}_run{NN}/{llm_messages,tool_calls,agent_outputs}.jsonl` | |
| **写入路径** | `LogWriter.append_chunk(chunk)` → `fcntl.flock(LOCK_EX)` → `f.write(line)` → `LOCK_UN` → `chunk_counts[type] += 1` | |
| **读取路径** | `LogStore.stream_chunks()` → 读 3 个 jsonl → sort by ts → yield | |

#### 1.2.3 类型分发表 (Schema)

| chunk.type | filename | agent 域 | 必有字段 | 可选字段 |
|---|---|---|---|---|
| `llm` | `llm_messages.jsonl` | `research_manager` / `risk_manager` / `trader`（来自 `_classify_chunk` in `web/runner.py:191`）| `agent`, `content` | `role`, `tokens_in`, `tokens_out` |
| `tool` | `tool_calls.jsonl` | tool name | `agent`, `tool`, `input`, `output` | (none) |
| `agent_output` | `agent_outputs.jsonl` | 9 report keys → 9 agent names | `agent`, `report_key`, `content` | (none) |

> **注**：当前 `_classify_chunk` (web/runner.py:191-245) **只 yield 12 种组合**（9 agent_output + 3 llm）。其他 LangGraph state 字段（`messages`, `sender`, `sender_agent` 等）都被丢弃。

#### 1.2.4 三个 dict-key 双射

```python
# backend/core/log_store.py:29-35
_CHUNK_TYPES = ("llm_messages", "tool_calls", "agent_outputs")          # 仅 filename 元组
_TYPE_FROM_FILENAME = {
    "llm_messages.jsonl":  "llm",
    "tool_calls.jsonl":    "tool",
    "agent_outputs.jsonl": "agent_output",
}
_FILENAME_FROM_TYPE = {v: k for k, v in _TYPE_FROM_FILENAME.items()}
```

⚠️ **加新类型要改 4 处**：(1) `_CHUNK_TYPES` (2) `_TYPE_FROM_FILENAME` (3) `LogChunk.type` 注释 (4) `api/logs.py:138` 校验集合。**这是明显的 Enum 候选**（R2）。

---

### 1.3 `HistoryEntry` — AnalysisContext 跨上下文持久化

#### 1.3.1 元数据

```python
# backend/core/history_store.py:43-94
@dataclass
class HistoryEntry:
    analysis_id: str                # "{ticker}_{date}_{8-hex}"
    ticker: str
    trade_date: str
    signal: str = ""                # "" | "Buy" | "Sell" | "Hold"
    elapsed: float = 0.0
    status: str = "pending"         # pending | running | completed | error
    error: str | None = None
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    results_path: str = ""          # → ~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json
```

#### 1.3.2 DDD 角色分解

| 概念 | 类型 | 说明 |
|---|---|---|
| **聚合根** | `HistoryEntry` | 整个 entry 是 unit-of-consistency，跨进程 crash 恢复 |
| **Value Objects** | `AnalysisId`, `Ticker`, `TradeDate`, `Signal`, `Status`, `Error`, `StageId`, `ReportKey` | 同样靠 string 约束 |
| **Invariants** | 1. `status ∈ {pending, running, completed, error}`（**schema 校验缺**，line 195 仅接受 enum 不拒）<br>2. `signal ∈ {"", "Buy", "Sell", "Hold"}`（代码**只判 uppercase 含 BUY/SELL/HOLD**，不限 vocabulary，可能产生 `BullishBuy` 这种脏值）<br>3. `results_path` 路径存在或可解析（API 层 `report` endpoint 才校验）<br>4. `started_at` ⇒ status=running, `finished_at` ⇒ status∈{completed, error}（隐式，schema 不强制） | |
| **持久化** | per-id `~/.tradingagents/logs/history/{analysis_id}.json` | |
| **生命周期** | `HistoryStore.create(ticker, date, status=running)` → `mark_running` / `mark_stage_done` / `set_results_path` → `mark_complete` 或 `mark_error` | |
| **Domain Events** | 隐式：`history.running` → `stage.start` → `stage.done` → `analysis.complete` / `analysis.error` | |

#### 1.3.3 关键字段语义 & 写入时序

```python
# web/runner.py:248-290 — run_one_analysis (canonical entry)
entry = _history_store.create(ticker, trade_date, status="running")   # (1) 创建 entry
analysis_id = entry.analysis_id
tracker = ProgressTracker(analysis_id=analysis_id, ...)
_run(...)                                                            # (2) 跑图，写 H2 chunks
_history_store.mark_complete(                                        # (3) 收尾
    analysis_id, signal=..., elapsed=..., completed_stages=...
)
_history_store.set_results_path(                                     # (4) 写 full_states_log 路径
    analysis_id, results_path
)
```

#### 1.3.4 Anti-patterns

1. **`stage_reports` 与 `completed_stages` 双源真相**：
   - `completed_stages` 用 stage_id 索引（来自 `web/progress.STAGE_IDS`）
   - `stage_reports` 用 report_key 索引（来自 LangGraph chunk field name，比如 `"market_report"`）
   - P2.25 hotfix 修过 key 不一致，但**两个 key 集合仍然可能不同步**（如果某 stage_id 没有对应 report_key）
2. **`signal` 校验只判 uppercase 包含**，不限 vocabulary → 脏值会进 history
3. **没有 stage_reports cleanup on rerun**：删除 entry → 新 entry 不存在这个隐患，但旧 API `delete + intent` 后旧 stage_reports **保留在 meta 里**直到新分析完成（race window）
4. **`results_path` 是字符串路径**，不是 `Path` 对象 → API 层需要 `Path(...)` wrap（`api/history.py:155` 做了）

---

## 2. 仓储 (Repository) 设计

### 2.1 `LogStore` (read-only singleton)

#### 2.1.1 类签名

```python
# backend/core/log_store.py:95-319
class LogStore:
    LOGS_ROOT = _LOGS_ROOT                              # class-level 常量
    CHUNK_TYPES = _CHUNK_TYPES

    def list_tickers(self) -> list[str]
    def list_tasks(self, ticker: str) -> list[TaskSummary]
    def get_meta(self, ticker: str, task_dir_name: str) -> dict
    def count_chunks(self, ticker: str, task_dir_name: str) -> dict[str, int]
    def stream_chunks(self, ticker: str, task_dir_name: str,
                      type_filter: str | None = None) -> Iterator[LogChunk]
```

#### 2.1.2 单例模式

```python
# backend/core/log_store.py:451-459
_log_store_singleton: LogStore | None = None

def get_log_store() -> LogStore:
    global _log_store_singleton
    if _log_store_singleton is None:               # 无锁检查（module import 是单线程）
        _log_store_singleton = LogStore()
    return _log_store_singleton
```

**简化 DCL**，因为模块 import 是单线程的。但 FastAPI + Streamlit 双进程时会创建两个独立实例（跨进程隔离）。

#### 2.1.3 Legacy 兼容 shim

`list_tasks` 顺序处理 new → legacy：

```python
# backend/core/log_store.py:152-214
# 1. 先扫新结构: ticker_dir.glob("*/meta.json")
for meta_file in sorted(ticker_dir.glob("*/meta.json")):
    ...
# 2. 再扫 legacy: ticker_dir/TradingAgentsStrategy_logs/full_states_log_*.json
#    但 seen_dates 内的 trade_date 跳过 (new wins)
legacy_dir = ticker_dir / _LEGACY_DIR_NAME  # "TradingAgentsStrategy_logs"
if legacy_dir.is_dir():
    for legacy_file in sorted(legacy_dir.glob(f"{_LEGACY_FILENAME_PREFIX}*.json")):
        date_part = stem[len(_LEGACY_FILENAME_PREFIX):]
        if date_part in seen_dates: continue   # ← 防重复
        ...
```

`get_meta` 同模式：先查 new，fallback legacy，否则 `FileNotFoundError` (line 250)。

#### 2.1.4 设计评价

- ✅ **read-only 单一职责**：UI 只读，不污染 disk
- ✅ **legacy shim 优雅**：new 优先 + 日期去重，零侵入
- ⚠️ **list_tickers 全量扫盘**：每次 N×M 次 `stat()`（N=tickers, M=tasks），无缓存。dev box 20 tasks 没问题，prod 100+ ticker 会慢
- ⚠️ **stream_chunks 全量加载到内存**：`chunks: list[LogChunk] = []` + `chunks.sort(key=lambda c: c.ts)`（line 314）→ 10000 chunks 会占 50+ MB。可以 yield-from-sorted-heap，但当前是 list

---

### 2.2 `LogWriter` (append-only, per-task)

#### 2.2.1 类签名

```python
# backend/core/log_store.py:339-447
class LogWriter:
    def __init__(self, analysis_id: str, ticker: str, trade_date: str)
    def append_chunk(self, chunk: LogChunk) -> None
    def update_stages(self, completed_stages: list[str]) -> None
    def finalize(self, signal: str, elapsed_sec: float,
                 error: str | None = None,
                 completed_stages: list[str] | None = None) -> None
```

#### 2.2.2 目录 & 编号策略

```python
# backend/core/log_store.py:342-358
existing = sorted(p.name for p in ticker_dir.glob(f"{trade_date}_run*"))
if existing:
    last_n = max(int(p.split("_run")[1]) for p in existing)
    run_nn = f"run{last_n + 1:02d}"      # "run01", "run02", ..., "run99"
else:
    run_nn = "run01"

self.task_dir = ticker_dir / f"{trade_date}_{run_nn}"
self.task_dir.mkdir(parents=True, exist_ok=False)  # ← FileExistsError 强制唯一
```

⚠️ **无并发保护**：两个 LogWriter 同时 init 同一 (ticker, date) 时，`exist_ok=False` 会让后到的抛 `FileExistsError`。`web/runner.py:128` 在 `_run` 内创建 LogWriter，而 batch_job / scheduler 也会触发 _run → **同一 ticker+date 并发 run 必然冲突**。当前 dev box 是单 batch 顺序跑，所以没爆。

#### 2.2.3 fcntl.flock 加锁 (局部)

```python
# backend/core/log_store.py:382-402
def append_chunk(self, chunk: LogChunk) -> None:
    if chunk.type not in _FILENAME_FROM_TYPE:
        raise ValueError(f"Unknown chunk type: {chunk.type!r}")
    filename = _FILENAME_FROM_TYPE[chunk.type]
    path = self.task_dir / filename
    line = json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n"

    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)         # ← 只锁 append_chunk
        try:
            f.write(line)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    self.chunk_counts[chunk.type] = self.chunk_counts.get(chunk.type, 0) + 1

    # Update meta chunk_counts every 10 chunks (avoid fs churn)
    total = sum(self.chunk_counts.values())
    if total % 10 == 0:
        self._write_meta_field("chunk_counts", dict(self.chunk_counts))  # ← 无锁
```

> **注释自己说 "Uses fcntl.flock for safety" 但只锁了 append_chunk**。`_write_meta_field` 是 read-modify-write，无 fcntl。

#### 2.2.4 原子 meta.json 写 (局部)

```python
# backend/core/log_store.py:434-447
def _write_meta(self, data: dict) -> None:
    """Atomic write (write to .tmp, then rename)."""
    tmp = self._meta_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(self._meta_path())                # ← 单文件 rename 原子

def _write_meta_field(self, field: str, value: Any) -> None:
    """Read meta, update one field, write back."""
    path = self._meta_path()
    data = json.loads(path.read_text(encoding="utf-8"))  # ← 无锁读
    data[field] = value
    self._write_meta(data)                            # ← 原子 rename，但 read-modify-write 整体无锁
```

**单次 _write_meta 原子**（tmp + rename），但**多次 _write_meta_field 并发** 会出现：
- T1: read meta → 改 chunk_counts
- T2: read meta → 改 stages_completed
- T1: write meta (T2 改动丢失)
- T2: write meta (T1 改动丢失)

#### 2.2.5 finalize 收尾

```python
# backend/core/log_store.py:408-428
def finalize(self, signal, elapsed_sec, error=None, completed_stages=None):
    status = "error" if error else "completed"
    updates = {
        "status": status, "signal": signal, "elapsed_sec": elapsed_sec,
        "finished_at": time.time(), "error": error,
        "chunk_counts": dict(self.chunk_counts),
    }
    if completed_stages is not None:
        updates["stages_completed"] = completed_stages
    for k, v in updates.items():        # ← 6 次顺序 read-modify-write
        self._write_meta_field(k, v)
```

**6 次串行 _write_meta_field**，每次都 read + rename。**中断恢复弱**：如果 finalize 在第 3 个字段（`signal`）后崩溃，meta.json 会停留在 `status=running, signal=Buy, finished_at=None` 的"中间态" → 启动时 cleanup_zombies 会扫到 elapsed > STUCK_THRESHOLD → mark_error，但丢失 signal。

---

### 2.3 `HistoryStore` (read/write singleton)

#### 2.3.1 类签名

```python
# backend/core/history_store.py:97-341
class HistoryStore:
    _instance: "HistoryStore | None" = None
    _lock = __import__("threading").Lock()

    def __init__(self) -> None:
        self._lock_path = __import__("threading").Lock()  # 声明但从未使用!

    @classmethod
    def get_instance(cls) -> "HistoryStore":  # DCL 单例
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── write (8 methods) ──
    def create(self, ticker, trade_date, status="running", analysis_id=None) -> HistoryEntry
    def update(self, entry) -> None
    def mark_running(self, analysis_id) -> HistoryEntry | None
    def mark_stage_done(self, analysis_id, stage_id, report="", report_key=None) -> None
    def mark_complete(self, analysis_id, signal, elapsed, completed_stages) -> None
    def mark_error(self, analysis_id, error, elapsed=0.0) -> None
    def set_results_path(self, analysis_id, path) -> None
    def delete(self, analysis_id) -> None

    # ── read (3 methods) ──
    def get(self, analysis_id) -> HistoryEntry | None
    def list_all(self, ticker=None, signal=None, status=None,
                 limit=50, offset=0) -> tuple[list[HistoryEntry], int]
    def find_by_ticker_date(self, ticker, trade_date) -> HistoryEntry | None

    # ── P2.14 + P2.21 operations (2 methods) ──
    @staticmethod
    def is_zombie(entry, now=None) -> bool
    def cleanup_zombies(self, now=None) -> list[str]
```

#### 2.3.2 DCL 单例 + **未使用的 _lock_path**

```python
# backend/core/history_store.py:104-116
class HistoryStore:
    _instance: "HistoryStore | None" = None
    _lock = __import__("threading").Lock()

    def __init__(self) -> None:
        self._lock_path = __import__("threading").Lock()  # ← 声明，从来没被引用

    @classmethod
    def get_instance(cls) -> "HistoryStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
```

`_lock_path` 是 dead code —— 作者预留了 per-file 锁但没实现。每个 `mark_*` 内部 `read-modify-write` 都是无锁的。

#### 2.3.3 list_all filter + pagination

```python
# backend/core/history_store.py:227-257
def list_all(self, ticker=None, signal=None, status=None, limit=50, offset=0):
    """List entries with optional filters, returns (entries, total)."""
    if not _HISTORY_DIR.exists(): return [], 0

    entries: list[HistoryEntry] = []
    for f in _HISTORY_DIR.glob("*.json"):
        try: d = json.loads(f.read_text(encoding="utf-8"))
        except: continue
        entry = HistoryEntry.from_dict(d)

        if ticker and ticker.upper() not in entry.ticker.upper(): continue  # 模糊包含
        if signal and entry.signal != signal: continue
        if status and entry.status != status: continue
        entries.append(entry)

    entries.sort(key=lambda e: e.created_at, reverse=True)
    total = len(entries)
    return entries[offset : offset + limit], total
```

⚠️ **性能坑**：全量读 + 全量 sort + 全量 filter。dev box 67 entries → 67 read + 67 JSON parse + 67 sort + skip。1000 entries 时瓶颈明显。

#### 2.3.4 `_write` 的静默失败

```python
# backend/core/history_store.py:358-367
def _write(self, entry: HistoryEntry) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = self._path(entry.analysis_id)
        path.write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # Non-critical  ← !!! 吞所有异常 !!!
```

⚠️ **silent swallow**：写历史失败时（磁盘满 / EACCES / 路径过长）完全静默。**比 race condition 更危险** —— 用户看到 status=running 但 disk 上 entry 缺失 → 找不到 `analysis_id`。

#### 2.3.5 zombie & stuck 检测 (P2.14 + P2.21)

```python
# backend/core/history_store.py:269-306
@staticmethod
def is_zombie(entry, now=None):
    """P2.14 zombie: status=running + elapsed==0 + 老于 60s
       P2.21 stuck:   status=running + elapsed>0  + 大于 600s (10 min)"""
    if now is None: now = time.time()
    if entry.status != "running": return False

    # True zombie: never moved
    if entry.elapsed == 0.0 and not entry.completed_stages:
        return (now - entry.created_at) > ZOMBIE_THRESHOLD_SEC    # 60s

    # Stuck: has moved but is taking too long
    if entry.elapsed > 0:
        return entry.elapsed > STUCK_THRESHOLD_SEC                # 600s

    return False

def cleanup_zombies(self, now=None):
    """Mark all zombie + stuck entries as error."""
    if now is None: now = time.time()
    cleaned: list[str] = []
    entries, _ = self.list_all(limit=1000, offset=0)
    for entry in entries:
        if not self.is_zombie(entry, now=now): continue
        if entry.elapsed == 0.0 and not entry.completed_stages:
            reason = "分析被中断 (server restart, thread was SIGKILL'd)"
        else:
            reason = (
                f"分析超时被清理 (elapsed={entry.elapsed:.1f}s > "
                f"{STUCK_THRESHOLD_SEC:.0f}s, 可能卡在 "
                f"{entry.completed_stages[-1] if entry.completed_stages else '未知'} 阶段)"
            )
        self.mark_error(entry.analysis_id, error=reason, elapsed=entry.elapsed or 0.0)
        cleaned.append(entry.analysis_id)
    return cleaned
```

**调用点仅 1 处**：`backend/main.py:43-55` 的 `lifespan` startup hook。

---

## 3. 两套日志 / 历史系统 — 关系

### 3.1 架构图

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       LangGraph stream (web/runner.py)                      │
│                                                                            │
│   for chunk in graph.graph.stream(init_state):                             │
│       _classify_chunk(chunk, stats) → Iterator[LogChunk]                   │
│                  ↓                  ↓                  ↓                   │
│             LogWriter.append_chunk  (write H2)                            │
│                  ↓                                                          │
│             {meta.json, llm_messages.jsonl, tool_calls.jsonl,              │
│              agent_outputs.jsonl}                                          │
└────────────────────────────────────────────────────────────────────────────┘
                  ↓                                            ↓
   ┌──────────────────────────────┐         ┌──────────────────────────────────┐
   │  H2 LogContext (run-time)     │         │  H1 HistoryContext (cross-run)   │
   │                               │         │                                  │
   │  LogWriter (per-task, fcntl) │         │  HistoryStore (singleton,       │
   │  LogStore  (read-only)        │         │   threading.Lock unused)         │
   │                               │         │                                  │
   │  持久化:                       │         │  持久化:                          │
   │  ~/.tradingagents/logs/        │         │  ~/.tradingagents/logs/history/  │
   │    {ticker}/                   │         │    {analysis_id}.json            │
   │      {date}_runNN/             │         │                                  │
   │        meta.json               │         │  Operations:                     │
   │        llm_messages.jsonl      │         │  - is_zombie / cleanup_zombies   │
   │        tool_calls.jsonl        │         │  - P2.14 (60s) / P2.21 (600s)    │
   │        agent_outputs.jsonl     │         │                                  │
   │                               │         │  Run / cancel / mark_error:      │
   │  Read by:                      │         │  - POST /api/analyze/{id}/run    │
   │  - GET /api/logs/* (5)         │         │  - POST /api/analyze/{id}/cancel │
   │  - web/components/logs_panel   │         │    (P2.21 hotfix)                │
   │                               │         │  - POST .../mark_error (P2.14)   │
   │                               │         │                                  │
   │                               │         │  Read / delete / rerun:          │
   │                               │         │  - GET/DELETE /api/history/*     │
   └──────────────────────────────┘         └──────────────────────────────────┘
                  ↓                                            ↓
                  └────────────────────┬───────────────────────┘
                                       ↓
                          ┌──────────────────────────────┐
                          │   Cross-cutting writes       │
                          │   web/runner.py:260, 274,    │
                          │     279, 289                 │
                          │   _history_store.create /    │
                          │     mark_error / mark_complete│
                          │     / set_results_path       │
                          └──────────────────────────────┘
```

### 3.2 5 个交叉点 (Critical Coupling Points)

| # | 路径 | 触发 | 一致性 |
|---|---|---|---|
| 1 | `web/runner.py:128` LogWriter 创建 | `_run` 内，每次分析 | task_dir_name 跟 history.analysis_id **不同**（task_dir 用 runNN，history 用 UUID 8-hex）|
| 2 | `web/runner.py:147` append_chunk | 每个 LangGraph chunk | 跟 HistoryStore.mark_stage_done **无强一致**（两个独立文件）|
| 3 | `web/runner.py:260` _history_store.create | run_one_analysis 入口 | analysis_id 跟 LogWriter 的 analysis_id 是**同一个**（通过 `_run` 参数传入）|
| 4 | `web/runner.py:274` mark_error | _run 抛异常 | 只更新 history，LogWriter 在 line 171-174 try/except 也调 finalize，但任一失败另一边收不到 |
| 5 | `web/runner.py:289` set_results_path | finalize 之后 | results_path = `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json`，由 `_log_state()` 写 |

### 3.3 信息冗余 (Information Redundancy)

| 字段 | H1 (HistoryStore) | H2 (LogStore.meta.json) | 同步？ |
|---|---|---|---|
| analysis_id | ✓ | ✓ | 显式同步（_run 参数传入）|
| ticker | ✓ | ✓ | 显式同步 |
| trade_date | ✓ | ✓ | 显式同步 |
| status | ✓ | ✓ | **隐式同步**（run_one_analysis 顺序保证，但 race window）|
| signal | ✓ | ✓ | **隐式同步**（run_one_analysis line 281-283）|
| elapsed | ✓ | ✓ (elapsed_sec) | **隐式同步** |
| finished_at | ✓ | ✓ | **隐式同步** |
| chunk_counts | ✗ | ✓ | **H1 不知道 chunks 数量**（潜在 data loss signal）|
| stage_reports | ✓ | ✗ | **H2 没有 stage_reports 字段**（LogStore.TaskSummary 没 stage_reports，只 LogChunk 里有）|
| results_path | ✓ | ✗ | H2 不存 results_path |

⚠️ **schema drift 风险**：H1 加字段（比如 model/provider）H2 不会有；H2 加字段（比如 chunk latency）H1 不会有。

---

## 4. 完整 API 端点 (10 个)

### 4.1 Logs API (5 endpoints) — `backend/api/logs.py`

#### 4.1.1 `GET /api/logs/tickers`

| 项 | 值 |
|---|---|
| 实现 | `list_tickers()` (line 54) |
| Query params | (none) |
| Response | `{"tickers": [{"ticker", "task_count", "latest_signal", "latest_status", "latest_trade_date"}, ...], "total": int}` |
| 错误 | (none — empty if no logs) |
| 性能 | 全量 `iterdir` + `glob("*/meta.json")` + per-meta `stat` |

#### 4.1.2 `GET /api/logs/tasks`

| 项 | 值 |
|---|---|
| 实现 | `list_tasks(ticker)` (line 79) |
| Query params | `ticker: str` |
| Validation | `_safe_segment(ticker)` 拒绝 `/`, `\`, `..`, NUL |
| Response | `{"ticker", "tasks": [TaskSummary dict], "total": int}` |
| 错误 | 404 if ticker not in `list_tickers()` |

#### 4.1.3 `GET /api/logs/task`

| 项 | 值 |
|---|---|
| 实现 | `get_task(ticker, task)` (line 111) |
| Query params | `ticker: str`, `task: str` (date_runNN) |
| Validation | `_safe_segment` × 2 |
| Response | `{"meta": {...}, "chunk_counts": {...}, "ticker", "task"}` |
| 错误 | 404 (FileNotFoundError → HTTPException) |

#### 4.1.4 `GET /api/logs/chunks`

| 项 | 值 |
|---|---|
| 实现 | `get_chunks(ticker, task, type)` (line 126) |
| Query params | `ticker: str`, `task: str`, `type: "llm"\|"tool"\|"agent_output"\|None` |
| Validation | `_safe_segment` × 2 + type whitelist |
| Response | `{"ticker", "task", "type", "chunks": [LogChunk dict], "total": int, "counts": {type: count}}` |
| 错误 | 400 (invalid type), 404 implicit (no chunks) |
| 性能 | 全量加载到内存 + sort by ts |

#### 4.1.5 `GET /api/logs/counts`

| 项 | 值 |
|---|---|
| 实现 | `get_counts(ticker, task)` (line 159) |
| Query params | `ticker: str \| None`, `task: str \| None` |
| 3 modes | 1) ticker+task: 单 task counts<br>2) ticker only: 跨 task 累加 counts<br>3) neither: 跨 ticker 累加 counts |
| Response | `{"ticker", "task"?, "counts" \| "tickers" \| "grand_total"}` |
| 错误 | (none) |

⚠️ 注意：**mode 2 / 3 读的是 `meta.chunk_counts` 字段**，不是实际 jsonl 行数（`count_chunks` 才是实际行数）。meta 与实际可能不一致（见 §6.4）。

---

### 4.2 History API (5 endpoints) — `backend/api/history.py`

#### 4.2.1 `GET /api/history`

| 项 | 值 |
|---|---|
| 实现 | `list_history(...)` (line 49) |
| Query params | `limit=20`, `offset=0`, `ticker=None`, `signal=None`, `status=None`, `min_elapsed=None`, `max_elapsed=None` |
| Validation | (none — 脏 signal 也会过 schema) |
| Response | `HistoryResponse { items: List[HistoryItem], total, limit, offset }` |
| 性能 | 全量读 history/*.json + 全量 filter + 全量 sort |

#### 4.2.2 `GET /api/history/{analysis_id}`

| 项 | 值 |
|---|---|
| 实现 | `get_history(analysis_id)` (line 90) |
| Response | `entry.to_dict()` (full dict incl. `results_path`, `stage_reports`, `completed_stages`) |
| 错误 | 404 if not in history dir |
| 备注 | **没有 path safety 校验**——`analysis_id` 直接喂给 `_path()` → `Path / f"{analysis_id}.json"`。如果前端传入 `../../etc/passwd` 会被 `_path` 接受成 `~/.tradingagents/logs/history/../../etc/passwd` → 实际 `read_text` 不存在的路径会 FileNotFoundError，但 `path.write_text` 能写出到意外位置。**潜在的 path traversal**（虽然 `_read` / `delete` 都只读已存在文件，影响小，但仍然是不规范） |

#### 4.2.3 `DELETE /api/history/{analysis_id}`

| 项 | 值 |
|---|---|
| 实现 | `delete_history(analysis_id)` (line 106) |
| Response | `{"ok": True, "analysis_id": ...}` |
| 错误 | (none — 幂等：entry 不存在也返 200) |
| 备注 | **不级联删 logs/{ticker}/{date}_runNN/**（见 §6.11）|

#### 4.2.4 `POST /api/history/{analysis_id}/rerun`

| 项 | 值 |
|---|---|
| 实现 | `rerun_history(analysis_id)` (line 118) |
| Response | `{"ok": True, "start_analysis": {"ticker", "trade_date"}, "analysis_id": ...}` |
| 行为 | 1) `store.get(analysis_id)` 拿 ticker+date<br>2) `store.delete(analysis_id)`<br>3) 返回 `{ticker, trade_date}` 给前端 |
| **缺口** | **只返 intent，没启动新分析**（见 §6.9）。前端需要再调 `POST /api/analyze` 才能真正跑。**不是原子操作** |
| 错误 | 404 if entry not found |

#### 4.2.5 `GET /api/history/{analysis_id}/report`

| 项 | 值 |
|---|---|
| 实现 | `get_history_report(analysis_id)` (line 141) |
| 数据源 | 1) `entry.results_path` if exists<br>2) Fallback: `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json` |
| Response | `{"analysis_id", "ticker", "trade_date", "results_path", "report": <full JSON>}` |
| 错误 | 404 if neither path exists, 500 if read fails |
| 备注 | **返 JSON 不是 markdown**（见 §6.12）—— frontend 需要再解析 `final_trade_decision` 等字段 |

---

## 5. 运维管理特性 (Operations Features)

### 5.1 僵尸分析清理 (P2.14 Hotfix)

| 项 | 值 |
|---|---|
| 触发 | `backend/main.py:45` `lifespan` startup hook |
| 检测 | `HistoryStore.is_zombie(entry)` static method |
| 阈值 | `ZOMBIE_THRESHOLD_SEC = 60.0` (line 32) |
| 条件 | `status=running AND elapsed==0 AND completed_stages==[] AND (now - created_at) > 60s` |
| 行动 | `mark_error(analysis_id, error="分析被中断 (server restart, thread was SIGKILL'd)")` |
| 根因 | uvicorn restart SIGKILL 旧 PID → worker thread 死 → history.json 留 status=running 但无 thread 推进 |
| 幂等 | ✓ 干净 store 是 no-op |

### 5.2 卡死分析清理 (P2.21 Hotfix)

| 项 | 值 |
|---|---|
| 触发 | 同上 `cleanup_zombies` |
| 阈值 | `STUCK_THRESHOLD_SEC = 600.0` (line 40) |
| 条件 | `status=running AND elapsed > 600s` |
| 行动 | `mark_error(analysis_id, error=f"分析超时被清理 (elapsed={...}s > 600s, 可能卡在 {stage} 阶段)")` |
| 根因 | 用户报告 `600595_2026-07-16_1589cdfd` 跑了 8.2 小时做 8/12 stages 然后卡死（LLM API hang + mootdx port unreachable），原 P2.14 只判 `elapsed==0` 漏掉了 |
| 关联 | `backend/core/runner.py:104 MAX_RUN_SEC = 600` 跟 STUCK_THRESHOLD_SEC 同步 |

### 5.3 路径安全 (Path Safety)

#### 5.3.1 `backend/api/logs.py:35-50`

```python
def _safe_segment(value: str, *, label: str) -> str:
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if "/" in value or "\\" in value or ".." in value or "\x00" in value:
        raise HTTPException(status_code=400, detail=...)
    return value
```

5 个 endpoint 全部用此守卫：line 82, 114, 115, 136, 137, 168, 171。

#### 5.3.2 `tradingagents/dataflows/utils.py: safe_ticker_component`

```python
# backend/api/chart.py:65 (comment) 引用：
# """Strict 6-digit A-share code validation. Mirrors ``safe_ticker_component``."""
```

⚠️ **不统一**：`/api/chart` 用 6 位正则，`/api/logs` 用 blacklist。`/api/history` 完全没校验。**应该统一进 `backend/api/_validators.py`**。

### 5.4 并发控制 (Concurrency Control)

#### 5.4.1 LogWriter: fcntl.flock 局部

```python
# backend/core/log_store.py:382-402
def append_chunk(self, chunk: LogChunk) -> None:
    ...
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try: f.write(line)
        finally: fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    self.chunk_counts[chunk.type] = self.chunk_counts.get(chunk.type, 0) + 1
    if total % 10 == 0:
        self._write_meta_field("chunk_counts", dict(self.chunk_counts))  # ← 无锁
```

- ✅ append_chunk 有 flock
- ❌ _write_meta / _write_meta_field **无锁**（read-modify-write 全裸跑）
- ❌ finalize 6 次串行 _write_meta_field，**整体非原子**

#### 5.4.2 HistoryStore: 单例 + 未使用的 _lock_path

```python
# backend/core/history_store.py:104-116
class HistoryStore:
    _instance: "HistoryStore | None" = None
    _lock = __import__("threading").Lock()  # ← 只锁 get_instance
    def __init__(self) -> None:
        self._lock_path = __import__("threading").Lock()  # ← 声明，从来没用过
```

- ✅ get_instance 是正确 DCL
- ❌ _write **无锁**（read-modify-write 全裸跑）
- ❌ _write 静默吞异常（line 366 `except Exception: pass`）—— 比 race 更危险
- ❌ _lock_path 是 dead code

#### 5.4.3 隐患 (Hazard Inventory)

| 场景 | 后果 |
|---|---|
| 两个 thread 同时 mark_stage_done + mark_complete | 互相覆盖，最后写者赢 |
| thread A mark_running + thread B cleanup_zombies | cleanup 删 A 的 entry，A 后续 mark_* 全 no-op（`_read` 返回 None）|
| uvicorn 重启 + cleanup_zombies | dev box 67 entry → cleanup 把 2 个 zombie mark_error |
| LogWriter.finalize 中途崩溃 | meta 留中间态（status 仍 running，signal 已写入）|
| LogWriter.append_chunk 中途崩溃 | chunk_counts 已 ++ 但 meta 未 flush（每 10 chunk 才写）→ meta 落后 |

### 5.5 文件格式版本 (Format Versioning)

#### 5.5.1 LogStore: 双格式兼容

- **new**: `~/.tradingagents/logs/{ticker}/{date}_runNN/{meta.json, llm_messages.jsonl, tool_calls.jsonl, agent_outputs.jsonl}`
- **legacy**: `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json`
- `LogStore.list_tasks` / `get_meta` 同时读两种格式，new 优先 + 日期去重
- **dev box 当前无 legacy 文件**（post-cleanup?）—— 但代码保留 shim 是对的

#### 5.5.2 HistoryStore: 单 JSON 无版本

```python
# backend/core/history_store.py:43-94
@dataclass
class HistoryEntry:
    analysis_id: str
    ticker: str
    trade_date: str
    signal: str = ""
    elapsed: float = 0.0
    status: str = "pending"
    error: str | None = None
    completed_stages: list[str] = field(default_factory=list)
    stage_reports: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    results_path: str = ""
```

- ⚠️ `from_dict` 全部 `d.get(key, default)` 隐式迁移
- ⚠️ 加新字段不会破坏老 entry（默认 factory）
- ⚠️ 重命名字段会**静默丢数据**（`d.get("old_name")` 返 default，新代码读 `entry.new_name` 是 None）
- ⚠️ 没有 `version` 字段做显式 migration

#### 5.5.3 反序列化校验缺

两个 store 的 `from_dict` / 读 meta.json 都没 schema validation：
- 缺字段 → silent default
- 类型错（比如 `signal` 是 int）→ 运行时崩
- 状态值非法（比如 `status="paused"`）→ 接受，无 invariant enforcement

---

## 6. 现有架构债务 (Architectural Debt)

> ⚠️ **真实 Bug 标记**：第 1, 2, 11 条是真 bug / race condition，应该修。

### 6.1 ⚠️ `[BUG]` LogWriter.meta.json 写无锁

`LogWriter._write_meta_field` (line 442-447) read-modify-write 无 fcntl：
```python
def _write_meta_field(self, field: str, value: Any) -> None:
    path = self._meta_path()
    data = json.loads(path.read_text(encoding="utf-8"))  # ← T1, T2 同时读
    data[field] = value
    self._write_meta(data)                                # ← T1, T2 同时 rename .tmp → meta.json
```

**后果**：batch_job + scheduler 同 ticker+date 并发 → meta 字段互相覆盖。

### 6.2 ⚠️ `[BUG]` HistoryStore._write 无锁 + 静默吞异常

`HistoryStore._write` (line 358-367) 无 threading 锁 + `except: pass`：
```python
def _write(self, entry: HistoryEntry) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = self._path(entry.analysis_id)
        path.write_text(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # Non-critical  ← !!! 吞所有异常 !!!
```

**后果**：
1. 并发 mark_* → 互相覆盖
2. 写失败（disk full / EACCES）→ 完全静默 → 用户看到 status=running 但 disk 没文件

### 6.3 zombie cleanup 被动（只 startup）

`cleanup_zombies` 只在 `backend/main.py:45` 的 FastAPI lifespan 调一次。**runtime 出现的新 zombie 没自动清理**，需要：
- 手动 `POST /api/analyze/{id}/mark_error`（P2.14 hotfix 但 API 路由有点绕）
- 或 `POST /api/analyze/{id}/cancel`（P2.21 hotfix 但**实际不 kill thread**，只是 UI flip status）

**missing**：runtime scanner (60s polling cleanup) 或 webhook 通知。

### 6.4 meta.json chunk_counts vs 实际 jsonl 行数可能不一致

`LogStore.count_chunks` (line 255-272) 读**实际 jsonl 文件**（正确）：
```python
for jsonl_name, chunk_type in _TYPE_FROM_FILENAME.items():
    path = task_dir / jsonl_name
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            result[chunk_type] = sum(1 for _ in f)
```

但 `LogStore.list_tasks` (line 166-180) 读 **meta.json.chunk_counts**（快但可能 stale）：
```python
chunk_counts=meta.get("chunk_counts", {"llm": 0, "tool": 0, "agent_output": 0}),
```

而 `api/logs.py:179, 191` 的 `get_counts(mode 2/3)` 用 `t.chunk_counts`（即 meta 字段）。

**实测**：dev box 600595 的 20 个 run 全是 0/0/0 一致（这些 run 都 pre-graph 失败，没产生 chunk）。但如果 append_chunk 在 `_write_meta_field` 之前崩溃，meta 落后 → API 返 0 → UI 看不到实际 chunks。

### 6.5 log cleanup 缺 — logs 目录无限增长

`~/.tradingagents/logs/{ticker}/{date}_runNN/` **永不删除**。dev box 20 run 已占 ~20 个目录（虽然 440KB 主要是 history，logs 占小），生产环境运行 1 年 → 数千 ticker × 12 月 × ~5 runs ≈ 60000 个目录。

**缺失**：LRU (保留最近 N runs)、TTL (删 > 30 天)、size cap (总大小 > X 删最旧)。

### 6.6 history cleanup 缺 — 同样无限增长

`~/.tradingagents/logs/history/{analysis_id}.json` **永不删除**。dev box 67 entry 占 440KB（含 jsonl 0）。生产环境 1 年 → 数万 entry × ~5KB = 数百 MB。

**缺失**：LRU / TTL / size cap。

### 6.7 chunk_type 字符串散在多处

"llm" / "tool" / "agent_output" 出现位置：
1. `log_store.py:30-35` `_TYPE_FROM_FILENAME` + `_FILENAME_FROM_TYPE`
2. `log_store.py:69` `LogChunk.type` 注释
3. `log_store.py:177, 246, 259, 270` `{"llm": 0, "tool": 0, "agent_output": 0}` 字面量 × 4 处
4. `log_store.py:384` `if chunk.type not in _FILENAME_FROM_TYPE` 校验
5. `api/logs.py:138` `if type not in ("llm", "tool", "agent_output")` 校验
6. `web/components/logs_panel.py:97-99` `counts.get('llm', 0)` 等

加新类型（比如 `system_event`）要改 6+ 处 → **Enum 候选**。

### 6.8 legacy shim 永久保留

`TradingAgentsStrategy_logs/` 目录永远不会被代码主动清理（v0.3.0 加的兼容 shim）。CLAUDE.md 说 v0.3.0 之后没人写 legacy → dev box 已无，但用户升级前可能有大量 legacy 数据。

**问题**：保留是好（兼容）但 dev 不知道何时可以安全删 legacy → 没有 deprecation 日志 / warning。

### 6.9 ⚠️ `[BUG?]` rerun endpoint 半成品

`api/history.py:118-137` `rerun_history`：
```python
def rerun_history(analysis_id: str) -> dict:
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None: raise HTTPException(404, ...)
    payload = {"ticker": entry.ticker, "trade_date": entry.trade_date}
    store.delete(analysis_id)            # ← 删了！
    return {"ok": True, "start_analysis": payload, "analysis_id": analysis_id}
```

**实际行为**：删了 entry，**没有启动新分析**。前端拿到 `{ticker, trade_date}` 后**必须再调** `POST /api/analyze`。**不是原子**——中间崩溃 → entry 没了，新分析没启动。

**应该**：返 `{ticker, trade_date, analysis_id}` + 后端启动后台分析 + 返新 analysis_id。

### 6.10 历史 rerun 不带 stage_reports

`rerun_history` 删除旧 entry → 新 entry 通过 `run_one_analysis` 会自然有 `stage_reports=[]`（从 `field(default_factory=dict)` 来）→ OK。

但 `mark_stage_done` 在 race window 内可能写**老 entry 的 analysis_id**（如果旧 thread 还没完全死）。**不是 rerun 自身的 bug，是全局 race**。

### 6.11 ⚠️ `[BUG]` delete 不级联

`api/history.py:106-114` `delete_history` 只删 `~/.tradingagents/logs/history/{analysis_id}.json`：
```python
def delete(self, analysis_id: str) -> None:
    path = _HISTORY_DIR / f"{analysis_id}.json"
    if path.exists():
        path.unlink()
```

**不删**：
- `~/.tradingagents/logs/{ticker}/{date}_runNN/`（对应的 LangGraph stream chunks）
- `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json`（results_path 指向）

**后果**：删 history 后 logs 还在 → `GET /api/logs/tasks?ticker=...` 仍能查到 → 数据不一致。

### 6.12 report endpoint 不支持 markdown

`api/history.py:141-179` `get_history_report` 返**整个 full_states_log JSON**：
```python
return {"analysis_id", "ticker", "trade_date", "results_path", "report": content}
```

**frontend 需要自己** 解析 `content["final_trade_decision"]` / `content["investment_plan"]` / `content["market_report"]` 等字段并格式化 markdown。

**缺**：后端直接格式化好 markdown 返回（类似 web/components 的 _render_*_report 函数）。

---

## 7. 重构建议 (Refactoring Roadmap)

### 7.1 短期 (1-2 周) — 修真 Bug

#### R1 ⚠️ 加 fcntl.flock 给 LogWriter._write_meta + HistoryStore._write

**目标**：消除 §6.1, §6.2 的 race condition。

**LogWriter._write_meta_field**:
```python
def _write_meta_field(self, field, value):
    with open(self._meta_path(), "r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            data = json.loads(f.read())
            data[field] = value
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**HistoryStore._write**:
```python
def _write(self, entry):
    # Replace silent except with logging + raise
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = self._path(entry.analysis_id)
    with open(path, "r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            data = json.loads(f.read())
            data.update(entry.to_dict())
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

或者用 `fcntl.flock(open(path + ".lock", "w"))` 作为 sidecar lock file。

**优先级**：🔴 高（用户可能在 batch 跑同时手动 rerun → race 真的会发生）。

#### R2 加 ChunkType Enum

**目标**：替换 §6.7 的 6+ 处字符串字面量。

```python
# backend/core/log_store.py
from enum import Enum

class ChunkType(str, Enum):
    LLM = "llm"
    TOOL = "tool"
    AGENT_OUTPUT = "agent_output"

_FILENAME_FROM_TYPE = {
    ChunkType.LLM: "llm_messages.jsonl",
    ChunkType.TOOL: "tool_calls.jsonl",
    ChunkType.AGENT_OUTPUT: "agent_outputs.jsonl",
}
```

连带 `api/logs.py:138` / `web/components/logs_panel.py` 也用 enum value。

#### R3 验证 LogStore.count_chunks 跟实际 jsonl 行数一致

**目标**：§6.4 的 stale meta 风险。

加一个 sanity check CLI（`python -m cli.verify_log_consistency`）：
```python
# Compare meta.json.chunk_counts with actual wc -l of each jsonl
# Print divergences (delta != 0) for ops review
```

或者把 `LogStore.list_tasks` 改成优先用 `count_chunks`（实际行数），慢一点但准确。

### 7.2 中期 (1 月) — 运维体验

#### R4 Log cleanup 策略

**目标**：§6.5

- **LRU by task_count per ticker**: 保留最近 50 runs / ticker
- **TTL**: 删除 > 90 天的 task_dir
- **size cap**: 总 logs > 10GB 时按 mtime 删最旧

实现：`backend/core/log_store.py` 加 `LogStore.gc(max_age_days=90, max_per_ticker=50)` + CLI / 手动调。

#### R5 History cleanup 策略

**目标**：§6.6

同样 LRU + TTL + size cap。`HistoryStore.gc(...)`。

#### R6 升级 rerun endpoint

**目标**：§6.9, §6.10

```python
@router.post("/api/history/{analysis_id}/rerun")
async def rerun_history(analysis_id: str, background_tasks: BackgroundTasks):
    entry = get_history_store().get(analysis_id)
    if entry is None: raise HTTPException(404)
    new_id = f"{entry.ticker}_{entry.trade_date}_{uuid.uuid4().hex[:8]}"
    # Delete old + clear stage_reports (via mark_error old first)
    get_history_store().delete(analysis_id)
    # Schedule new analysis
    background_tasks.add_task(run_one_analysis, entry.ticker, entry.trade_date, config)
    return {"ok": True, "analysis_id": new_id, "ticker": entry.ticker, "trade_date": entry.trade_date}
```

#### R7 Delete 级联

**目标**：§6.11

```python
def delete(self, analysis_id: str) -> None:
    entry = self.get(analysis_id)
    if entry:
        # 1. Delete history entry
        self._path(analysis_id).unlink(missing_ok=True)
        # 2. Delete corresponding logs/{ticker}/{date}_runNN/
        task_dir = _LOGS_ROOT / entry.ticker
        for run_dir in task_dir.glob(f"{entry.trade_date}_run*"):
            if (run_dir / "meta.json").exists():
                d = json.loads((run_dir / "meta.json").read_text())
                if d.get("analysis_id") == analysis_id:
                    shutil.rmtree(run_dir)
        # 3. Optionally delete full_states_log if results_path points to it
        if entry.results_path and Path(entry.results_path).exists():
            Path(entry.results_path).unlink(missing_ok=True)
```

### 7.3 长期 (季度) — 架构升级

#### R8 LogStore 持久化迁移 (JSONL → SQLite)

**目标**：scale 100x+。

- 当前: 3 个 jsonl + meta.json per task, append-only + full scan read
- 目标: SQLite 单 db per root, indexed by (ticker, date, run, ts), WAL mode 支持并发
- 好处: count_chunks 走 index O(log N), stream_chunks 走 cursor, no fs churn
- 风险: migration script (从 jsonl 导入老数据)

#### R9 HistoryStore 迁移 (跟 R8 一起)

SQLite 替代 JSON file：
- table: history(id, ticker, trade_date, signal, status, elapsed, error, created_at, started_at, finished_at, results_path)
- table: stage_reports(history_id, stage_id, report_key, content)
- index: (ticker, created_at), (status, created_at), (signal, created_at)
- 好处: list_all filter 走 index (当前是全量扫描 + sort)

#### R10 实时 log streaming (WebSocket / SSE)

**目标**：替代当前的 "running 任务在内存 tracker，刷新后看 disk" 模式。

- 后端: `web/runner.py:_run` 用 `asyncio.Queue` 把每个 LogChunk 推到 WebSocket
- 前端: Streamlit + st.fragment / React WebSocket client
- 持久化: 仍然写 jsonl (H2 不变)，WebSocket 只是实时通知层

---

## 8. 总结 (TL;DR)

### 8.1 5 个文件位置 & 角色

| 文件 | 行数 | 角色 |
|---|---|---|
| `backend/core/log_store.py` | 458 | LogStore (read) + LogWriter (write) + TaskSummary + LogChunk + singleton |
| `backend/core/history_store.py` | 370 | HistoryEntry + HistoryStore (DCL singleton + P2.14/P2.21 zombie ops) |
| `backend/api/logs.py` | 196 | 5 read-only endpoints + `_safe_segment` |
| `backend/api/history.py` | 185 | 5 read/write/delete/rerun/report endpoints (无 path safety) |
| `web/components/logs_panel.py` | 178 | GitHub PR-style UI: ticker list (1) + task list (3) + running card |

### 8.2 3 个聚合根

| 根 | 持久化 | 主要字段 | 已知 anti-pattern |
|---|---|---|---|
| `TaskSummary` | `~/.tradingagents/logs/{ticker}/{date}_runNN/meta.json` | analysis_id, status, signal, elapsed_sec, chunk_counts | dataclass 当 DTO + Entity 双重角色，无 schema 版本 |
| `LogChunk` | `{llm_messages, tool_calls, agent_outputs}.jsonl` | ts, type, agent, role, tokens_in/out, content, tool, input/output, report_key | type 字符串散在 6+ 处 (R2) |
| `HistoryEntry` | `~/.tradingagents/logs/history/{analysis_id}.json` | analysis_id, ticker, status, signal, elapsed, stage_reports | stage_reports key 与 stage_id 不同步 (P2.25 修过，但仍是 schema drift 风险) |

### 8.3 10 API 端点速查

| Method | Path | 角色 |
|---|---|---|
| GET | `/api/logs/tickers` | list tickers + per-ticker summary |
| GET | `/api/logs/tasks` | list tasks per ticker |
| GET | `/api/logs/task` | single task meta + chunk counts |
| GET | `/api/logs/chunks` | stream chunks (filter by type) |
| GET | `/api/logs/counts` | chunk counts per task/ticker/all |
| GET | `/api/history` | list with filter + pagination |
| GET | `/api/history/{id}` | single entry detail |
| DELETE | `/api/history/{id}` | delete (not cascading) |
| POST | `/api/history/{id}/rerun` | delete + intent (not atomic) |
| GET | `/api/history/{id}/report` | read full_states_log JSON |

### 8.4 5 个运维特性

| 特性 | 阈值 | 触发 |
|---|---|---|
| zombie cleanup (P2.14) | 60s | startup lifespan hook (`backend/main.py:45`) |
| stuck cleanup (P2.21) | 600s | 同上 |
| path safety | reject `/`, `\`, `..`, NUL | `_safe_segment` in `api/logs.py:35` |
| 并发控制 | fcntl.flock (局部) | `LogWriter.append_chunk` only |
| legacy 兼容 | `TradingAgentsStrategy_logs/` read shim | `LogStore.list_tasks` / `get_meta` |

### 8.5 ⚠️ 12 个架构债务（3 个真 bug）

| # | 严重度 | 描述 |
|---|---|---|
| 1 | 🔴 bug | LogWriter._write_meta_field 无锁 (§6.1) |
| 2 | 🔴 bug | HistoryStore._write 无锁 + 静默 except (§6.2) |
| 3 | 🟡 risk | zombie cleanup 只 startup 跑 (§6.3) |
| 4 | 🟡 risk | meta.json chunk_counts 跟实际 jsonl 可能不一致 (§6.4) |
| 5 | 🟡 debt | log cleanup 缺 (§6.5) |
| 6 | 🟡 debt | history cleanup 缺 (§6.6) |
| 7 | 🟢 cleanup | chunk_type 字符串散在 6+ 处 (§6.7) |
| 8 | 🟢 cleanup | legacy shim 永久保留 (§6.8) |
| 9 | 🔴 bug | rerun endpoint 半成品，删了 entry 不启动新分析 (§6.9) |
| 10 | 🟡 risk | rerun race window 旧 thread 写老 analysis_id (§6.10) |
| 11 | 🔴 bug | delete 不级联，logs 残留 (§6.11) |
| 12 | 🟢 cleanup | report endpoint 不返 markdown (§6.12) |

### 8.6 10 个重构建议

| # | 周期 | 建议 |
|---|---|---|
| R1 | 短期 | 加 fcntl.flock 给 LogWriter._write_meta + HistoryStore._write |
| R2 | 短期 | 加 ChunkType Enum |
| R3 | 短期 | 验证 count_chunks 跟实际 jsonl 一致 |
| R4 | 中期 | log cleanup (LRU + TTL + size cap) |
| R5 | 中期 | history cleanup (LRU + TTL + size cap) |
| R6 | 中期 | 升级 rerun endpoint (返新 analysis_id + 自动启动) |
| R7 | 中期 | delete 级联 (history + logs/{date}_runNN + results_path) |
| R8 | 长期 | LogStore 迁移 JSONL → SQLite |
| R9 | 长期 | HistoryStore 迁移 SQLite |
| R10 | 长期 | 实时 log streaming (WebSocket / SSE) |

### 8.7 一句话

> **H1 (history) + H2 (logs) 是两条独立的运行时流水线，靠 web/runner.py 一个地方串联，schema 重叠但不同步。最大的运维风险不是 zombie（已自动清理），而是 §6.1, §6.2, §6.11 三个 race / 级联 bug——这些应该在 P2.x hotfix 之前先修。**

---

## 附录 A: 参考文献 & 交叉引用

### A.1 前 4 个 DDD 文档（互补，不重复）

| 文档 | 范围 | 跟本文的关系 |
|---|---|---|
| `DDD_EXPLORATION.md` (1311 行) | 13 后端聚合根 | 包含 `LogContext` / `AnalysisContext` 的高层战略；本文深入 log_store + history_store |
| `DDD_AGENTS_DEEP_DIVE.md` (1424 行) | 16 LangGraph Agent | 不涉及 ops，本文是 ops 唯一深入 |
| `DDD_DATAFLOWS_INFRA.md` (779 行) | 13 dataflows + 10+ 外部数据源 | 不涉及 log/history |
| `DDD_DATAFLOWS_DEEP.md` (1184 行) | 4 个 dataflows + 10 个工具集 | 不涉及 log/history |

### A.2 P2 Hotfix 索引

| 版本 | 主题 | 文件 |
|---|---|---|
| P2.14 | zombie cleanup (60s) | `backend/core/history_store.py:32` |
| P2.21 | stuck cleanup (600s) | `backend/core/history_store.py:40`, `backend/core/runner.py:104` |
| P2.25 | stage_reports key + ID 一致性 + 异常路径 | (git HEAD 33b3a42) |

### A.3 单元测试覆盖

| 测试 | 覆盖 |
|---|---|
| `tests/test_log_store.py` (205 行) | LogStore 16 tests |
| `tests/test_log_streaming.py` (149 行) | Runner 7 tests |
| `tests/test_logs_panel.py` (103 行) | UI 6 tests |
| `tests/test_cli_list_logs.py` (63 行) | CLI 3 tests |

(没有 `tests/test_history_store.py` 对 zombie / stuck / race 的覆盖 — **R1 实施时应加测试**)