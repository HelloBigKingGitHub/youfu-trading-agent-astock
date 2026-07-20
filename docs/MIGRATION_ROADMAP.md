# Youfu-Trading-Agent-Astock 长期迁移 Roadmap

> **文档类型**：DDD 探索 #6，既有建议的整合规划；不是第六次架构债务发现。
>
> **基线**：git HEAD `33b3a42`（完整值 `33b3a428a14b52b73d14b6393a370326f39c5928`）。
>
> **输入**：`DDD_EXPLORATION.md`、`DDD_AGENTS_DEEP_DIVE.md`、`DDD_DATAFLOWS_INFRA.md`、`DDD_DATAFLOWS_DEEP.md`、`DDD_OPERATIONS.md`，共 6,012 行。
>
> **硬约束**：本轮只新增本文件；不修改代码、测试、`pyproject.toml` 或 spec，不执行 commit。
>
> **时间范围**：8 个阶段，顺序实施总计 **25–39 周（约 6–10 个月）**。

---

## 1. 战略愿景（Strategic Vision）

### 1.1 为什么现在需要迁移

前五轮探索已经给出 50+ 条架构债务和 50 条编号重构建议，但建议分散在后端聚合、Agent 工作流、数据基础设施、ACL 和运维五个视角。逐条实施会产生三个问题：

1. **同一问题被不同文档用不同语言描述**：例如 JSON/JSONL 并发写、History/Log 双写、缺少 Repository Protocol，本质上都指向持久化边界不稳定。
2. **局部优化可能锁死下一阶段**：如果先把 11 个 vendor 全部改成 async，却没有稳定 Protocol、value object 和 fallback contract，会把同步耦合原样复制到 async 实现。
3. **缺少可回退的交付顺序**：typed aggregate、SQLite、async、ACL 都是跨模块变化，必须以兼容适配层、双读/双写、feature flag 和可度量验收门槛逐步迁移，而不是一次性切换。

本 Roadmap 不再扩充债务清单，而是把已有结论归并为可排序、可验收、可回滚的迁移组合。

### 1.2 当前痛点归并

| 痛点簇 | 五份文档中的代码现状 | 长期后果 | 本 Roadmap 收口点 |
|---|---|---|---|
| 文件持久化碎片化 | history per-entry JSON、log meta + 3 个 JSONL、portfolio 多 JSON、scheduler JSON/JSONL；部分写无完整跨进程锁 | race、部分写、全盘扫描、schema 演进困难 | Theme A / Phase 3 |
| 同步数据访问 | `a_stock.py` 同步 HTTP/TCP；11 个数据源 timeout、限流、retry 不一致 | 阻塞 event loop、批量吞吐低、故障放大 | Theme B / Phase 5 |
| 工作流状态弱类型 | `AgentState` + 嵌套 `TypedDict` + free-text；structured output 失败后退化成字符串 | P2.23 类错误、路由脆弱、难追踪 transition | Theme C / Phase 6 |
| ACL 覆盖不完整 | `interface.py` 是真实 ACL，但只覆盖 3 个顶层 vendor；11 个底层数据源仍在 `a_stock.py` 硬编码 fallback | vendor 替换困难、DataFrame/str schema 泄漏到 Agent | Theme D / Phase 4–5 |
| 测试与契约不足 | 5 个关键模块 0 unit test；多个 hotfix 缺 integration/contract test | 迁移无法建立可信回归基线 | Phase 1–2，贯穿后续阶段 |
| 运维可观测性割裂 | tracker 在内存，history 与 logs 分离；实时状态主要靠轮询/磁盘读取 | 故障定位慢、用户看见 zombie/stuck、缺端到端 provenance | Theme A/C + Phase 7 |
| 第三方能力手写/脆弱 | 直连免费源、4 通知渠道手写、quality gate 非真正分支、trail-stop 为 stub | 维护成本随 vendor/channel 增长 | Phase 8 |

