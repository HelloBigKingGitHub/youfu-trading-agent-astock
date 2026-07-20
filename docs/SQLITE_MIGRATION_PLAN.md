# SQLite + WAL 日志模块迁移实施计划

> **文档类型**：DDD 探索 #7 — 实施级 plan。`MIGRATION_ROADMAP.md` 给战略（8 Phase），本文件给 Phase 3 的**具体怎么做**。
>
> **基线**：git HEAD `33b3a42`。
>
> **互补关系**：
> - `DDD_OPERATIONS.md` — 当前 log_store + history_store 痛点（1314 行）
> - `MIGRATION_ROADMAP.md §3.4` — Phase 3 骨架（35 行）
> - **本文件** — Schema DDL + 迁移脚本 + 双写期 + 兼容层 + 性能数据 + 风险（实施级）
>
> **硬约束**：本轮不修改代码、测试、`pyproject.toml` 或 spec；不 commit。

---

## 目录

1. [当前架构痛点（来自 DDD_OPERATIONS §2/§3）](#1-当前架构痛点来自-ddd_operations-2s3)
2. [SQLite 目标架构](#2-sqlite-目标架构)
3. [迁移策略](#3-迁移策略)
4. [性能预期](#4-性能预期)
5. [运维增强](#5-运维增强)
6. [Schema Migration 版本化](#6-schema-migration-版本化)
7. [替代方案对比](#7-替代方案对比)
8. [风险与回退](#8-风险与回退)
9. [Phase 3 实施步骤细化](#9-phase-3-实施步骤细化)
10. [不做清单（Out of Scope）](#10-不做清单out-of-scope)

---

## 1. 当前架构痛点（来自 DDD_OPERATIONS §2/§3）

### 1.1 两套独立日志系统

| 模块 | 物理形态 | 写入并发模型 | 读取模型 |
|---|---|---|---|
| `HistoryStore` (374 行) | `~/.tradingagents/logs/history/{analysis_id}.json` | RLock 单例 + `_write()` 写整个文件（**无 fcntl，跨进程 race**） | `glob('*.json')` + 全解析 + 内存过滤 |
| `LogStore` (458 行) | `~/.tradingagents/logs/{ticker}/{date}_runNN/{meta.json, llm_messages.jsonl, tool_calls.jsonl, agent_outputs.jsonl}` | `fcntl.flock` 在 append 上 ✓，`_write_meta` **无锁** ⚠ | `glob('*/meta.json')` + 逐 task 解析 |

**关键结构不变量**（来自代码实测，HEAD `33b3a42`）：

- `HistoryEntry`（`backend/core/history_store.py:47-64`）：11 字段，元数据 + `completed_stages: list[str]` + `stage_reports: dict[str, str]`
- `TaskSummary`（`backend/core/log_store.py:47-62`）：10 字段 + `chunk_counts: dict[str, int]` + `is_legacy: bool`
- `_CHUNK_TYPES = ("llm_messages", "tool_calls", "agent_outputs")` (`log_store.py:29`)

### 1.2 8 个已知 bug（Phase 1 热修已识别）

| # | Bug | 文件 / 行 | 影响 |
|---|---|---|---|
| 1 | `LogWriter._write_meta` (`log_store.py:434`) **无 fcntl lock** | race under concurrent finalize + append | meta 与 jsonl 错位 |
| 2 | `HistoryStore._write` (`history_store.py:362-371`) 静默 `except: pass` | 磁盘满 / EACCES 静默丢失 | 历史数据空洞无告警 |
| 3 | `LogStore.count_chunks` 不与实际 jsonl 行数对账 | meta 计数漂移 | UI 显示错误 chunk 数 |
| 4 | DELETE endpoint 不级联删 `logs/{ticker}/{date}_runNN/` | 孤儿目录堆积 | 磁盘泄漏 |
| 5 | Zombie cleanup 被动（只 startup） | 长跑任务不会重启 | UI 长时间卡 "running" |
| 6 | Log cleanup 缺（无 LRU/TTL） | 无边界 | OOM 风险 |
| 7 | History cleanup 缺（无 LRU/TTL） | 无边界 | OOM 风险 |
| 8 | rerun endpoint 半成品 | UI 入口有，后端空 | 用户阻塞 |

**Phase 1 会热修 1–4；5–8 是 Phase 3 落地自然解决。**

### 1.3 量化证据（HEAD `33b3a42` 实测）

- `~/.tradingagents/logs/history/`：**1 个 JSON 文件**（`33b3a42` P2.25 后的 smoke history）
- `~/.tradingagents/logs/600595/`：**0 个 `*_runNN` 目录**（清理后状态）
- pytest 基线：**779 passed, 2 skipped, 44 subtests** in 10.36s

痛点是**架构性**的，不是数据量大的问题。生产环境随着 ~200+ history 文件 + 50+ ticker 后开始显现。

---

## 2. SQLite 目标架构

### 2.1 单 SQLite 文件 + WAL 模式

**路径**：`~/.tradingagents/tradingagents.db`（含 WAL 时自动生成 `tradingagents.db-wal` / `tradingagents.db-shm`）

**连接初始化（每次 connect 后必跑）**：

```sql
PRAGMA journal_mode = WAL;          -- 并发读 + 单写
PRAGMA synchronous  = NORMAL;       -- 性能/可靠性折中（断电丢最后一两个 tx）
PRAGMA busy_timeout = 5000;         -- 5s 锁等待（避免 SQLITE_BUSY 立刻抛）
PRAGMA foreign_keys = ON;           -- 启用 FK（SQLite 默认 OFF）
PRAGMA cache_size    = -64000;      -- 64MB page cache（负数 = KiB）
PRAGMA temp_store    = MEMORY;      -- 临时表/B-tree 不落盘
```

**为什么 NORMAL 而不是 FULL**：`synchronous=NORMAL` + `journal_mode=WAL` 是 SQLite 官方推荐的"Rollback journal safe on power loss, but not crash"档位。我们做的是单进程 uvicorn + 异步分析任务，写并发低（写入均发生在后台 scheduler 线程），丢最后一两个 tx 风险可接受；FULL 会让 WAL commit 慢 5–10×。

### 2.2 Schema 设计 — 4 张核心表

#### 2.2.1 `history` — 历史分析元数据（聚合根）

替代 `~/.tradingagents/logs/history/{id}.json` per-entry JSON。

```sql
CREATE TABLE history (
    analysis_id   TEXT PRIMARY KEY,             -- 16-char ulid（既有约定）
    ticker        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,                -- "YYYY-MM-DD"
    signal        TEXT,                         -- "Buy"/"Sell"/"Hold"/NULL
    elapsed       REAL NOT NULL DEFAULT 0,      -- 秒
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','completed','error')),
    error         TEXT,                         -- error 信息 or NULL
    results_path  TEXT NOT NULL DEFAULT '',     -- 指向 full_states_log_*.json（legacy shim）
    started_at    REAL,
    finished_at   REAL,
    created_at    REAL NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1   -- row-level schema version（见 §6）
);

CREATE INDEX idx_history_ticker_created
    ON history (ticker, created_at DESC);

CREATE INDEX idx_history_status_running
    ON history (status) WHERE status IN ('running', 'pending');  -- partial index

CREATE INDEX idx_history_created
    ON history (created_at DESC);
```

**索引策略理由**：
- `idx_history_ticker_created`：单 ticker 历史分页（`list_tasks(ticker)` 走这条）
- `idx_history_status_running`：partial index，zombie cleanup 扫描只索引 running/pending 子集，**体积小几个数量级**
- `idx_history_created`：跨 ticker "最新 N 条" 用
- **不建 FULLTEXT**：`stage_reports.content` 在 `stage_reports` 表里，text search 用 `LIKE %x%` 或后续 Phase 8 单独建 FTS5 表

#### 2.2.2 `stage_reports` — stage 输出（替代 `stage_reports: dict` JSON 字段）

替代 `HistoryEntry.stage_reports: dict[str, str]` 嵌套字段。

```sql
CREATE TABLE stage_reports (
    analysis_id TEXT NOT NULL,
    report_key  TEXT NOT NULL,                   -- LangGraph chunk field 的 canonical key
    stage_id    TEXT NOT NULL,                   -- pipeline stage label ("market_analyst" etc.)
    content     TEXT NOT NULL,                   -- 实际 markdown 报告
    created_at  REAL NOT NULL,
    PRIMARY KEY (analysis_id, report_key),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_stage_reports_stage
    ON stage_reports (stage_id);
```

**为什么拆出**：
- 一对多天然关系（一次分析有 9 个 stage × 多个 report_key）
- `report_key` 主键保证幂等 insert（`INSERT OR IGNORE`）
- FK ON DELETE CASCADE 自动清理 orphan

#### 2.2.3 `completed_stages` — stage 完成顺序（替代 `completed_stages: list` JSON 字段）

替代 `HistoryEntry.completed_stages: list[str]`。

```sql
CREATE TABLE completed_stages (
    analysis_id  TEXT NOT NULL,
    stage_id     TEXT NOT NULL,
    completed_at REAL NOT NULL,
    sequence     INTEGER NOT NULL,              -- 完成顺序（1, 2, 3, ...）
    PRIMARY KEY (analysis_id, stage_id),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_completed_stages_analysis_seq
    ON completed_stages (analysis_id, sequence);
```

#### 2.2.4 `log_chunks` — stream event（替代 3 个 JSONL 文件）

替代 `llm_messages.jsonl` + `tool_calls.jsonl` + `agent_outputs.jsonl` 三件套。

```sql
CREATE TABLE log_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id   TEXT    NOT NULL,
    task_dir_name TEXT    NOT NULL,              -- "{date}_runNN}"（保留以便旧 API 兼容）
    ts            REAL    NOT NULL,
    type          TEXT    NOT NULL
                  CHECK (type IN ('llm','tool','agent_output')),
    agent         TEXT    NOT NULL DEFAULT '',
    role          TEXT,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    content       TEXT,
    tool          TEXT,
    input_json    TEXT,                          -- JSON string of input dict
    output        TEXT,
    report_key    TEXT,
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_chunks_analysis_ts
    ON log_chunks (analysis_id, ts);

CREATE INDEX idx_chunks_analysis_type
    ON log_chunks (analysis_id, type);

CREATE INDEX idx_chunks_task_dir
    ON log_chunks (task_dir_name);
```

**`type` 校验**：直接对应 `_CHUNK_TYPES = ("llm_messages","tool_calls","agent_outputs")`，**DB 层硬约束**——比 Python dataclass 注释可靠。

### 2.3 历史 + 日志：合并 vs 分离（决策）

| 方案 | 形态 | 优 | 劣 |
|---|---|---|---|
| A. 合并（1 history 表 + 1 chunks 表） | metadata + events 在同一物理存储 | 少一张表；join 简单 | metadata 跟 streaming events 体积差异大（hot row vs cold archive），vacuum/重写策略冲突 |
| **B. 分离（4 张表）** — 推荐 | `history`/`stage_reports`/`completed_stages`/`log_chunks` | 跟 DDD 聚合根对齐（`HistoryEntry` aggregate 持有 `LogChunk` 集合）；FK 约束清晰；可独立 TTL 策略 | 多 3 张表，迁移脚本略长 |

**选 B**：与 DDD 聚合根边界一致（`HistoryEntry` 持有 completed_stages + stage_reports 两个 child collection，logs 是独立 event stream）；FK CASCADE 把孤儿清理自动化。

### 2.4 目录结构改造

**Phase 3c 后废弃**：`~/.tradingagents/logs/{ticker}/{date}_runNN/`

| 旧文件 | 新归宿 |
|---|---|
| `meta.json` | `history` + `stage_reports` + `completed_stages` |
| `llm_messages.jsonl` | `log_chunks WHERE type='llm'` |
| `tool_calls.jsonl` | `log_chunks WHERE type='tool'` |
| `agent_outputs.jsonl` | `log_chunks WHERE type='agent_output'` |

**保留**（不受 Phase 3 影响）：

- `~/.tradingagents/logs/history/{id}.json` — Phase 3b 切换后变为只读 rollback backup，7 天后归档删
- `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json` — legacy results（保留读路径）
- `~/.tradingagents/cache/` — 跟 SQLite 无关，保留

---

## 3. 迁移策略

### 3.1 数据迁移脚本（Phase 3a）

**一次性脚本**：`scripts/migrate_logs_to_sqlite.py`

**输入**：
- `~/.tradingagents/logs/history/*.json` → `history` 表
- `~/.tradingagents/logs/{ticker}/{date}_runNN/meta.json` → `history` 表（注意：可能与 history/*.json 重复，用 `INSERT OR IGNORE`）
- `~/.tradingagents/logs/{ticker}/{date}_runNN/*.jsonl` → `log_chunks` 表

**幂等机制**：
- `history.analysis_id PRIMARY KEY` → `INSERT OR IGNORE`
- `log_chunks.id AUTOINCREMENT` + 唯一 `(analysis_id, ts, type, content)` 元组 → import 前 `SELECT` 比对，重复跳过
- 重复跑同一脚本 N 次结果一致

**对账（reconciliation）**：`scripts/verify_migration.py` 必须独立运行：

| 指标 | 期望 |
|---|---|
| `count(history) == count(history.json files) - dedup` | 相等 |
| `count(log_chunks WHERE type='llm') == sum(llm_messages.jsonl 行数)` | 相等 |
| `count(log_chunks WHERE type='tool') == sum(tool_calls.jsonl 行数)` | 相等 |
| `count(log_chunks WHERE type='agent_output') == sum(agent_outputs.jsonl 行数)` | 相等 |
| 所有 stage_reports 条目 count == sum(history.stage_reports 长度) | 相等 |

**0 数据丢失 = 对账通过**。脚本最后一行写 `tradingagents.db_migration_complete` 标记文件（防止半完成状态进 dual-write）。

### 3.2 双写期（Dual-write Period，Phase 3b–3c）

**核心原则：先读后写，先切读再切写，最后清。**

时间线（4 周窗口）：

```
W1 (3a):   仅跑导入脚本 + verify_migration。读写路径仍全部走 JSON。✅ 0 行为变化
W2 (3b):   HistoryStore 改造：写双路 (JSON + SQLite)；读仍走 JSON（向后兼容）
            → 验证：JSON 跟 SQLite 一致（用 diff 脚本）
W3 (3c):   LogStore 改造：写双路；读仍走 JSON
            → 验证同上
            → 切读路径到 SQLite（保留 JSON 兼容降级）
W4 (3d):   切写路径到 SQLite-only（JSON 只读 fallback）
            → 7 天观察期
            → 删 `~/.tradingagents/logs/{ticker}/{date}_runNN/`
            → 删 history/*.json
```

**W2/W3 中间的"读路径不切"是关键**——SQLite 写入 bug 不会立刻被 UI 发现，因为 UI 还在读 JSON。**W3 末切读路径是信任切换点**。

**双写期实现细节**：

```python
# 伪代码 — HistoryStore 改造后
class HistoryStore:
    def mark_running(self, analysis_id):
        entry = self._read(analysis_id)
        entry.status = "running"
        # 写双路
        self._write_json(entry)               # 原路径，保证兼容
        self._write_sqlite(entry)             # 新路径，try/except 记日志
```

**SQLite 写失败怎么办**：必须 swallow + 记 log + 告警。**绝不让 SQLite 故障拖死整个分析**。这是双写期的核心安全属性。

**W3 末的对比验证**：每 100 次写跑一次随机抽检 `SELECT * FROM history WHERE analysis_id=?` 跟内存对象 diff；不一致立即告警 + 自动切回 JSON-only。

### 3.3 兼容层（Compatibility Layer）

**原则**：**API 不动，实现换**。

#### 3.3.1 LogStore 公共 API（不变）

```python
# 既有签名（backend/core/log_store.py）
class LogStore:
    def list_tickers(self) -> list[str]: ...
    def list_tasks(self, ticker: str, ...) -> list[TaskSummary]: ...
    def get_meta(self, ticker: str, task_dir_name: str) -> TaskSummary | None: ...
    def iter_chunks(self, ticker, task_dir_name, type_filter=None) -> Iterator[LogChunk]: ...
```

#### 3.3.2 SQLite 实现映射

| API | SQLite 查询 |
|---|---|
| `list_tickers()` | `SELECT DISTINCT ticker FROM history` + 去 active legacy 合并 |
| `list_tasks(ticker)` | `SELECT DISTINCT h.task_dir_name, h.* FROM log_chunks JOIN history h USING(analysis_id) WHERE h.ticker=? ORDER BY h.created_at DESC` |
| `get_meta(ticker, task_dir_name)` | `SELECT h.* FROM history h WHERE h.analysis_id IN (SELECT DISTINCT analysis_id FROM log_chunks WHERE task_dir_name=?) AND ticker=?` |
| `iter_chunks(ticker, task_dir_name, type_filter)` | `SELECT * FROM log_chunks WHERE analysis_id IN (...) AND type=? ORDER BY ts ASC` |

**Legacy 兼容降级**（`full_states_log_*.json`）：
- 切读路径后，扫描 SQLite 找不到时仍然 fallback 到 legacy 目录
- 跟现在一样，但标记 `is_legacy=True`

#### 3.3.3 HistoryStore 公共 API（不变）

```python
class HistoryStore:
    def create(self, ticker, trade_date, ...) -> HistoryEntry: ...
    def mark_running(self, analysis_id): ...
    def mark_completed(self, ...): ...
    def mark_error(self, ...): ...
    def set_stage_report(self, analysis_id, stage_id, report, report_key): ...
    def list_recent(self, ticker=None, signal=None, status=None, limit=50): ...
    def cleanup_zombies(self) -> list[str]: ...
```

所有签名一字不动。`cleanup_zombies` 实现从 `glob status==running` 改为 `SELECT WHERE status IN ('running','pending')`。

### 3.4 公共契约测试（Phase 2 准备）

Phase 2 已识别 HistoryStore / LogStore 0 unit test 覆盖。**Phase 3 之前**必须补：
- `tests/test_history_store_contract.py`：每 API 一个最小用例
- `tests/test_log_store_contract.py`：同上
- 12+ 集合，让 SQLite 重构不破坏 API

**Phase 3a 后这些测试套不变**——SQLite 实现必须满足同一组 test（双跑 JSON + SQLite）。

---

## 4. 性能预期

### 4.1 历史查询（单 analysis_id）

| 阶段 | 路径 | 实测 |
|---|---|---|
| 现状（JSON） | `json.loads(path.read_text())` + `HistoryEntry.from_dict` | ~1–5ms（filesystem cache hit，无 RLock 等待） |
| SQLite 后 | `SELECT * FROM history WHERE analysis_id = ?`（PK 查找） | ~0.05–0.1ms |

**收益**：5–50×。N/A 因为是低频操作（用户点击 detail 才查询）。

### 4.2 列表查询（recent 20 条）

| 阶段 | 路径 | 实测 |
|---|---|---|
| 现状（JSON） | `glob('*.json')` + 解析每个 + 内存 sort | ~50–100ms（200 文件起步；线性增长） |
| SQLite 后 | `SELECT * FROM history ORDER BY created_at DESC LIMIT 20`（idx_history_created 命中） | ~0.5–2ms |

**收益**：25–200×。**该指标是核心 UX 改进**——sidebar 切到 "📋 日志" tab 当前 50–100ms 等待；SQLite 后 < 5ms 不可感知。

### 4.3 增量写入（LogChunk append）

| 阶段 | 路径 | 实测 |
|---|---|---|
| 现状（JSONL） | `open(O_APPEND)` + `fcntl.LOCK_EX` + 写 + `LOCK_UN` + 后续 `_write_meta`（**无锁** ⚠） | ~0.3–0.5ms per chunk（一次 LLM 调用 30+ chunks） |
| SQLite 后 | 批量 `INSERT INTO log_chunks` 在一个 tx 里（prepared statement + `executemany`） | ~0.05ms per chunk（30 chunk 一个 tx ≈ 1.5ms） |

**收益**：~10×。**尤其关键**：避免 meta ↔ jsonl 漂移（Bug #3）。`chunk_counts` 由 `SELECT COUNT(*) GROUP BY type WHERE analysis_id=?` 实时算，永远不会漂。

### 4.4 并发模型

| 阶段 | 行为 |
|---|---|
| 现状（JSON + fcntl） | 单 writer per task（不同 task 不同文件），跨 task 元数据查询是 sequential `glob` |
| SQLite 后 | WAL：1 写 + N 读 并发；不同分析任务写不同 `analysis_id` 互不阻塞（写 B-tree page 级锁） |

**额外收益**：未来 scheduler 多 ticker 并行触发分析（Phase 8 候选），SQLite 不再是瓶颈。

### 4.5 文件 I/O 减少

| 阶段 | 单次分析任务写盘量 |
|---|---|
| 现状 | meta.json (1) + llm_messages.jsonl (1) + tool_calls.jsonl (1) + agent_outputs.jsonl (1) = 4 个文件 open/close 周期每 chunk |
| SQLite 后 | 1 个 db 文件 + WAL 增量；每 commit 一次 fsync |

**收益**：fs 调用次数下降 ~30×（每 chunk 由 4 fs → 1 commit batch 内合）。

---

## 5. 运维增强

### 5.1 自动 cleanup（Phase 3d）

**TTL 策略**：

| 表 | 策略 | SQL |
|---|---|---|
| `history` | 30 天前的 completed/error | `DELETE FROM history WHERE status IN ('completed','error') AND finished_at < strftime('%s','now','-30 days')` |
| `log_chunks` | 7 天前的 events | `DELETE FROM log_chunks WHERE ts < strftime('%s','now','-7 days')` |
| `history` | zombie (running/pending > 2h 且无 progress) | `UPDATE history SET status='error', error='zombie cleanup' WHERE status='running' AND started_at < strftime('%s','now','-2 hours')` |

**zombie 阈值改**：从"30 分钟" → "2 小时"。理由：完整分析 5–15 分钟是常态，2 小时确实是 zombie。

**触发位置**：
- `backend/main.py` lifespan startup（冷启动）
- FastAPI `BackgroundTasks` 每日 03:00（cron-like）

### 5.2 备份策略

```bash
# SQLite hot backup（WAL 模式下事务一致）
sqlite3 ~/.tradingagents/tradingagents.db ".backup /backup/db-$(date +%Y%m%d).db"

# 验证
sqlite3 /backup/db-$(date +%Y%m%d).db "PRAGMA integrity_check;"
```

**机制**：`sqlite3 .backup` 比 `cp` 安全——它会 checkpoint WAL 并保证 backup 是一个一致快照。

**频率**：每周一次自动（cron）；保留 4 个 backup 后轮转。

### 5.3 完整性验证

```bash
# 启动时跑
sqlite3 ~/.tradingagents/tradingagents.db "PRAGMA integrity_check;"
# 期望输出: ok

# 周期性跑（每日）
sqlite3 ~/.tradingagents/tradingagents.db "PRAGMA foreign_key_check;"
# 期望输出: 空
```

### 5.4 监控指标

未来 Phase 7+ 可加：
- `sqlite3.db_size_bytes`（gauge）
- `sqlite3.wal_size_bytes`（gauge；> 50MB 需 checkpoint）
- `migrate.dual_write_diff_count`（counter；周同比 0）
- `migrate.zombie_cleanup_count`（counter）

---

## 6. Schema Migration 版本化

### 6.1 Django-style migration journal

```
backend/storage/migrations/
├── 001_initial.sql                # 4 张表 + 索引
├── 002_add_schema_version_field.sql   # history 加 schema_version
├── 003_add_completed_stages_seq.sql   # completed_stages 加 sequence
└── ...
```

**migration journal 表**（自动维护）：

```sql
CREATE TABLE schema_migrations (
    version  INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    description TEXT NOT NULL,
    checksum TEXT NOT NULL          -- 文件 SHA256 防篡改
);
```

**migrate 脚本**：`scripts/sqlite_migrate.py`

行为：
1. 读 `_MIGRATIONS_DIR = backend/storage/migrations/*.sql`（按文件名前缀排序）
2. 当前 `MAX(version) FROM schema_migrations` 之前的全部应用
3. 每个 .sql 包在 `BEGIN ... COMMIT` 事务里
4. 失败 → `ROLLBACK` + 抛出，schema_migrations 不更新

### 6.2 row-level schema_version

`history.schema_version INTEGER DEFAULT 1` —— **row-level** 用来追踪 row 是哪个版本 migrate 进来的。读路径（如有字段差异）根据 version 走向后兼容。

未来 v2 schema 字段加：

```sql
-- 002_add_schema_version_field.sql
ALTER TABLE history ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1;
UPDATE history SET schema_version = 1;  -- 全部标 v1
```

### 6.3 迁移脚本幂等性

所有 migration 用 `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`，重复跑安全。

`ALTER TABLE` 用 SQLite 的 `ALTER TABLE ADD COLUMN`（无 `IF NOT EXISTS` 支持）→ 用 `PRAGMA table_info(history)` 检查列是否存在决定是否执行。

---

## 7. 替代方案对比

| 方案 | 优 | 劣 | 推荐 |
|---|---|---|---|
| **A. SQLite + WAL** | 单文件、备份简单、SQL 查询、生态成熟（sqlite3 CLI + Python stdlib） | 单写并发（够用）、跨进程复杂 | ✅ |
| B. DuckDB | OLAP 友好（分析 query 快）、单文件 | 写不友好（OLAP-oriented）；跟 async 不兼容 | ❌ 写不够 |
| C. TinyDB | 纯 Python、JSON 风格 | 性能差、不支持 SQL query | ❌ 治标 |
| D. 保留 JSON + 加索引文件 | 改动最小 | 治标不治本；schema 演进仍然手动 | ❌ |
| E. PostgreSQL | 真并发、生产级 | 单进程 overkill；运维（postgres 服务）沉；迁移路径破坏现有部署 | ❌ 杀鸡用牛刀 |

**选 A**：单写并发足够（analyses 本来就低频，单 uvicorn 进程；WAL 也允许多 reader），SQL 查询 + 备份生态 + stdlib = 几乎没有引入风险。

---

## 8. 风险与回退

### 8.1 风险矩阵

| 风险 | 概率 | 影响 | Phase 时点 |
|---|---|---|---|
| 数据迁移字段映射错 | 中 | 高（数据丢失） | 3a |
| 双写期不一致（JSON 跟 SQLite diff） | 中 | 中 | 3b–3c |
| WAL 锁 — 长 tx 阻塞其他 reader | 低 | 中 | 3d 之后 |
| 索引建错（查询比 JSON 还慢） | 低 | 中 | 3d |
| DROP JSON 文件后回退发现需要 | 中 | 高（数据不在结构化存储） | 3d 之后 |
| WAL 文件未 checkpoint 撑爆磁盘 | 低 | 中 | 长期 |
| FK CASCADE 把 meta 误删 | 极低 | 高 | 3b 之后 |

### 8.2 回退策略

#### 8.2.1 Phase 3a 失败（导入错）→ 立即回退
- SQLite 没切换读路径 → 0 用户感知
- 删 `tradingagents.db` 即可
- 30 分钟回退成本

#### 8.2.2 Phase 3b/3c 失败（双写期 diff 报警）→ 单写回退
- 关闭 dual-write 开关（`DUAL_WRITE_ENABLED=false`）
- 1 天回退成本
- JSON 文件完整（双写期一直在写），0 数据丢失

#### 8.2.3 Phase 3d 后（已切 SQLite-only）回退
- **必须先 dump**：`sqlite3 .dump > backup.sql`
- 然后 `git revert HEAD~N` 回到 JSON-only
- 跑 `restore_from_backup.py`（回填 JSON 从 dump）
- 1 周回退成本
- 数据完整性依赖 dump 有效性

**结论**：**Phase 3 内任何时点都能 < 1 天回退**。这是双写期最大的安全网。

### 8.3 验证门槛（go/no-go）

进入 Phase 3b 之前必须 ✅：
- [ ] `tests/test_history_store_contract.py` 通过
- [ ] `tests/test_log_store_contract.py` 通过
- [ ] `scripts/migrate_logs_to_sqlite.py` + `verify_migration.py` 在 dev env 0 数据丢失

进入 Phase 3d 之前必须 ✅：
- [ ] 双写期 ≥ 1 周 diff 为 0
- [ ] 1 个真实 production-size history（>200 entries）双路写后对账通过
- [ ] backup → restore 演练成功（一次）

---

## 9. Phase 3 实施步骤细化

按 `MIGRATION_ROADMAP.md §3.4` 的 3a/3b/3c/3d 拆。**总计 3–4 周**，单人可执行。

### Phase 3a — schema migration script + verification（1 周）

**目标**：建立 SQLite schema + 导入 + 对账。**不动运行时代码**。

| Day | Task | 交付物 | 验收 |
|---|---|---|---|
| 1–2 | 设计并审查 schema（4 表 + 索引） | `docs/SQLITE_MIGRATION_PLAN.md` §2（本文件已交付） | PR review |
| 3 | 写 `backend/storage/schema.sql` + `schema_migrations` journal | schema file | dry-run 应用无错 |
| 4 | 写 `scripts/migrate_logs_to_sqlite.py` | 导入脚本 | 幂等测试通过 |
| 5 | 写 `scripts/verify_migration.py` | 对账脚本 | 0 数据丢失 |

**关键代码骨架**（非强制，仅示意）：

```python
# scripts/migrate_logs_to_sqlite.py 骨架
import sqlite3, json, glob, os
from pathlib import Path

DB = Path.home() / ".tradingagents" / "tradingagents.db"
SCHEMA = Path(__file__).parent.parent / "backend" / "storage" / "schema.sql"
LOGS_ROOT = Path.home() / ".tradingagents" / "logs"

def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    for pragma in [
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA busy_timeout=5000",
        "PRAGMA foreign_keys=ON",
    ]:
        conn.execute(pragma)
    conn.executescript(SCHEMA.read_text())
    return conn

def migrate_history_json(conn):
    history_dir = LOGS_ROOT / "history"
    for path in history_dir.glob("*.json"):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO history (analysis_id, ticker, trade_date, "
                "signal, elapsed, status, error, results_path, started_at, "
                "finished_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (d["analysis_id"], d["ticker"], d["trade_date"], d.get("signal"),
                 d.get("elapsed", 0.0), d.get("status", "completed"),
                 d.get("error"), d.get("results_path", ""),
                 d.get("started_at"), d.get("finished_at"),
                 d.get("created_at", path.stat().st_mtime))
            )
            # stage_reports：dict → 多行
            for k, v in (d.get("stage_reports") or {}).items():
                conn.execute(
                    "INSERT OR IGNORE INTO stage_reports "
                    "(analysis_id, report_key, stage_id, content, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (d["analysis_id"], k, d.get("stage_id", ""), v,
                     d.get("created_at", path.stat().st_mtime))
                )
        except Exception as e:
            print(f"[skip] {path.name}: {e}")

def migrate_log_jsons(conn):
    for ticker_dir in LOGS_ROOT.glob("*/"):
        if ticker_dir.name in ("history", "cache"):
            continue
        for task_dir in ticker_dir.glob("*_run*"):
            meta_path = task_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                analysis_id = meta["analysis_id"]
                ticker = meta["ticker"]
                trade_date = meta["trade_date"]
                task_dir_name = task_dir.name
                # INSERT OR IGNORE history
                conn.execute(
                    "INSERT OR IGNORE INTO history (analysis_id, ticker, trade_date, "
                    "signal, elapsed, status, started_at, finished_at, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (analysis_id, ticker, trade_date, meta.get("signal", ""),
                     meta.get("elapsed_sec", 0.0), meta.get("status", "completed"),
                     meta.get("started_at"), meta.get("finished_at"),
                     meta.get("started_at"))
                )
                # 三 JSONL → log_chunks
                for jsonl_name, chunk_type in [
                    ("llm_messages.jsonl", "llm"),
                    ("tool_calls.jsonl", "tool"),
                    ("agent_outputs.jsonl", "agent_output"),
                ]:
                    jsonl_path = task_dir / jsonl_name
                    if not jsonl_path.exists():
                        continue
                    with jsonl_path.open() as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                c = json.loads(line)
                                conn.execute(
                                    "INSERT INTO log_chunks (analysis_id, "
                                    "task_dir_name, ts, type, agent, role, "
                                    "tokens_in, tokens_out, content, tool, "
                                    "input_json, output, report_key) "
                                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (analysis_id, task_dir_name,
                                     c.get("ts", 0.0), chunk_type,
                                     c.get("agent", ""), c.get("role"),
                                     c.get("tokens_in"), c.get("tokens_out"),
                                     c.get("content"), c.get("tool"),
                                     json.dumps(c.get("input")) if c.get("input") else None,
                                     c.get("output"), c.get("report_key"))
                                )
                            except Exception:
                                continue
            except Exception as e:
                print(f"[skip] {task_dir}: {e}")

if __name__ == "__main__":
    conn = init_db()
    migrate_history_json(conn)
    migrate_log_jsons(conn)
    conn.commit()
    print("✅ migration complete")
```

### Phase 3b — HistoryStore SQLite 实现 + 双写（1 周）

| Day | Task | 验收 |
|---|---|---|
| 1 | 新增 `backend/core/sqlite_history_repo.py`（实现 HistoryStore 公开 API 同样的 method，底层 SQLite） | 编译 + 12+ 契约测试过 |
| 2 | `HistoryStore` 改造：每个写 method 加 dual-write | JSON-only 跟 SQLite-only 各跑一遍 0 差异 |
| 3 | 加 diff 守护（每 100 次写抽检一次） | 1k 次双写后 0 diff |
| 4 | 文档 + 测试：`tests/test_dual_write_history.py` | 全绿 |
| 5 | dev env soak test（真实 history 跑分析，SQLite 跟 JSON diff） | 1 个 production-size history 0 diff |

### Phase 3c — LogStore + LogWriter SQLite 实现 + 双写（1 周）

| Day | Task | 验收 |
|---|---|---|
| 1 | 新增 `backend/core/sqlite_log_repo.py` | 12+ 契约测试过 |
| 2 | `LogWriter` 改造：append + finalize 走双路 | 同上 |
| 3 | `LogStore` 改造：list/iter 优先 SQLite + legacy fallback | 读路径切换前 0 行为变化 |
| 4 | 切读路径（flag 控制）：默认仍走 JSON，feature flag 切 SQLite | flag toggle 验证一致 |
| 5 | soak test + diff 守护 1 周累计 0 差异 | 周结 0 diff |

### Phase 3d — cleanup + 索引优化 + 备份脚本（1 周）

| Day | Task | 验收 |
|---|---|---|
| 1 | 切写路径到 SQLite-only（JSON 仍写，标识 `_readonly_legacy_backup`） | 1 天跑真实分析 0 错误 |
| 2 | TTL auto-cleanup：在 `backend/main.py` lifespan 加 + 加 cron 任务 | 7 天后 history 跟 log_chunks 自然 shrink |
| 3 | 备份脚本 + 演练（dump + restore） | `scripts/backup_db.sh` 5 分钟内完成 |
| 4 | 跑 `PRAGMA integrity_check` + `PRAGMA foreign_key_check` baseline | 0 错误 |
| 5 | 删 `~/.tradingagents/logs/{ticker}/{date}_runNN/`（先 dry-run 列名单，再删） | 删前 grep + diff 0 差异 |

### 总验收门槛（Phase 3 收口）

- [ ] 0 数据丢失（migration diff 为 0）
- [ ] 7 天双读无差异
- [ ] `tests/test_history_store_contract.py` + `tests/test_log_store_contract.py` 全过
- [ ] `pytest tests/ --ignore=tests/test_google_api_key.py` 仍有 baseline 779 passed + 新增 24+
- [ ] `~/.tradingagents/logs/{ticker}/{date}_runNN/` 已删
- [ ] backup → restore 演练成功
- [ ] UI（`web/components/logs_panel.py`）0 改动，行为不变

---

## 10. 不做清单（Out of Scope）

| 不做项 | 原因 | 何时重提 |
|---|---|---|
| **跨进程多 writer** | uvicorn 单进程足够；WAL 单写并发支持未来扩展 | Phase 8+ 如果引入多 worker |
| **实时 log streaming**（WebSocket/SSE） | 跟 Phase 3 关注点不同；UI polling 够用 | Phase 7（Roadmap §3.8） |
| **SQLite replication / HA** | 单文件 + 备份足够；项目体量用不到 | 永远（除非上云） |
| **复杂 query 优化**（例如 JOIN 4 表） | 小数据集；索引足够 | Phase 8+ 如果数据 >10k |
| **替换 UI 层**（`web/components/logs_panel.py`） | UI 不变，只换 storage；API 兼容层保证 | 永远（本 Phase 边界） |
| **替换 portfolio_store / scheduler / watchlist_store** | 它们也有 JSON 痛点，但属于 Theme A 不同子集 | Phase 3 后续滚动实施（MIGRATION_ROADMAP §2.1 Theme A 子项） |
| **FTS5 全文索引** | `content` 太大，LIKE 够用；引入虚拟表增加 schema 复杂度 | Phase 8 搜索功能重提 |
| **加密 SQLite**（SQLCipher） | 用户数据是本地 + 自有；不引入额外依赖 | 永远（如要分发到第三方再考虑） |
| **改 dataclass → SQLAlchemy ORM** | dataclass + sqlite3 stdlib 已经够；ORM 引入 Schema/relationship 抽象过度 | 永远（除非引入 4+ 模块） |
| **PRAGMA mmap_size** | 取决于 fs；NORMAL 性能足够 | 性能不足时再调 |

---

## 附录 A：与 6 个 DDD 文档 / MIGRATION_ROADMAP 互补性

| 文档 | 关注点 | 本文件互补 |
|---|---|---|
| `DDD_OPERATIONS.md §2/§3` | 当前 log_store + history_store 8 bug 列举 | §1 引用并量化 |
| `DDD_EXPLORATION.md §4` | backend/core 13 聚合根 | §2.3 映射 HistoryEntry aggregate |
| `MIGRATION_ROADMAP.md §3.4` | Phase 3a/b/c/d 骨架 | §9 拆到 Day 粒度 |
| `MIGRATION_ROADMAP.md §4` | Phase 3 风险 | §8 风险矩阵 + 回退策略 |
| `MIGRATION_ROADMAP.md §7` | Out of Scope 战略级 | §10 实施级 |
| `DDD_DATAFLOWS_INFRA.md / DEEP.md` | 数据源 / 缓存 / circuit breaker | 不涉及（不在 Phase 3 边界） |
| `DDD_AGENTS_DEEP_DIVE.md` | Agent 工作流 | 不涉及（Phase 6 范围） |
| `DDD_ANALYSIS.md` | 跨切面 | 不涉及 |

## 附录 B：实施前复核清单（Phase 3 go/no-go）

- [ ] Phase 1 8 bug 全部 hotfix 完成 + 测试覆盖
- [ ] Phase 2 `tests/test_history_store_contract.py` + `tests/test_log_store_contract.py` 12+ 用例全绿
- [ ] `scripts/verify_migration.py` 在 dev env 0 数据丢失
- [ ] backup → restore 演练 ≥ 1 次成功
- [ ] 业务方已知 4 周窗口 + 周内不动生产数据写路径
- [ ] DB 文件位置 + 备份路径 + TTL 策略写入 ops 文档

---

**完成 Phase 3 后，Theme A 第一步完成。下一阶段候选（任选）**：

- Phase 3'：把 portfolio_store + scheduler 同模式迁移进 `tradingagents.db`
- Phase 7 起点：实时 log streaming（SSE）+ 复用 SQLite query
- Phase 4：ACL 扩展（DDD_DATAFLOWS_INFRA 范围）