### 1.3 目标架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Application / Delivery                                               │
│ FastAPI · LangGraph adapters · WebSocket/SSE · existing UI          │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ typed commands / events / DTO
┌───────────────────────▼──────────────────────────────────────────────┐
│ Core Workflow — Theme C                                              │
│ AnalysisAggregate · explicit transitions · QualityPolicy             │
│ IAnalyst / IDebator / IManager · typed LLMResult · provenance        │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ MarketDataGateway / DataResult
┌───────────────────────▼──────────────────────────────────────────────┐
│ Data Access — Theme B + Theme D                                      │
│ async ACL · Protocol adapters · configurable fallback chain          │
│ OhlcvBar / Quote / NewsItem · rate limit · retry · circuit breaker  │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ events / snapshots / migration metadata
┌───────────────────────▼──────────────────────────────────────────────┐
│ Persistence — Theme A                                                │
│ SQLite + WAL · schema migrations · transactions · indexed queries   │
│ history · logs · portfolio/schedule/job metadata as scoped rollout   │
└──────────────────────────────────────────────────────────────────────┘
```

目标不是重写现有系统，而是在 monolith 内形成四条稳定边界：

- **Theme A：SQLite + WAL 统一持久化**——先稳定事实与运维数据。
- **Theme B：Async 数据访问层**——在可审计、可限流的边界上提高吞吐。
- **Theme C：Typed Aggregate + 显式 State Machine**——把 LLM 不确定性隔离在 adapter 外缘。
- **Theme D：ACL 覆盖全 11 数据源**——使 vendor、fallback 和返回 schema 可替换。

### 1.4 业务价值

| 价值 | 目标能力 | 可验证结果 |
|---|---|---|
| 可观测性 | 每次 Agent、tool、vendor、store 操作有稳定 identity、metrics 和 trace | 可由 `analysis_id` 定位完整链路；实时日志无需刷新 |
| 可维护性 | 状态转换、schema migration、retry/fallback 不再散落 | 单模块 contract test 能捕获回归；无字符串前缀决定辩论路由 |
| 可扩展性 | async fan-out/fan-in、per-host 限流、索引查询 | 单笔分析由 16+ 分钟降至 5 分钟内；批量任务不阻塞 event loop |
| 可替换性 | Repository/Protocol、typed DTO、provider config | 新增/替换 vendor、通知 channel、LLM provider 时不改核心领域逻辑 |

### 1.5 五份文档的 50 条建议如何唯一收口

下表是整合索引。每项只指定一个**主要落点**，避免在多个主题重复实施；“支撑”表示它是该 Phase 的配套工作，不代表另起迁移项目。

| 来源 | 原建议 | 本 Roadmap 唯一落点 |
|---|---|---|
| #1 Core R1 | Repository Protocol / 依赖注入 | Phase 3 的 store seam，支撑 Theme A |
| #1 Core R2 | in-process EventBus | Phase 7 的事件/stream seam，支撑 Theme C observability |
| #1 Core R3 | TrackerStore 持久化 | Phase 3，纳入统一运行状态持久化 |
| #1 Core R4 | zombie 启动延迟修复 | Phase 1–3，先修复再由 SQL 状态查询替代扫描 |
| #1 Core R5 | `AnalysisId` value object | Phase 6，typed aggregate identity |
| #1 Core R6 | backend contexts ACL | Phase 3/6 的应用层 adapter seam |
| #1 Core R7 | 真实化 rebalance signal | Phase 8 第三方/业务策略收尾 |
| #1 Core R8 | SQLite 迁移 | **Theme A / Phase 3** |
| #1 Core R9 | apprise 替换 Notifier | Phase 8 |
| #1 Core R10 | 真实 trailing stop | Phase 8 |
| #2 Agents R1 | Agent Protocol + 最小 DTO | **Theme C / Phase 6** |
| #2 Agents R2 | typed aggregate + transition commands | **Theme C / Phase 6** |
| #2 Agents R3 | Evidence / Report value object | Theme C，并与 Theme D `DataResult` 对接 |
| #2 Agents R4 | pluggable Quality Policy | Phase 6，Phase 8 启用真实 gate policy |
| #2 Agents R5 | analyst fan-out/fan-in | Phase 6；依赖 Phase 5 async |
| #2 Agents R6 | Agent Registry + graph spec | Phase 6 |
| #2 Agents R7 | typed LLM Gateway / 调用预算 | Phase 6 |
| #2 Agents R8 | typed schema 保留到 state | Phase 6 |
| #2 Agents R9 | enum/round object 路由 | Phase 6 |
| #2 Agents R10 | context assembly 与 reasoning 拆分 | Phase 6 |
| #2 Agents R11 | typed DataGateway + provenance | Theme C/D 接缝，Phase 4–6 |
| #2 Agents R12 | Agent contract tests | Phase 2 建基线，Phase 6 扩展 |
| #2 Agents R13 | 风险 judge 统一语言 | Phase 6 schema/registry 命名 |
| #2 Agents R14 | AgentRun / TransitionEvent observability | Phase 6 产事件，Phase 7 streaming |
| #3 Infra R1 | OHLCV Protocol + fallback composite | Phase 4，Theme D 前置 seam |
| #3 Infra R2 | OhlcvBar/Quote/NewsItem 等 VO | Phase 4，Theme D |
| #3 Infra R3 | hot-money tool drift | 已在源文档验证为已修复并撤销；不排入实施 |
| #3 Infra R4 | 统一 cache | Phase 4 统一接口，Phase 3 SQLite 可作 metadata/backend |
| #3 Infra R5 | RateLimiter/Retry/CircuitBreaker | Phase 5，Theme B |
| #3 Infra R6 | yfinance/alpha_vantage 退役 | Phase 8，须先有替代 provider |
| #3 Infra R7 | Tushare Pro/Wind/iFinD 统一付费 API | **Phase 8 / Theme D provider replacement** |
| #3 Infra R8 | async dataflows | **Theme B / Phase 5** |
| #4 Deep R1 | ACL fallback exception taxonomy | Phase 4 |
| #4 Deep R2 | per-vendor circuit breaker | Phase 5 |
| #4 Deep R3 | Ticker 提升到 domain VO | Phase 4 |
| #4 Deep R4 | ACL 覆盖 11 数据源 | **Theme D / Phase 4–5** |
| #4 Deep R5 | PortfolioRating typed contract | Phase 6 |
| #4 Deep R6 | MemoryProvider 抽象 | Phase 6 的 Protocol 批次；具体新后端延后 |
| #4 Deep R7 | async ACL | **Theme B / Phase 5** |
| #4 Deep R8 | YAML/TOML provider config | Theme D / Phase 4 |
| #5 Ops R1 | meta/history 写加 `fcntl.flock` | Phase 1 |
| #5 Ops R2 | `ChunkType` Enum | Phase 1 |
| #5 Ops R3 | chunk count 一致性校验 | Phase 2–3 migration verification |
| #5 Ops R4 | log cleanup | Phase 3d |
| #5 Ops R5 | history cleanup | Phase 3d |
| #5 Ops R6 | rerun endpoint | Phase 1 hotfix closure |
| #5 Ops R7 | delete 级联 | Phase 1 hotfix closure；Phase 3 用 FK/transaction 固化 |
| #5 Ops R8 | LogStore JSONL → SQLite | **Theme A / Phase 3** |
| #5 Ops R9 | HistoryStore JSON → SQLite | **Theme A / Phase 3** |
| #5 Ops R10 | WebSocket/SSE 实时日志 | Phase 7 |

> **归属纠正**：#3 Infra R7 的原意是“统一付费数据 API”，不是 SQLite。它在 Theme A 中仅消费迁移状态/缓存/审计能力，主实施落点必须是 Theme D/Phase 8；这样既不遗漏，也不把同一建议重复实施。

---

## 2. 四大迁移主题（4 Major Migration Themes）

### 2.1 依赖顺序

四个主题按必须先稳定的基础能力排列，而不是按目录或团队排列：

```text
Theme A（无依赖：持久化事实先稳定）
    ↓
Theme B（依赖 A：async 运行状态、缓存/限流观测可持久化）
    ├──────────────→ Theme C（依赖 B：并行 workflow + typed state）
    └──────────────→ Theme D（依赖 B：11 vendor 的最终 async ACL）
```

- **Theme A → B → C** 是主风险链。
- **Theme D 也依赖 B**，但 Phase 4 会先建立同步 Protocol/DTO/config seam；到 Phase 5 完成 async adapter 后，Theme D 才算完成。这解释了“Phase 4 ACL 先做、Theme D 最终依赖 B”并不矛盾。
- Theme C 与 D 在 B 后可部分并行，但本 Roadmap 为降低单体仓库集成风险，仍按 Phase 5 → 6 收敛。

### 2.2 Theme A：SQLite + WAL 统一持久化

**来源收口**：#1 R1/R3/R8，#5 R3/R4/R5/R8/R9；#3 R7 只使用其提供的迁移审计能力，不作为本主题的错误主归属。

| 属性 | 规划 |
|---|---|
| 影响范围 | `backend/core/history_store.py`、`log_store.py`、`job_queue.py`、`scheduler.py`（部分）；后续可覆盖 portfolio，但 Phase 3 首批以 history/log/runtime metadata 为主 |
| 价值 | 并发安全、事务、SQL 查询、索引、schema version、替代散落 JSON/JSONL |
| 依赖 | **无** |
| ROI | ★★★★☆；高，但 schema migration 必须可重复、可校验 |
| 主题工作量 | **4–6 周**；Phase 3 主实施 3–4 周，其余准备/观察分布在 Phase 1–2/7 |
| 首要风险 | 既有 `history/*.json` 与 task JSONL 数据迁移丢失、重复或顺序变化 |

**目标边界**：

- Repository Protocol 保留现有调用语义，SQLite 实现隐藏在 adapter 后。
- SQLite 启用 `journal_mode=WAL`、`foreign_keys=ON`、明确 `busy_timeout`；连接生命周期由 store/composition root 管理。
- schema 至少包含 `schema_migrations`、`history`、`stage_reports`、`log_tasks`、`log_events`；job/schedule 只迁移明确需要持久化的 runtime metadata，不把线程对象写入数据库。
- `log_events` 按 `(analysis_id, sequence)` 保序并建 `(ticker, ts)`、`(type, ts)` 索引；History 与 Log 用同一 `analysis_id` 关联。
- 原始 JSON/JSONL 在迁移后保留 7 天只读观察期；备份、行数、hash、业务字段对账全部通过后才清理。

**完成门槛**：

1. JSON → SQLite 100% 记录可追溯，迁移脚本可重复执行且幂等。
2. history/log 双读对比 7 天无差异；并发写测试无 `database is locked`、lost update 或损坏。
3. 所有现有 API 输出保持兼容；索引查询结果与旧扫描排序一致。
4. 回滚时可切回只读 JSON + 恢复备份，不依赖不可逆 schema 变化。

### 2.3 Theme B：Async 数据访问层

**来源收口**：#3 R5/R8，#4 R2/R7，以及 #2 R5 的并行前提。

| 属性 | 规划 |
|---|---|
| 影响范围 | `tradingagents/dataflows/` 全部 11 个外部数据源、`interface.py`、Agent tool facade、LangGraph ToolNode adapter |
| 价值 | 提高吞吐、限流友好、不阻塞 asyncio event loop、支持可控 fan-out/fan-in |
| 依赖 | **Theme A**：运行状态、cache metadata、rate-limit/circuit 状态和观测数据先有稳定持久化/查询边界 |
| ROI | ★★★★☆；高，但必须逐 vendor 适配而非全量切换 |
| 主题工作量 | **6–8 周**；Phase 5 是集中交付，Phase 4 完成 contracts |
| 首要风险 | `httpx.AsyncClient` lifecycle、连接池泄漏、timeout/cancellation 语义改变、vendor 限流被并发放大 |

**目标边界**：

- composition root 创建并关闭共享 `httpx.AsyncClient`；禁止每次 tool call 新建 client。
- timeout 分层：connect/read/write/pool + workflow deadline；所有 cancellation 可向上游传播。
- per-host semaphore/token bucket，结合 retry（仅幂等、带 jitter）和 circuit breaker；失败返回 typed `DataResult`，不伪装成空数据。
- 对暂时无法 async 化的 mootdx/同步 SDK 使用受限线程池 adapter，避免阻塞 event loop。
- 先 shadow/dual-run，再按 vendor feature flag 切换；同步 facade 在兼容窗口内保留。

**完成门槛**：

1. 11 个数据源都有 async adapter 或明确的 bounded-thread adapter。
2. client 创建/关闭、timeout、cancel、rate-limit、breaker half-open 有 contract test。
3. 同输入下同步/async 结果在允许的时间戳差异内等价。
4. p95 数据获取延迟和错误率不劣于基线；event loop lag 有指标且不超门槛。

### 2.4 Theme C：Typed Aggregate + 显式 State Machine

**来源收口**：#2 R1–R14 全部建议，#1 R5，#4 R5/R6；其中 observability 在 Phase 7 展示。

| 属性 | 规划 |
|---|---|
| 影响范围 | `tradingagents/agents/`、`AgentState`、16 个业务 Agent、graph setup/conditional logic、quality gate、LLM/Tool adapters |
| 价值 | 控制 P2.23 structured-output failure 的影响范围、类型安全、显式 transition、contract test、可观测性 |
| 依赖 | **Theme B**；并行 Agent 和 async tool failure 必须先有稳定结果契约 |
| ROI | ★★★★☆；高，但核心 workflow 变化风险最大 |
| 主题工作量 | **8–12 周**；Phase 2 建测试，Phase 6 主迁移，Phase 7 完成观测 |
| 首要风险 | LLM 仍可能输出不稳定 JSON；过早强类型会将可降级结果变成全流程失败 |

**目标边界**：

- `AnalysisAggregate` 使用 Pydantic v2 schema；LangGraph dict 仅为 adapter，不再是领域事实的唯一表达。
- 显式 phase 与 command：`record_report`、`complete_quality_review`、`append_argument`、`publish_research_plan`、`publish_trader_proposal`、`publish_final_decision`。
- `IAnalyst` / `IDebator` / `IManager` 只接收最小 request DTO，返回 typed artifact。
- `Evidence` / `SourceRef` / `DataResult` 保存 vendor、retrieved_at、partial、missing items 和 error code；Markdown 是 read model，不再反向充当领域状态。
- `ILLMInvoker` 返回 `LLMResult[T]`，记录 attempts/provider/fallback/tokens；schema parse failure 是显式状态，而不是普通文本。
- 辩论路由用 speaker/phase/round enum 和纯 transition function，不读取 LLM 文本前缀。
- Quality Gate 拆为 hard checker、可选 LLM reviewer 和 `QualityPolicy`；只有 policy 负责 PASS/WARN/FAIL 路由。

**对 P2.23 的准确承诺**：typed aggregate 不会让模型永远输出合法 JSON；它会让 malformed output 在 LLM adapter 边界被识别、记录、重试或降级，阻止未验证 free-text 污染后续状态和路由。

**完成门槛**：

1. 16 个业务 Agent 均有最小 DTO contract test；graph topology 与 transition table 有测试。
2. state 中保存 typed artifact；Markdown 只作为兼容输出。
3. malformed JSON、timeout、partial reports、budget exhausted 都有确定转移和可观测事件。
4. 7 Analyst fan-out/fan-in 在并发安全、消息隔离和 vendor 限流下启用；失败 Agent 可显式 degraded。

### 2.5 Theme D：Anti-Corruption Layer 覆盖全 11 数据源

**来源收口**：#3 R1/R2/R4/R7，#4 R1/R3/R4/R8，#2 R11。#3 R7 的付费 provider 替换在 Phase 8 落地。

| 属性 | 规划 |
|---|---|
| 影响范围 | `tradingagents/dataflows/interface.py`、`a_stock.py`、11 个数据源 adapter、19 个 Agent-facing tools |
| 价值 | 统一 vendor contract、配置化 fallback chain、value object 替代 DataFrame/str schema 泄漏 |
| 依赖 | **Theme B** 才能完成；Phase 4 先建同步 seam，Phase 5 再完成 async ACL |
| ROI | ★★★☆☆；中等短期收益、很高长期替换价值 |
| 主题工作量 | **6–8 周**；分散在 Phase 4–5，避免与 Theme B 重复计时 |
| 首要风险 | 11 个 vendor schema/错误语义各异，适配与黄金样本维护量大 |

**目标边界**：

- 以 capability Protocol 分组，而不是为每个 vendor 建一个巨型统一接口：OHLCV、quote、fundamentals、news、signal。
- `OhlcvBar`、`Quote`、`NewsItem`、`FinancialStatement`、`FundFlowSnapshot` 等 value object 隔离外部字段。
- fallback chain 是配置化 composite；YAML/TOML 经 schema validation 后载入，配置变化可审计。
- vendor exception 归一为 `VendorTimeout`、`VendorRateLimited`、`VendorParseError`、`VendorUnavailable`；不再用空字符串表示失败。
- 保留现有 `route_to_vendor` facade 作为兼容入口；逐 tool 切换到 typed gateway。

**完成门槛**：

1. 11 个数据源均通过 ACL，`a_stock.py` 内不再存在不可配置的跨 vendor 嵌套 fallback。
2. 19 个 tools 与 ACL capability 一一对应；返回 typed result，再由 tool adapter 渲染模型上下文。
3. YAML/TOML 配置有 schema、默认值、secret 引用规则、变更审计和安全回退。
4. 每个 vendor 有黄金样本/contract test，外部字段变化只需修改对应 adapter。

---

## 3. 八阶段实施计划（Phase Plan）

### 3.1 总览

| Phase | 周期 | 资源 | 主要交付 | 主题关系 | 主要风险摘要 |
|---|---:|---:|---|---|---|
| 1 短期热修 | 1–2 周 | 1 人 | hotfix 收口、真实 race 修复、`ChunkType` | A/C 前置 | 锁顺序与行为回归 |
| 2 单测补齐 | 2–3 周 | 1 人 | 5 个零测试模块 + 14 hotfix integration | 全主题安全网 | flaky / 假覆盖 |
| 3 SQLite + WAL | 3–4 周 | 1–2 人 | migration、History、Log、cleanup | **A** | data loss / schema mismatch |
| 4 ACL 扩展 | 3–4 周 | 1–2 人 | Protocol、fallback、VO、配置 | D 前置 | adapter 语义漂移 |
| 5 Async 数据层 | 4–6 周 | 2 人 | httpx、限流、breaker、11 vendor | **B + 完成 D** | client/timeout/rate-limit |
| 6 Typed Aggregate | 4–6 周 | 2 人 | Pydantic、Protocols、enum route、contracts | **C 主体** | workflow 行为漂移 |
| 7 实时日志 | 4–8 周 | 2 人 | iterator、WebSocket/SSE、frontend subscribe | A/C 观测 | 连接泄漏 / 背压 |
| 8 第三方替换 | 4–6 周 | 1 人 | 付费数据源、apprise、真实 policies | D 收尾 | vendor 成本/行为变化 |

### 3.2 Phase 1（立即，1–2 周）：短期热修

**目标**：在大迁移前消除已知真实 bug，不把 race 和未闭合 hotfix 带入新存储层。

**工作包**：

1. 盘点 P2.10–P2.25，确保已知 hotfix 都有独立变更记录且进入迁移基线；“已 commit”是未来 Phase 1 的验收要求，不是本轮文档工作的动作。
2. 给 `LogWriter._write_meta` / `_write_meta_field` 与 `HistoryStore._write` 增加跨进程文件锁；确定 sidecar lock 或固定 lock-order，避免锁住被 replace 的 inode。
3. 修复 operation 文档列出的真实 race、rerun 半成品和 delete 不级联；明确旧 thread 写旧 `analysis_id` 的拒绝规则。
4. 增加 `ChunkType` enum，消除 API/UI/store 之间字符串漂移。
5. 固化 zombie/stuck cleanup 的触发与状态语义，为 SQLite 状态迁移提供确定基线。

**验收**：并发 writer 压测无 lost update；rerun 产生新 analysis id；delete 行为一致；P2.10–P2.25 清单无悬空项。

**工作量/风险**：1 人、1–2 周。主要风险是错误锁顺序造成死锁或吞吐下降；详见 §4 Phase 1。

### 3.3 Phase 2（短期，2–3 周）：单测与迁移安全网

**目标**：先建立行为基线，再替换基础设施。

**工作包**：

1. 补齐 5 个当前 0 unit test 的关键模块：`interface.py`、`stockstats_utils.py`、`memory.py`、`rating.py`、`structured.py`。
2. 为 14 个缺测试覆盖的 hotfix 增加 integration/regression test；以实际 hotfix 清单为准建立 traceability matrix。
3. 增加 store contract suite：同一套测试运行 JSON/JSONL 实现与未来 SQLite 实现。
4. 增加 migration golden fixtures：正常、空文件、损坏 JSON、重复 id、旧 schema、legacy log、乱序 JSONL。
5. 增加 chunk count 一致性校验和 CLI/测试工具，作为 Phase 3 前数据体检。
6. 为 Agent 建第一层 contract tests：malformed structured output、free-text fallback、debate route、quality hard check。

**验收**：`pytest` 0 failed；新增 integration test 稳定重复运行；迁移 fixtures 覆盖已知历史格式；失败测试能证明会捕获目标回归。

**工作量/风险**：1 人、2–3 周。主要风险是只验证 mock 实现、未锁住真实行为或引入 flaky timing test；详见 §4 Phase 2。

### 3.4 Phase 3（中期，3–4 周）：SQLite + WAL 持久化

**目标**：完成 Theme A 的首批生产切换，统一 history/log/runtime metadata 的事实边界。

#### Phase 3a：schema 与 migration script

- 定义 versioned schema、索引、外键和 migration journal。
- migration 按 discover → validate → backup → import → reconcile → mark complete 执行。
- JSON/JSONL → SQLite 以 source path + source hash 作为幂等键；重复运行不重复插入。
- 导入前后校验 record count、关键字段、event sequence、content hash 和 status 分布。

#### Phase 3b：HistoryStore

- 先实现 `SQLiteHistoryRepository`，复用 Phase 2 contract suite。
- 采用 shadow read/diff，再短期 dual-write；切换后旧 JSON 为只读 rollback source。
- `stage_reports` 与 history 用外键/事务维护；list/filter 走索引。

#### Phase 3c：LogStore

- `log_tasks` 保存 task metadata，`log_events` 保存有序 chunk。
- append 与 chunk count 在同一事务中更新；杜绝 meta count 与文件行数漂移。
- 保留 API shape 和 legacy reader；新写入只进 SQLite，legacy 导入可分批进行。

#### Phase 3d：data cleanup

- 成功切换后保留原 JSON/JSONL **7 天**只读观察期；到期仅在对账 100% 通过且有备份时删除老 log。
- cleanup 先 dry-run，输出候选、大小、最后访问时间和关联 analysis id，再显式执行。
- 稳态保留策略继续支持 age/task-count/size 三维门槛，避免只靠单一 TTL。

**验收**：0 数据丢失；7 天双读无差异；并发测试通过；备份恢复演练成功；所有 API 兼容。

**工作量/风险**：1–2 人、3–4 周。主要风险是 schema migration/data loss/downtime；详见 §4 Phase 3。

### 3.5 Phase 4（中期，3–4 周）：ACL 扩展与 typed data contracts

**目标**：不立即改成 async，先把 11 个 vendor 的稳定 seam 建好，控制 Phase 5 的爆炸半径。

**工作包**：

1. 为 11 个 vendor 按 capability 抽 Protocol；现有函数用 sync adapter 包装。
2. 将 mootdx → Sina → push2his 等 3-fallback chain 通用化为 configurable composite。
3. 建立 `OhlcvBar`、`Quote`、`NewsItem`、`FinancialStatement`、`FundFlowSnapshot` 等 value object，保留 str/Markdown renderer 兼容 Agent。
4. 统一 vendor exception taxonomy；fallback 只处理可降级错误，编程错误不得静默吞掉。
5. 把 provider/fallback/timeout/rate-limit 配置迁到 YAML/TOML，并加 schema validation；secret 只引用环境变量，不写入配置文件。
6. 把 `Ticker` / `PortfolioRating` 等跨层 vocabulary 提升到 domain contract，结束 private helper 泄漏。
7. 统一 cache interface；不在此阶段强行改变所有物理 cache backend。

**重要边界**：Phase 4 只完成 Theme D 的同步 contract；Theme D 要到 Phase 5 的 async adapter 全覆盖后才完成。

**验收**：19 个 tool 与 capability map 一一对应；11 vendor 有 contract tests；旧 facade 输出不变；fallback 顺序可配置且有审计。

**工作量/风险**：1–2 人、3–4 周。主要风险是 value object 归一化造成数据精度/字段语义漂移；详见 §4 Phase 4。

### 3.6 Phase 5（中期，4–6 周）：Async 数据访问层

**目标**：完成 Theme B，并在 async runtime 上完成 Theme D。

**工作包**：

1. 使用共享 `httpx.AsyncClient` 替换 `requests`/`urllib` HTTP 路径；明确 client lifespan。
2. 为 connect/read/write/pool 设置 timeout；workflow deadline 和 cancellation 向 vendor adapter 传播。
3. 实现 per-host rate limit、bounded concurrency、retry with jitter、circuit breaker 和 half-open probe。
4. 逐 vendor 迁移 11 个数据源：一次只切一个 capability/vendor，保留 feature flag 与 sync fallback。
5. mootdx/付费同步 SDK 使用 bounded executor adapter，不直接阻塞 event loop。
6. 使用 `asyncio.gather`/TaskGroup 只并发彼此独立的请求；同 host 限流和 fallback 次序仍受 policy 约束。
7. 暴露 vendor latency、timeout、retry、breaker、fallback、event-loop lag 指标。

**验收**：11 vendor async/bounded adapter 全覆盖；client 无泄漏；cancel 不遗留后台请求；p95 不退化；rate-limit 错误不增加；sync/async golden result 等价。

**工作量/风险**：2 人、4–6 周。主要风险是连接池、timeout、取消和并发放大外部限流；详见 §4 Phase 5。

### 3.7 Phase 6（中期，4–6 周）：Typed Aggregate + 显式 State Machine

**目标**：把 16 Agent 的领域状态与 LangGraph transport 解耦，完成 Theme C 主体。

**工作包**：

1. 用 Pydantic v2 定义 `AnalysisAggregate`、`EvidenceBundle`、debate、proposal、decision、quality schemas；保留 version 字段。
2. 定义 `IAnalyst`、`IDebator`、`IManager`、`ILLMInvoker`、`MarketDataGateway`；LangGraph node 只做 adapter。
3. 将 state mutation 改为显式 transition commands，校验 phase、speaker、round、required artifacts 和版本单调。
4. 将辩论路由 enum 化；transition 为纯函数并表格化测试。
5. 保留 typed schema 到 state；Markdown 仅用于 UI/log/backward compatibility。
6. 拆分 context assembly、LLM invocation、output parser 与 state adapter；structured-output failure 产生 typed failure。
7. 建 Agent Registry/声明式 graph spec，统一 role、tool、input/output、LLM policy 和预算。
8. 在 Phase 5 的 async gateway 上实现 7 Analyst fan-out/fan-in，独立 message context，支持 degraded result。
9. Quality Gate 变为 `HardQualityChecker + LLMQualityReviewer + QualityPolicy`；contract test 覆盖 PASS/WARN/FAIL 路由。
10. 发出稳定 `AgentRun` / `TransitionEvent`，为 Phase 7 streaming 提供事件源。

**验收**：16 Agent contract tests、graph topology、failure path 全通过；P2.23 类 malformed output 不污染 state；最终决策可追溯到 evidence/vendor/transition。

**工作量/风险**：2 人、4–6 周。主要风险是强类型过脆和 graph 行为漂移；详见 §4 Phase 6。

### 3.8 Phase 7（长期，4–8 周）：实时 log streaming + WebSocket/SSE

**目标**：在 SQLite event store 与 typed transition event 上提供稳定实时观测，不改变分析领域逻辑。

#### Phase 7a：LogStore iterator

- 提供按 `analysis_id + sequence` 的增量 iterator/cursor。
- 支持断线续传、last-event-id、bounded buffer 和慢消费者背压。
- EventBus/TransitionEvent 写库与发布顺序可解释；数据库仍是最终事实源。

#### Phase 7b：WebSocket/SSE endpoint

- SSE 作为单向日志默认方案，WebSocket 仅用于确有双向控制需求的场景。
- 鉴权、订阅隔离、heartbeat、connection limit、disconnect cleanup、resume cursor 都有测试。
- endpoint 不发送完整敏感 prompt；只发送定义好的 event DTO。

#### Phase 7c：Frontend subscribe

- 前端按 analysis id 订阅，显示 agent/store/vendor 的实时阶段、错误和 fallback。
- 断线回退为 REST catch-up；刷新后从 cursor 恢复，不丢事件、不重复渲染。

**验收**：每个 agent/store 有 metrics + tracing；断线重连无缺口；慢客户端不拖慢分析；旧 REST/轮询仍可回退。

**工作量/风险**：2 人、4–8 周。主要风险是连接泄漏、背压、事件重复/乱序和前端状态同步；详见 §4 Phase 7。

### 3.9 Phase 8（长期，4–6 周）：第三方替换与策略真实化

**目标**：在 A–D 稳定边界上替换最脆弱、维护成本最高的第三方接入和 stub。

**工作包**：

1. 从 Tushare Pro / Wind / iFinD 中先选一个 primary provider，以 ACL adapter 接入；逐 capability 替换 mootdx、Sina 等直连免费源，保留合规 fallback。
2. 在替代 provider 的 contract/SLA 达标后，再将 yfinance/alpha_vantage legacy 实现移入 `_deprecated/` 或删除依赖。
3. 用 apprise 统一 WeCom、Email、Desktop、Log 四渠道；先 shadow-send，再按 channel feature flag 切换。
4. 真实化 quality policy：PASS/WARN/FAIL 必须改变 graph transition，而不只是生成 Markdown。
5. 真实化 `trailing_stop`：持久化 high-water mark，使用历史 K 线并明确复权、交易日、gap 风险。
6. 真实化 `get_rebalance_signals`：typed PortfolioDecision 与 Position 比较，生成可解释 action/urgency。
7. MemoryProvider 仅建立可替换接口；ChromaDB/LanceDB 等具体后端只有在有明确检索指标时另立项目，避免把 Phase 8 扩成无界范围。

**验收**：primary provider SLA/contract test 达标；apprise 四渠道等价；quality FAIL 确实路由；trail-stop/rebalance 有历史回放与幂等测试。

**工作量/风险**：1 人、4–6 周。主要风险是付费 vendor 成本/许可、字段差异、通知重复、策略行为变化；详见 §4 Phase 8。

---

## 4. 风险与回退（Risk & Rollback）

### 4.1 共用发布纪律

每个 Phase 都遵循以下规则：

1. **小步提交**：schema、adapter、shadow mode、切流、cleanup 分开提交，便于 `git revert`；本轮 Roadmap 本身不 commit。
2. **先备份再迁移**：原始 JSON/JSONL、SQLite DB 和配置都带时间戳备份；恢复演练通过后才能切流。
3. **feature flag / compatibility adapter**：新旧实现可短期并存；禁止同一部署同时做不可逆 schema 删除与业务行为切换。
4. **观测窗口**：切流后至少观察一个完整业务周期；Phase 3 的旧数据保留窗口为 7 天。
5. **自动触发回滚**：测试失败、数据 corruption、错误率上升、关键性能显著退化或无法解释的决策变化，任何一项达到门槛即停止扩流。

### 4.2 分 Phase 风险矩阵

| Phase | 主要风险 | 预防/探测 | 回退方案 | 回滚触发条件 |
|---|---|---|---|---|
| 1 热修 | `flock` 顺序错误导致死锁；锁住旧 inode；hotfix 改变 API 行为 | 多进程并发测试、lock timeout、rerun/delete regression | `git revert` 单个热修；恢复旧 writer；保留损坏前文件备份 | deadlock/timeout；lost update；既有 API/test fail |
| 2 测试 | flaky timing；mock 与真实系统不一致；为通过测试固化错误行为 | fake clock、临时目录隔离、至少一层真实 integration、mutation/negative check | 回退 flaky test；保留可重复的 contract/golden tests | CI 不稳定；同一 commit 重跑结果不一致；测试无法捕获目标故障 |
| 3 SQLite | schema mismatch、重复/漏导、event 乱序、DB lock、切换 downtime | dry-run、幂等 migration、count/hash/业务对账、WAL 并发压测、7 天双读 | 停写；切回 JSON read/write adapter；恢复 JSON/DB 备份；revert 切流 commit | 任一数据不一致/损坏；迁移非幂等；API 结果漂移；lock error 超阈值；性能退化 >20% |
| 4 ACL | 归一化丢字段/精度；fallback 顺序变化；配置错误导致全源不可用 | golden payload、per-vendor contract、配置 schema、legacy renderer diff | feature flag 切回旧 `route_to_vendor`/硬编码路径；revert 单 adapter | typed vs legacy 结果不一致；错误 fallback；关键字段缺失；contract fail |
| 5 Async | client 泄漏、event loop 阻塞、取消失效、并发触发封禁、retry storm | lifespan test、loop-lag metric、bounded semaphore、retry budget、shadow traffic | per-vendor 切回 sync adapter/受限线程池；降低并发；revert vendor 切流 | fd/连接持续增长；p95 退化 >20%；429/封禁显著增加；cancel 后任务残留 |
| 6 Typed | LLM JSON 不稳定导致失败率上升；state schema 不兼容；graph transition 改变最终决策 | tolerant boundary parser、schema version、old/new aggregate shadow compare、contract/topology test | feature flag 使用旧 AgentState adapter；保留 Markdown path；revert 单角色/transition | malformed-output hard failure 上升；非法 transition；决策差异无法解释；全量 test fail |
| 7 Streaming | WebSocket/SSE 连接泄漏、背压拖慢生产者、乱序/重复、敏感信息泄漏 | bounded queue、cursor/sequence、disconnect cleanup、load/security test、字段白名单 | 关闭 streaming flag；回退 REST polling；DB event store 不回滚 | 分析吞吐下降 >10%；内存/连接持续增长；事件缺口；越权或敏感内容暴露 |
| 8 替换 | provider SLA/许可/成本不达标；字段语义变化；apprise 重复通知；策略误触发 | provider contract + shadow compare、预算告警、notification idempotency key、历史回放 | 切回原 vendor/channel/quality policy；保留旧 adapter；禁用新策略 flag | 数据差异超容忍；费用超预算；通知重复/漏发；质量/止损策略误触发 |

### 4.3 数据回滚细则

- 每次 migration 记录 `migration_id`、source path/hash、rows imported、started/finished、tool version 和 result。
- 回滚不通过“反向猜 schema”完成，而是停止新写入、保存当前 DB、恢复切流前备份，再运行经过验证的旧实现。
- 删除旧 JSON/JSONL 前必须完成恢复演练；7 天观察窗口内只读，不修改原文件。
- schema 采用 expand → migrate → contract：先加表/列，再回填和切读，最后才在后续版本清理旧结构。
- perf rollback 以同一 fixture/环境的 p50/p95、event-loop lag、error rate 和资源占用比较，不凭主观感觉判断。

---

## 5. 时间线（Timeline）

### 5.1 顺序时间线

```text
月 1      Phase 1 热修（1–2 周） + Phase 2 起步
月 2      Phase 2 测试（2–3 周） → Phase 3 SQLite
月 3      Phase 3 完成（3–4 周） → 7 天观察
月 4      Phase 4 ACL（3–4 周）
月 5–6    Phase 5 Async（4–6 周）
月 6–7    Phase 6 Typed Aggregate（4–6 周）
月 8–9    Phase 7 Streaming（4–8 周）
月 9–10   Phase 8 第三方替换（4–6 周）
```

| Phase | 最短 | 最长 | 资源 | 累计最短 | 累计最长 |
|---|---:|---:|---|---:|---:|
| 1 | 1 周 | 2 周 | 单人 | 1 | 2 |
| 2 | 2 周 | 3 周 | 单人 | 3 | 5 |
| 3 | 3 周 | 4 周 | 1–2 人 | 6 | 9 |
| 4 | 3 周 | 4 周 | 1–2 人 | 9 | 13 |
| 5 | 4 周 | 6 周 | 2 人 | 13 | 19 |
| 6 | 4 周 | 6 周 | 2 人 | 17 | 25 |
| 7 | 4 周 | 8 周 | 2 人 | 21 | 33 |
| 8 | 4 周 | 6 周 | 1 人 | **25** | **39** |

**总计：25–39 周（约 6–10 个月）**。

### 5.2 资源与并行原则

- Phase 1–2 单人即可，重点是建立可信基线。
- Phase 3–4 可由 1–2 人完成；如果两人并行，应按 repository/schema 与 API/contract 分工，不同时修改同一 adapter。
- Phase 5–7 建议 2 人：一人负责 runtime/infra，一人负责 contract/graph/frontend；每个 vendor/Agent 仍逐个切换。
- Phase 8 以 1 人 owner 控制 provider/channel 策略，避免采购、配置和代码变更责任分散。
- 四主题的“4–6/6–8/8–12/6–8 周”是跨阶段工作量口径，不应与 8 Phase 时长再次相加。

### 5.3 阶段门（Go / No-Go）

| Gate | 进入条件 | 不满足时 |
|---|---|---|
| Phase 3 | Phase 1 race 修复完成；Phase 2 store/migration tests 通过 | 不迁移数据，继续补基线 |
| Phase 4 | SQLite 切换稳定且备份恢复演练通过 | 不扩大基础设施变更面 |
| Phase 5 | 11 vendor Protocol/DTO/config contract 已建立 | 不直接 async 化 `a_stock.py` 巨型函数 |
| Phase 6 | async failure/cancel/limit 语义稳定 | 不做 fan-out/fan-in，只保留 serial pipeline |
| Phase 7 | TransitionEvent 与 log sequence 稳定 | 继续 REST polling，不建设实时通道 |
| Phase 8 | ACL provider seam 和策略 contract 稳定 | 不移除旧 vendor/Notifier/stub fallback |

---

## 6. 成功指标（Success Metrics）

### 6.1 必达指标

| 维度 | 指标 | 验证方式 | 目标 |
|---|---|---|---|
| 测试 | 全量回归 | CI `pytest` | **0 failed**，新增 unit/integration/contract tests 全通过 |
| 数据迁移 | JSON/JSONL → SQLite 一致性 | count + identity + sequence + content hash + status distribution | **0 数据丢失，100% 一致** |
| 恢复能力 | 备份恢复 | staging 恢复演练 | RTO/RPO 在单机运维目标内，至少一次完整成功演练 |
| 性能 | 单笔完整分析 wall time | 相同 ticker/date/model/config 的基线对比 | **16+ min → < 5 min** |
| async 健康 | event loop / client | loop lag、open connections、timeout/cancel metrics | 无持续泄漏；p95 不退化；取消后无残留任务 |
| vendor 稳定 | 外部调用 | success/timeout/429/retry/fallback/breaker metrics | 每个 host 可观测；错误率不高于基线 |
| 类型安全 | workflow artifacts | schema validation + contract tests | 16 Agent 输出均通过 typed boundary；非法 transition 为 0 |
| LLM 降级 | structured-output failure | `LLMResult` metrics | 失败/重试/fallback 可计量，free-text 不直接污染 typed state |
| 可观测性 | Agent/store tracing | trace 查询 | **每个 agent / store 有 metrics + tracing**；可按 analysis id 串联 |
| 实时日志 | stream correctness | sequence/cursor/reconnect test | 断线恢复 0 缺失；重复事件可幂等消除 |
| 可替换性 | provider/channel change | fake provider + shadow test | 替换 vendor/Notifier 不改核心 aggregate/transition |

### 6.2 分阶段验收仪表板

至少保留以下时间序列并按 release 对比：

- `analysis_duration_seconds{phase,role}` 与端到端 p50/p95。
- `agent_run_total{role,outcome}`、`llm_attempts_total{provider,role,outcome}`、structured fallback ratio。
- `vendor_request_total{vendor,host,outcome}`、latency、429、timeout、retry、breaker state、fallback path。
- `store_operation_seconds{store,operation,outcome}`、SQLite busy/lock count、WAL size/checkpoint time。
- `transition_total{from,to,outcome}`、invalid transition count。
- `stream_connections`、queue depth、dropped events（目标 0）、reconnect/catch-up count。

### 6.3 性能结论的约束

“16+ 分钟降到 5 分钟内”必须在固定 model/provider、selected analysts、数据日期、网络区间与缓存策略下比较。async 与 fan-out 不能通过减少 Agent、跳过 quality gate 或使用陈旧 cache 获得虚假提升。

---

## 7. 不做（Out of Scope）

本 Roadmap 明确不做以下事项：

1. **不重写 LangGraph 框架**：保留 LangGraph 作为 workflow/delivery adapter；只把领域状态与 transition 从框架 dict 中抽离。
2. **不迁移到 PostgreSQL**：v0.7.0 单机/单用户规模下 SQLite + WAL 足够；只有经过指标证明单机写并发成为瓶颈才另立 ADR。
3. **不做微服务拆分**：monolith 优先；Protocol/ACL 是模块边界，不是部署边界。
4. **不做实时协作编辑**：v0.7.0 继续单用户优先；Phase 7 streaming 是运行日志订阅，不是协同编辑。
5. **不删除 Streamlit 8501**：此前“Phase 3 删 Streamlit”触发条件 #4 等待 7 天的事项已 CLOSED，不在本 Roadmap 重启。
6. **不一次性替换所有免费源**：Phase 8 先选一个 primary provider，按 capability 切换并保留 fallback。
7. **不把 Markdown 全部删除**：Markdown 保留为 UI/log/兼容 read model，只是不再充当核心领域事实。
8. **不在迁移中重做投资算法**：除已知 stub（quality policy、trailing stop、rebalance）外，不修改投研策略逻辑。
9. **不把 MemoryProvider 的可选后端强塞进主线**：没有检索质量指标前，不承诺 ChromaDB/LanceDB 生产迁移。
10. **不在本轮执行任何代码变更、测试配置变更或 commit**：本文件只定义后续实施顺序与门槛。

---

## 8. 与“Phase 3 删除 Streamlit”事项的关系

本 Roadmap 中的 Phase 3 与此前讨论的“Phase 3 删除 Streamlit 8501”只是名称碰巧相同，二者是两条完全独立的工作流。

| 事项 | 含义 | 状态/触发 | 是否在本 Roadmap |
|---|---|---|---|
| 旧事项：Phase 3 删除 Streamlit | 基于 8 个触发条件评估是否删除/停用 Streamlit 8501 | 必须等待用户手动执行并明确下令；触发条件 #4 等 7 天事项已 CLOSED，**不得自动重启** | **否** |
| 本文：8 Phase 代码架构迁移 | SQLite、ACL、Async、Typed Aggregate、Streaming、第三方替换 | 按本文件 Gate 与验收条件推进 | **是** |

因此：

- 任何人执行本文 Phase 3，只能进行 **SQLite + WAL 持久化迁移**，不得借同名阶段删除、停用或改造 Streamlit 8501。
- 任何 Streamlit 删除动作都需要回到原 8 个触发条件流程，等待用户手动运行和明确命令；本 Roadmap 不能视为授权。
- Phase 7 的 frontend subscribe 可以适配现有前端，但不构成替换 Streamlit 的决定。

---

## 附录 A：Roadmap 决策摘要

| 决策 | 结论 |
|---|---|
| 迁移主链 | A SQLite → B Async → C Typed；D 在 B 后完成 |
| Phase 4 为何早于 Theme B | 先建同步 ACL seam，Phase 5 再完成 async ACL；Theme D 不在 Phase 4 提前宣告完成 |
| 数据存储 | SQLite + WAL，不上 PostgreSQL |
| 交付形态 | 模块化 monolith，不拆微服务 |
| 兼容策略 | facade/adapter、shadow read、短期 dual-write、feature flag |
| 数据清理 | 迁移后原 JSON/JSONL 保留 7 天，只读对账通过后清理 |
| LLM 不确定性 | 不声称消灭；在 typed gateway 边界显式识别、重试、降级、记录 |
| 预计周期 | 25–39 周（6–10 个月） |
| 本轮变更 | 只新增 `docs/MIGRATION_ROADMAP.md`，不改代码，不 commit |

## 附录 B：实施前复核清单

- [ ] git HEAD 与计划基线差异已评审。
- [ ] P2.10–P2.25 实际 commit/test 覆盖矩阵已生成。
- [ ] 5 个零 unit-test 模块已建立行为基线。
- [ ] 生产/开发 JSON、JSONL 格式与规模已重新盘点。
- [ ] SQLite schema、backup、restore、idempotent migration 已演练。
- [ ] 11 vendor / 19 tool capability map 已冻结。
- [ ] async client lifecycle、timeout、cancel、rate-limit policy 已评审。
- [ ] 16 Agent 的 role、输入、输出、transition、failure policy 已冻结。
- [ ] 每个 Phase 的 feature flag、owner、dashboard、rollback command 已准备。
- [ ] Streamlit 删除事项未被本 Roadmap 误触发。
