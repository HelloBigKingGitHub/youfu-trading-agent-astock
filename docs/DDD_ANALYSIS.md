# Youfu-Trading-Agent-Astock DDD 领域模型分析

> **git HEAD**: `5257c0d` (v0.7.0 Phase 2 — React SPA + FastAPI 完成)
> **分析日期**: 2026-07-17
> **分析范围**: `backend/core/*` (14 模块 / 5574 LOC), `backend/api/*` (16 endpoint / 3854 LOC), `tradingagents/dataflows/a_stock.py` (2610 LOC)
> **方法**: 静态代码阅读 + git log + CLAUDE.md 交叉验证; **0 改代码, 0 commit**

---

## 1. 系统全景

### 一句话定位
基于 **LangGraph 多 Agent 框架 + 7 个 Analyst + Bull/Bear 三方风险辩论** 的 A 股投研系统,在原版 65K-Star TradingAgents 之上深度本土化 (政策/游资/解禁 3 个 A 股特化分析师 + 板块轮动日报 + 个人仓位跟踪 + 定时分析)。

### 一句话技术栈
**Python 3.11+ / FastAPI / Streamlit Web + React SPA (Vite/shadcn) / 9 个 sidebar / 多 HTTP 数据源 (mootdx / 新浪 / 东财 push2 + push2his + np-ipick / 同花顺 / 财联社) / 零第三方数据库,全 JSON 文件持久化 / 556+ pytest / croniter / Jinja2**

---

## 2. Bounded Contexts

系统按 **业务能力垂直切片** + **数据流一致性边界** 划分为 **10 个 Bounded Context**:

| # | Context | 职责 | 核心聚合 | 上游 / 下游 | 模块入口 |
|---|---|---|---|---|---|
| 1 | **Analysis** | 单笔 LangGraph 多 Agent 分析 (7 Analyst + Bull/Bear + Risk + Trader + PM) | `Analysis` + `AnalysisTracker` | D: Batch, Scheduler, Chart (行情); U: Log (写流), History (存结果) | `backend/core/tracker.py`, `web/runner.py` |
| 2 | **Log** | LangGraph stream chunks 持久化 (LLM/Tool/AgentOutput 9+3+12 类) | `LogTask` + `LogChunk` | D: Analysis (订阅 stream); U: Analysis (历史查询回放) | `backend/core/log_store.py` |
| 3 | **Chart** | K 线 / 实时行情 (mootdx → sina → push2his 三层 fallback) | `KLineSeries` + `KLineBar` | D: 外部数据源 (TCP/HTTP); U: Analysis, Portfolio, Watchlist | `tradingagents/dataflows/a_stock.py:get_stock_data`, `web/components/chart_panel.py` |
| 4 | **Sector** | 板块轮动日报 (东财 np-ipick + 同花顺涨停归因 + 百度 PAE → 4 段式 Markdown) | `SectorDigest` + `SectorPick` + `ConceptPick` | D: Chart (行情上下文); U: Scheduler (可选通知) | `tradingagents/dataflows/a_stock.py:get_sector_rotation_digest`, `backend/api/sector.py` |
| 5 | **Portfolio** | 个人仓位 (positions / transactions / alerts / accounts) + 业绩归因 (XIRR / Sharpe / MaxDD / Brinson) | `Position` + `Transaction` + `AlertRule` + `Account` | D: Chart (现价); U: Scheduler (ticker 源), Analysis (Bull/Bear 联动) | `backend/core/portfolio_store.py` |
| 6 | **Scheduler** | 定时任务 (cron + ticker 源 + 多渠道通知) | `Schedule` + `ScheduleRun` | D: Portfolio, Watchlist (ticker 源), Analysis (跑批); U: Notifier (完成回调), Batch (复用) | `backend/core/scheduler.py` |
| 7 | **Batch** | 批量分析 (JobQueue + 多个 ticker 并行 + stagger 防东财 429) | `BatchJob` + `Job` | D: Analysis (单笔), Portfolio (持仓 ticker); U: Scheduler (提交源) | `backend/core/job_queue.py` |
| 8 | **Settings** | 配置管理 (UI 偏好 + 默认值) | `AppSettings` | D: — ; U: 所有 context (读配置) | `backend/api/settings.py` |
| 9 | **Watchlist** | 自选股 (Scheduler 用的 ticker 源之一) | `Watchlist` + `WatchEntry` | D: — ; U: Scheduler (源), Analysis (待分析 ticker) | `backend/core/watchlist.py` |
| 10 | **Notifier** | 多渠道通知 (WeCom / Email / Desktop / Log) | `NotificationMessage` | D: Scheduler (完成事件); U: 外部 (Webhook / SMTP / notify-send) | `backend/core/notifier.py` |

### 上下文边界判定原则
- **业务语义独立性** (e.g. Portfolio 不知道 Analysis 的 LangGraph 细节)
- **数据流方向单向** (避免环: Analysis → Log → Analysis 是 read-only 查询回路)
- **持久化单元独立** (每个 context 写自己 `~/.tradingagents/<ctx>/` 子目录)
- **测试独立运行** (单测 monkeypatch `<CTX>_DIR = tmp_path` 不污染其他 context)

---

## 3. Context Map

### 3.1 ASCII 关系图

```
                              ┌─────────────────┐
                              │   Settings      │ (G) 提供 app config
                              │   (Generic)     │
                              └────────┬────────┘
                                       │ Conformist
                                       ▼
   ┌───────────────┐    Shared   ┌──────────────┐    ACL     ┌───────────────┐
   │   Chart       │◄──Kernel───►│  Analysis    │◄──────────►│  Log          │
   │  (Supporting) │   (行情)    │  (Core)      │            │  (Supporting) │
   └───────┬───────┘             └──────┬───────┘            └───────────────┘
           │                            │ Partnership
           │                            ├──────────────────┐
           ▼                            ▼                  ▼
   ┌───────────────┐            ┌──────────────┐  ┌───────────────┐
   │   Portfolio   │            │   Batch      │  │  Sector       │
   │  (Supporting) │◄──D────────│  (Supporting)│  │  (Core)       │
   │               │            │              │  │               │
   └───────┬───────┘            └──────┬───────┘  └───────────────┘
           │ Customer-Supplier          │
           ▼                            ▼
   ┌───────────────┐            ┌──────────────┐
   │  Watchlist    │◄──D────────│  Scheduler   │
   │  (Supporting) │  ticker源  │  (Supporting)│
   └───────────────┘            └──────┬───────┘
                                      │ Customer-Supplier
                                      ▼
                              ┌──────────────┐
                              │   Notifier   │
                              │   (Generic)  │
                              └──────────────┘
```

### 3.2 关系类型与适配点表

| 上游 → 下游 | 关系类型 | 翻译 / 适配点 | 备注 |
|---|---|---|---|
| Chart → Analysis | **Shared Kernel** | `Ticker` / `TradeDate` / `Signal` 值对象 | 两 context 共享同一份 `a_stock.py` 数据接口契约 |
| Chart → Portfolio | **Customer-Supplier** | PortfolioStore 读 `get_stock_data` 获取现价 | 实时性靠 push2 f43/f44/f45 节流 |
| Analysis → Log | **Partnership** | `AnalysisTracker.mark_stage_done()` → `LogWriter.append_chunk()` | 同步调用,Log 反向提供历史回放查询 API |
| Analysis → HistoryStore | **Conformist** | TrackerStore 直接写 HistoryStore,共用 ID 模式 (`uuid.uuid4().hex[:8]`) | **P2.25 已知 ID 一致性 bug,见架构债务 #1** |
| Portfolio → Scheduler | **Customer-Supplier** | `PortfolioStore.list_positions()` → `Scheduler._load_tickers_for_source()` | 60s polling 周期,无 push |
| Watchlist → Scheduler | **Customer-Supplier** | `WatchlistStore.list()` → 同上 | 同上 |
| Scheduler → Batch | **Customer-Supplier** | `Scheduler._run_schedule()` → `JobQueue.create_batch + submit` | 复用 batch API,不重写分析路径 |
| Scheduler → Notifier | **Open-Host Service** | `Notifier.send(channels, ...)` 公开 API,无 ACL | 单 channel 失败隔离,但 **无重试/幂等**(v0.7.0 待办) |
| Batch → Analysis | **Conformist** | `Job._run_pipeline()` → `web.runner.run_one_analysis` | 直接 import,违反 DIP,见架构债务 #4 |
| Settings → All | **Conformist** | 全局单例 read | 配置改动需重启,无 hot reload |
| Sector → (No deps) | **Standalone** | 4 段式 Markdown 一次性产出 | 与 Analysis 完全解耦 |

### 3.3 缺失 / 不足的 ACL
- **Batch ↔ Analysis**: 当前是 direct call (`from web.runner import run_one_analysis`),应引入 `AnalysisRunner` 端口
- **Scheduler ↔ Analysis**: 同上,`_run_schedule` 直接调用 `JobQueue`
- **Chart → Portfolio**: 现价注入没有事件接口,只有 read-on-demand

---

## 4. Subdomain 分类

按 **Eric Evans 核心域 / 支撑子域 / 通用子域** 三分法:

### 4.1 Core Domain (核心竞争力,优先投资)
| Context | 价值理由 |
|---|---|
| **Analysis** | 7 Analyst + Bull/Bear + Risk 三方辩论 + Trader/PM 是与 65K-Star 上游 fork 的最大差异化;中文 prompt + A 股 3 个特化分析师 (政策/游资/解禁) 是壁垒 |
| **Sector** | 4 段式 Markdown digest (np-ipick + 同花顺 + 百度 PAE) 是**纯算法编排**,不消耗 LLM token,零成本高频产出,可直接复用为日推/午推 |

### 4.2 Supporting Subdomain (支撑业务,需内部实现但非差异点)
| Context | 价值理由 |
|---|---|
| **Log** | LangGraph stream chunks 持久化,运维必需但可视为基础设施 |
| **Chart** | 行情数据获取,3 层 fallback 是工程稳健性,非业务差异化 |
| **Portfolio** | 个人仓位是产品形态,但 XIRR/Sharpe/Brinson 是通用算法 |
| **Scheduler** | cron + ticker 源 + 通知是通用编排,可替换 (APScheduler / Celery) |
| **Batch** | 并发执行 + stagger 防 429,纯工程 |
| **Watchlist** | CRUD 而已,可视为 Portfolio 的简化子集 |

### 4.3 Generic Subdomain (通用,优先外包/复用现成)
| Context | 价值理由 |
|---|---|
| **Settings** | YAML/JSON 配置即可,无需自研 |
| **Notifier** | 4 个 channel 都是 stdlib + 现成 webhook,**v0.7.0 应评估替换为 apprise (PyPI) 拿 60+ 渠道** |

### 4.4 子域投资策略建议
- **Core (Analysis + Sector)**: 内部全职团队维护,长迭代周期,深度测试
- **Supporting**: 内部维护但严格控制 scope,警惕 feature creep
- **Generic (Notifier)**: 评估第三方库替换 ROI

---

## 5. 聚合根 (Aggregate Roots)

按 **业务一致性边界 + 事务原子性** 梳理 **10 个核心聚合根**:

### 5.1 Analysis 聚合根 (AnalysisContext) ★ Core

```
Root Entity: AnalysisTracker (in-memory) + HistoryEntry (persisted)
├── Entities:
│   ├── AnalysisStage (12 stages: market/sentiment/news/fundamentals/policy/hot_money/ban_monitor + bull/bear + risk_judge + trader + pm)
│   ├── AgentOutput (per-stage Markdown report, 报告键: investment_debate_state / risk_debate_state / trader_investment_plan / final_trade_decision)
│   ├── LLMMessage (stream chunk, 含 tokens_in/out)
│   └── ToolCall (stream chunk, input/output)
├── Value Objects:
│   ├── Ticker (6 位 A 股代码,regex: ^(60[0-5]\d{3}|688\d{3}|000\d{3}|...|430\d{3})$)
│   ├── TradeDate (YYYY-MM-DD)
│   ├── AnalysisId (string, 格式: {ticker}_{date}_{uuid8})
│   ├── StageStatus (pending | active | done)
│   └── Signal (BUY | SELL | HOLD)
└── Invariants:
    • completed_stages.length <= 12
    • status 转换: pending → running → completed | error (单调,不可逆)
    • current_stage 与 completed_stages 互斥 (P2.22 hotfix 已修)
    • stage_reports 键必须为 report_key (与 stage_id 可能不同,见 P2.22)
    • zombie 检测: status=running && (elapsed==0 && completed_stages==[] && now-created_at>60s) → error
    • stuck 检测: status=running && elapsed>600s → error
```

### 5.2 HistoryEntry 聚合根 (AnalysisContext 跨上下文持久化层)

```
Root Entity: HistoryEntry
├── Value Objects:
│   ├── AnalysisId (string)
│   ├── Ticker, TradeDate, Signal
│   ├── StageReports (dict[str, str], key 是 report_key, value 限 500 字符)
│   └── CompletedStages (list[str])
├── Invariants:
│   • analysis_id 全局唯一 (格式: ticker_date_uuid8)
│   • status 转换: pending → running → completed | error
│   • started_at 一旦设置后单调递增
│   • finished_at >= started_at
└── ⚠️ 已知问题:
    TrackerStore 与 HistoryStore 各自生成 ID (P2.25 hotfix 已统一通过
    HistoryStore.create(analysis_id=<tracker_id>),但仍属临时修补)
```

### 5.3 Position 聚合根 (PortfolioContext)

```
Root Entity: Position
├── Entities:
│   ├── Transaction (6 actions: buy/sell/dividend/split/merge/rights)
│   └── AlertRule (7 rule_types: price_above/below/pct_change/pnl_pct/take_profit/stop_loss/trailing_stop)
├── Value Objects:
│   ├── Ticker (6 位, 同上 regex)
│   ├── PositionId (12-hex uuid)
│   ├── AccountName (string, 外键 → Account.name)
│   ├── AssetClass (stock | bond | overseas | cash | fund)
│   ├── Quantity (int, >= 0)
│   └── CostBasis (float)
└── Invariants:
    • quantity >= 0 (add_position 校验)
    • Account.name 必须先存在 (add_position 校验,FK 软约束)
    • asset_class ∈ VALID_ASSET_CLASSES
    • ticker 不可改 (update_position 拒绝 ticker 字段)
    • position_id 不可改 (update_position 拒绝)
    • delete_position 级联删除 transactions (避免悬挂流水)
    • add_transaction(sell) 校验 quantity 不为负
```

### 5.4 Schedule 聚合根 (SchedulerContext)

```
Root Entity: Schedule
├── Entities:
│   └── ScheduleRun (单次执行实例, 含 batch_id / job_ids / status / summary)
├── Value Objects:
│   ├── ScheduleId (12-hex uuid)
│   ├── CronExpression (croniter 验证)
│   ├── SourceType (PORTFOLIO | WATCHLIST | MANUAL)
│   ├── TickerSource (from PortfolioStore / WatchlistStore / 手动 list)
│   ├── NotifyChannel (log | wecom | email | desktop)
│   └── RunStatus (NEVER | OK | PARTIAL | ERROR | SKIPPED)
└── Invariants:
    • cron_expr 非空 + croniter.is_valid (validate())
    • name 非空
    • source_type=MANUAL 时 tickers 非空
    • notify_channels ⊆ [log, wecom, email, desktop]
    • last_run_status 转换: NEVER → (OK|PARTIAL|ERROR|SKIPPED)
    • 30 天前 run 自动 prune (MAX_RUN_HISTORY_DAYS)
```

### 5.5 BatchJob 聚合根 (BatchContext)

```
Root Entity: BatchJob
├── Entities:
│   └── Job (per-ticker 任务, 复用 analysis_id)
├── Value Objects:
│   ├── BatchId (格式: batch_{uuid8})
│   ├── JobId (格式: {ticker}_{date}_{uuid8})
│   ├── JobStatus (pending | running | completed | error | cancelled)
│   └── BatchStatus (派生: PENDING | RUNNING | COMPLETED | PARTIAL | FAILED | CANCELLED)
└── Invariants:
    • requests.length > 0 (create_batch 校验)
    • 每个 ticker 必须通过 TICKER_WHITELIST_RE (否则建议 reject,见债务 #5)
    • stagger_seconds >= 0 (防东财 429)
    • max_workers >= 1 (默认 5)
    • batch.batch_status 是派生属性,不持久化
    • 东财 429 自动 retry once (backoff 默认 8s)
```

### 5.6 LogTask 聚合根 (LogContext)

```
Root Entity: LogTask
├── Entities:
│   └── LogChunk (3 类型: llm | tool | agent_output)
├── Value Objects:
│   ├── TaskDirName (格式: {date}_run{NN})
│   ├── ChunkType (llm | tool | agent_output)
│   ├── Agent (7 analyst + bull/bear/judge/risk/trader/pm)
│   ├── Timestamp (float unix ts)
│   └── IsLegacy (bool, 兼容旧 TradingAgentsStrategy_logs 目录)
└── Invariants:
    • 每 task 目录必含 meta.json
    • 3 个 jsonl 文件: llm_messages / tool_calls / agent_outputs
    • chunk 类型与文件名一一对应 (_FILENAME_FROM_TYPE 反查)
    • legacy 目录可读但标记 is_legacy=True
    • TaskSummary.chunk_counts ≥ 0
```

### 5.7 SectorDigest 聚合根 (SectorContext) ★ Core

```
Root Entity: SectorDigest (frozen=True @dataclass)
├── Entities:
│   ├── SectorPick (热股策略,来自 np-ipick: rank/question/heatValue/market/code/chg)
│   ├── LimitUpStock (来自同花顺: code/name/reason/zhangfu/huanshou/chengjiaoe/ddejingliang)
│   └── ConceptPick (概念板块: name → list of limit-up stocks, count >= 2)
├── Value Objects:
│   ├── Date (YYYY-MM-DD)
│   ├── TopN (int, 1..50)
│   ├── HeatScore (float, np-ipick heatValue)
│   └── SourcesOk (dict[str, bool]: np-ipick / 10jqka / baidu)
└── Invariants:
    • concept_blocks 仅含 ≥ 2 只涨停股的板块
    • sources_ok 至少 1 个 True (否则视为整体失败)
    • 24h 内存缓存 (同一 date+top_n 命中)
    • markdown 是派生视图,与结构化字段一致性
```

### 5.8 KLineSeries 聚合根 (ChartContext)

```
Root Entity: KLineSeries
├── Entities:
│   └── KLineBar (单根: date/open/high/low/close/volume)
├── Value Objects:
│   ├── Ticker (6 位)
│   ├── DateRange (start, end)
│   ├── KLineRange (1d/1w/1m/3m/6m/1y/all, 7 档)
│   └── DataSource (mootdx | sina | push2his, fallback 顺序)
└── Invariants:
    • 三层 fallback: mootdx TCP → sina HTTP → push2his HTTP
    • 24h CSV 缓存 (~/.tradingagents/cache/kline/{ticker}_{range}.csv)
    • 实时 K 线 via SSE (push2his trends2/sse, CORS 验证)
    • 实时报价 f43/f44/f45 节流 (_em_get)
```

### 5.9 Watchlist 聚合根 (WatchlistContext)

```
Root Entity: Watchlist
├── Entities:
│   └── WatchEntry (单条自选股)
├── Value Objects:
│   ├── EntryId (12-hex uuid)
│   ├── Ticker (6 位, ^\d{6}$)
│   ├── Tag (长线 | 短线 | 观察 | T0 | T1 | T2)
│   └── Note (string)
└── Invariants:
    • ticker 必须 6 位数字 (add 校验)
    • tag ∈ VALID_TAGS (避免自由文本污染)
    • 持久化 ~/.tradingagents/watchlist.json (单文件,非目录)
    • 排序: (ticker asc, created_at asc)
```

### 5.10 NotificationMessage 聚合根 (NotifierContext)

```
Root Entity: NotificationMessage
├── Value Objects:
│   ├── Channel (wecom | email | desktop | log)
│   ├── Recipient (wecom: webhook URL / email: SMTP to / desktop: 系统通知 / log: stdout)
│   ├── Priority (v0.7.0 未实现,预留)
│   └── TemplateVars (schedule_name, status, started_at, duration, summary, batch_id, run_id, detail_link)
└── Invariants:
    • 每 channel 失败独立捕获,不互相影响
    • 单 channel 失败 log warning,不 raise
    • YAML 配置缺失 → 默认仅启用 log channel
    • SMTP 必须 host+user+password+to 齐全
    • WeCom 必须 webhook URL 齐全
    • Desktop 仅 Linux (其他平台 raise NotImplementedError)
```

---

## 6. 领域事件 (Domain Events)

按 **过去时态命名** 列举系统 **应实现但当前未发布** 的核心事件:

| # | 事件名 | 触发条件 | 携带数据 | 当前实现状态 |
|---|---|---|---|---|
| 1 | `AnalysisStarted` | `start_analysis` 调用,TrackerStore.create() | `analysis_id, ticker, trade_date, started_at` | ❌ 未发布 |
| 2 | `AnalysisStageCompleted` | `AnalysisTracker.mark_stage_done()` | `analysis_id, stage_id, report_key, elapsed_per_stage` | ❌ 未发布 |
| 3 | `AnalysisCompleted` | `AnalysisTracker.mark_complete()` | `analysis_id, signal, total_elapsed, completed_stages` | ❌ 未发布 |
| 4 | `AnalysisFailed` | `AnalysisTracker.mark_error()` | `analysis_id, error, elapsed, stage_failed` | ❌ 未发布 |
| 5 | `AnalysisMarkedAsZombie` | startup 时 `cleanup_zombies` 检测 | `analysis_id, reason` | ❌ 未发布 |
| 6 | `AnalysisMarkedAsStuck` | 同上 (elapsed > 600s) | `analysis_id, elapsed, last_stage` | ❌ 未发布 |
| 7 | `PortfolioPositionCreated` | `PortfolioStore.add_position()` | `position_id, ticker, account, quantity, cost_basis` | ❌ 未发布 |
| 8 | `PortfolioTransactionRecorded` | `PortfolioStore.add_transaction()` | `tx_id, position_id, action, price, quantity` | ❌ 未发布 |
| 9 | `PortfolioAlertTriggered` | `portfolio_alerts` 规则匹配 | `rule_id, ticker, rule_type, current_price, threshold` | ❌ 未发布 |
| 10 | `BatchJobSubmitted` | `JobQueue.submit()` | `batch_id, job_ids, total_tickers` | ❌ 未发布 |
| 11 | `BatchJobCompleted` | 单 job status=completed | `batch_id, job_id, ticker, signal, elapsed` | ❌ 未发布 |
| 12 | `BatchJobFailed` | 单 job status=error | `batch_id, job_id, ticker, error, retry_count` | ❌ 未发布 |
| 13 | `ScheduleTriggered` | cron 到点 / `run_now` | `schedule_id, run_id, triggered_at, manual` | ❌ 未发布 |
| 14 | `ScheduleRunCompleted` | `_run_schedule` 返回 | `run_id, schedule_id, status, batch_id, duration` | ❌ 未发布 |
| 15 | `LogChunkAppended` | `LogWriter.append_chunk()` | `task_dir, chunk_type, agent, ts` | ❌ 未发布 |
| 16 | `SectorDigestRefreshed` | `_fetch_digest` cache miss | `date, top_n, sources_ok, hash` | ❌ 未发布 |
| 17 | `KlineBarUpdated` | push2his SSE 实时推送 | `ticker, ohlcv, ts` | ❌ 未发布 |
| 18 | `NotifierChannelFailed` | 单 channel send 抛异常 | `channel, schedule_id, run_id, error` | ❌ 未发布 |

### 6.1 缺失事件的影响 (因果链)
- ❌ `ScheduleRunCompleted` 未发布 → Notifier 只能通过 Scheduler 内部 direct call 触发,无法被其他 context (e.g. Portfolio 同步最新 signal) 订阅
- ❌ `BatchJobCompleted` 未发布 → Portfolio 无法在每个 ticker 分析完成后自动更新 Bull/Bear 联动 banner
- ❌ `PortfolioAlertTriggered` 未发布 → Scheduler 无法用 alert 事件触发立即分析

---

## 7. Repository 接口 vs 实现

按 **接口分离原则 (DIP)** 列出 domain layer 仓储接口与 infrastructure 实现:

### 7.1 Domain Layer Interfaces (应新增,目前缺失)

| 接口 | 核心方法 | 当前状态 |
|---|---|---|
| `IAnalysisRepository` | `save(tracker)`, `get(id)`, `list_recent(ticker, limit)`, `mark_stage_done(...)`, `mark_complete(...)`, `mark_error(...)`, `cleanup_zombies()` | ❌ 缺失,目前 `HistoryStore` 直接被 import |
| `IHistoryRepository` | `create(...)`, `get(id)`, `list_all(filters)`, `find_by_ticker_date(...)`, `delete(id)` | ❌ 缺失,目前 `HistoryStore` 直接被 import |
| `ILogRepository` | `list_tasks(ticker)`, `load_chunks(task_dir, type)`, `append_chunk(task_id, chunk)` | ❌ 缺失,目前 `LogStore` + `LogWriter` 直接被 import |
| `IPortfolioRepository` | `positions: CRUD`, `transactions: CRUD`, `alerts: CRUD`, `accounts: CRUD`, `audit_log: append` | ❌ 缺失,目前 `PortfolioStore` 直接被 import |
| `IScheduleRepository` | `schedules: CRUD`, `runs: append/list/prune`, `ticker_source: load` | ❌ 缺失,目前 `Scheduler` 直接被 import |
| `IBatchRepository` | `create_batch`, `submit`, `get_batch`, `get_job`, `cancel_job`, `retry`, `wait_for_batch` | ❌ 缺失,目前 `JobQueue` 直接被 import |
| `ISectorRepository` | `fetch_digest(date, top_n)`, `cached_digest`, `invalidate_cache` | ❌ 缺失,目前 `_fetch_digest` 内联在 `backend/api/sector.py` |
| `IChartRepository` | `get_stock_data(ticker, range)`, `get_realtime_quote(ticker)`, `clear_cache` | ❌ 缺失,目前是 `tradingagents.dataflows.a_stock.get_stock_data` |
| `IWatchlistRepository` | `add`, `remove`, `list`, `count`, `clear` | ❌ 缺失,目前 `WatchlistStore` 直接被 import |

### 7.2 Infrastructure Layer Implementations (现有)

| 实现类 | 持久化策略 | 线程安全 | 路径 |
|---|---|---|---|
| `HistoryStore` (singleton) | JSON 文件,每个 entry 一个文件 | 双检锁 + Lock | `~/.tradingagents/logs/history/{analysis_id}.json` |
| `TrackerStore` (singleton) | 纯内存 `dict[analysis_id, AnalysisTracker]` | 双检锁 + Lock | — (in-memory,重启丢) |
| `LogStore` + `LogWriter` | JSONL 追加 + fcntl 文件锁 | 内置锁 | `~/.tradingagents/logs/{ticker}/{date}_run{NN}/{type}.jsonl` |
| `PortfolioStore` (singleton) | JSON 文件,4 个实体 + audit.log | RLock (重入友好) | `~/.tradingagents/portfolio/{positions,transactions,alerts,accounts}.json + audit.log` |
| `WatchlistStore` (singleton) | JSON 文件,单文件 | RLock | `~/.tradingagents/watchlist.json` |
| `Scheduler` (singleton) | JSON + 后台 daemon thread | RLock | `~/.tradingagents/schedules/schedules.json + runs/{date}.jsonl` |
| `JobQueue` (singleton) | 纯内存 + HistoryStore (复用) | Lock | — (in-memory,重启丢,仅 history 持久化) |
| `Notifier` (singleton) | 无持久化 + YAML 配置 + Jinja2 模板 | Lock | `~/.tradingagents/schedules/channels.yaml` |
| `SectorDigest` (frozen dataclass + module-level cache) | 24h 内存缓存 | 单进程 dict | `backend/api/sector.py:_DIGEST_CACHE` |
| `mootdx/sina/push2his` 三层 fallback (无独立类) | 24h CSV 缓存 | 无显式锁 | `~/.tradingagents/cache/kline/{ticker}_{range}.csv` |

### 7.3 反模式: 直接 import 实现类
当前 Backend 代码大量 `from backend.core.history_store import get_history_store`,**违反 DIP**。Domain layer 应只依赖接口,具体实现通过 DI 容器 (FastAPI `Depends` 或 `dependency-injector`) 注入。

---

## 8. 架构债务 (按严重性排序)

### 8.1 🔴 严重 (Critical — 阻塞正确性)

#### #1 TrackerStore vs HistoryStore ID 不一致 (Domain Identity Integrity)
- **位置**: `backend/core/tracker.py:188` + `backend/core/history_store.py:141`
- **症状**: POST /api/analyze 返回 ID 来自 TrackerStore (`uuid.uuid4().hex[:8]`),但如果走不同代码路径,history.json 文件名 ID 又来自 HistoryStore 独立生成。后果:`/progress` 按 POST 返回的 ID 查不到对应的 history.json → 404。Cancel endpoint 用 ticker+date 兜底查找,progress 之前没兜底。
- **修复**: P2.25 hotfix (commit `5257c0d` 之前) 已统一通过 `HistoryStore.create(analysis_id=<tracker_id>)`,但仍属**事后补丁**,应在 **领域层引入 `AnalysisId` 值对象** + `IAnalysisIdGenerator` 端口,从源头确保 ID 全局一致
- **风险**: v0.7.0 后,任何新增 entry 创建路径都必须记得调用 P2.25 接口,否则回退 bug

#### #2 多 in-memory 单例 + 重启丢数据
- **位置**: `TrackerStore` (`_trackers: dict`), `JobQueue` (`_batches`, `_jobs`), `Scheduler._schedules` (虽然有 JSON 持久化但 runs 只在 `_append_run` 时落盘)
- **症状**:
  - TrackerStore: uvicorn 重启后,正在运行的 tracker 全部消失 → 历史记录丢失 (P2.14 zombie 检测就是为这种情况打补丁)
  - JobQueue: 同上,批量任务重启后从内存蒸发,只剩 history.json
  - Scheduler._schedules: 持久化正常,但 `_executor.submit` 的 Future 重启后无引用
- **影响**: 生产稳定性,任何 SIGKILL 都可能造成数据丢失
- **修复方向**: TrackerStore/JobQueue 改为 **Write-Ahead Log (WAL)** 或迁移到 SQLite/RocksDB;短期方案是重启时从 HistoryStore 反向重建 in-memory tracker

#### #3 Repository 接口未抽象 (DIP 违反)
- **位置**: 所有 backend/api/*.py 文件
- **症状**: `from backend.core.history_store import get_history_store` 等直接 import 具体类
- **后果**: 无法 mock 测试业务逻辑,无法替换持久化后端 (e.g. 切到 SQLite 时必须改所有 import)
- **修复**: 引入 `backend/domain/ports/` 目录,定义 ABC 接口 + Protocol;在 `backend/api/` 用 FastAPI `Depends` 注入

### 8.2 🟡 中等 (Important — 影响可维护性)

#### #4 领域事件未实现 (12+ 事件全部缺失)
- **位置**: 全部 backend/core/*.py
- **症状**: 见 §6 表格, 18 个事件全部状态 `❌ 未发布`
- **因果影响**:
  - `ScheduleRunCompleted` 未发布 → Notifier 只能由 Scheduler direct call,无法被 Portfolio 等其他 context 订阅
  - `BatchJobCompleted` 未发布 → Portfolio 自动同步 Bull/Bear 联动无法实现
  - `PortfolioAlertTriggered` 未发布 → 无法用 alert 事件驱动立即分析
- **修复**: 引入 `backend/domain/events/` + `EventBus` (同步 in-process 即可,无需消息队列),最小成本实现 Observer 模式

#### #5 聚合根缺少 invariant 校验
- **位置**:
  - `AnalysisTracker.mark_complete()` 无 final_state 非空校验 (空 dict 也允许 mark_complete)
  - `JobQueue.create_batch()` 无 ticker 白名单校验 (直接信任输入,只有 runtime 才报错)
  - `PortfolioStore.update_position()` 允许 quantity=负数 (在 add_transaction sell 时才校验)
- **症状**: 边界 case 通过校验,但运行时崩
- **修复**: 在 `mark_complete`/`create_batch`/`update_position` 入口加防御性 assert + 测试覆盖

#### #6 Context 之间没有明确 ACL
- **位置**:
  - Analysis → Log: `AnalysisTracker.mark_stage_done()` 直接调 `get_history_store().mark_stage_done()` (内部同步)
  - Batch → Analysis: `Job._run_pipeline()` 直接 `from web.runner import run_one_analysis`
  - Scheduler → Notifier: `_notify()` 内联调 `Notifier.send()`
- **后果**: 上下游耦合紧,任一改动要 ripple 整个调用链;单元测试必须真实启动下游,失去 isolated test 能力
- **修复**: 在 infrastructure 层加 Adapter (e.g. `AnalysisRunnerAdapter` 包装 `run_one_analysis`),让 domain 只依赖接口

### 8.3 🟢 轻微 (Nice-to-have — 不阻塞但应规划)

#### #7 YAML 解析手写 (NotImplemented Yet)
- **位置**: `backend/core/notifier.py:_parse_yaml`
- **症状**: Notifier 为避免 PyYAML 依赖手写 mini YAML parser,只支持 2 级嵌套 + 列表。复杂配置直接静默失败。
- **建议**: 评估 PyYAML 引入 ROI (Pydantic v2 已自带 YAML 解析,且能 schema validate)

#### #8 Notifier 无重试/幂等
- **位置**: `backend/core/notifier.py`
- **症状**: WeCom webhook 4xx/5xx 直接 raise,Email SMTP 失败直接 raise,**不重试**
- **CLAUDE.md 明确**: 「不做重试 / 退避 (v0.7.0 加)」
- **建议**: v0.7.0 应实现 exponential backoff + dead-letter queue (e.g. 失败的 message 落 `~/.tradingagents/schedules/dead_letter/`)

#### #9 多个 in-process 缓存缺乏 invalidation hook
- **位置**: `backend/api/sector.py:_DIGEST_CACHE`, `_em_get` 的 CSV 缓存
- **症状**: 用户手动修改底层 JSON 文件后,缓存不刷新;Sector digest 24h 硬 TTL,盘中刷新延迟
- **建议**: 加 `invalidate()` 方法 + 文件 mtime 检测

---

## 9. 重构建议 (按 ROI 排序)

### 9.1 短期 (1-2 周, 低风险高 ROI)

#### 建议 #1: 提取 9 个 Repository 协议 (Protocol) — ROI ★★★★★
- **工作**: 在 `backend/domain/ports/` 新建 9 个 `Protocol` 类 (Python 3.11 原生,无需额外依赖),定义 §7.1 方法签名
- **实施**:
  1. 不改实现类,只把 `HistoryStore`/`PortfolioStore` 等 mark 为 `Protocol` 实现
  2. API 层改用 `from backend.domain.ports import IHistoryRepository` + FastAPI `Depends`
  3. 测试改用 `InMemoryHistoryStore` 替代 monkeypatch
- **收益**: 解耦持久层 + 单测提速 3-5x (不需要 tmp_path)
- **风险**: 0 (向后兼容)
- **不影响生产代码**: 纯新增文件,不改现有调用

#### 建议 #2: 引入领域事件总线 (EventBus) — ROI ★★★★☆
- **工作**: 在 `backend/domain/events/` 新建 `EventBus` 单例 + 18 个 dataclass 事件
- **实施**:
  1. `EventBus.publish(event)` 同步 in-process 调用 subscribers
  2. 各 store 的 mark_* 方法末尾加 `event_bus.publish(...)`
  3. Scheduler → Notifier 改为订阅 `ScheduleRunCompleted` 事件
- **收益**: 解耦 Scheduler ↔ Notifier,开放 Portfolio 自动响应能力
- **风险**: 极低 (新增 module,现有 direct call 保留作为 fallback)

#### 建议 #3: TrackerStore/JobQueue 持久化 — ROI ★★★☆☆
- **工作**: 复用现有 HistoryStore 的 JSON 文件模式,把 in-memory dict 改为每次 `__setitem__` 落盘
- **实施**:
  1. `TrackerStore.create/update` 同步追加到 `~/.tradingagents/trackers/{id}.json`
  2. `__init__` 启动时扫描目录重建 dict
  3. 加 TTL 或启动时主动清理僵尸
- **收益**: 重启不再丢数据,消除 P2.14/P2.21 zombie 场景
- **风险**: 中 (高频写可能影响性能,需 benchmark;考虑 batch fsync)

### 9.2 中期 (1-2 月, 中等 ROI)

#### 建议 #4: AnalysisId 值对象统一 — ROI ★★★★☆
- **工作**: 新增 `AnalysisId` value object,封装 `{ticker}_{date}_{uuid8}` 格式 + parse/validate 逻辑
- **实施**:
  1. 所有 ID 生成走 `AnalysisId.generate(ticker, date)` 工厂方法
  2. 替换 `_new_id() / uuid.uuid4().hex[:8]` 散落
  3. 加 `AnalysisId.from_string(s)` 解析 + 校验
- **收益**: 根除 ID 一致性问题 (§8.1 #1)
- **风险**: 中 (需修改 7+ 处 ID 生成点)

#### 建议 #5: ACL 适配层 — ROI ★★★☆☆
- **工作**: 引入 `AnalysisRunner` 抽象 + `WebRunnerAdapter` 实现
- **实施**:
  1. `Job._run_pipeline` 不再 `from web.runner import run_one_analysis`
  2. 改为 `runner: AnalysisRunner = WebRunnerAdapter()` 注入
  3. Scheduler 复用同一端口
- **收益**: Analysis / Batch / Scheduler 三 context 完全解耦
- **风险**: 中 (需新增 Protocol + Adapter)

### 9.3 长期 (季度级, 高 ROI 但投入大)

#### 建议 #6: 持久化层迁移到 SQLite — ROI ★★★★☆
- **动机**: v0.7.0+ TrackerStore/JobQueue in-memory 痛点 (§8.1 #2) 累积,JSON 文件方案 I/O 开销已逼近临界点
- **方案**:
  - 用 SQLite WAL 模式,保留现有 API 签名
  - 单文件 `~/.tradingagents/db.sqlite` (~50MB 容纳 100K 分析)
  - WAL checkpoint 由后台 thread 每 60s 触发
- **收益**:
  - 事务 ACID 保障
  - 跨进程查询 (Streamlit + FastAPI 同时跑)
  - 减少 zombie 检测逻辑 (DB 一致性保证)
- **风险**: 高 (持久化层重写,需大量回归测试)
- **建议阶段**: v0.8.0 起,Phase 3 范围

#### 建议 #7: Notifier 替换为 apprise — ROI ★★★☆☆
- **动机**: 自研 4 channel 通用性不足 (Slack/Discord/Telegram 等缺失)
- **方案**: `pip install apprise` 替换 `Notifier` 为薄 wrapper
- **收益**: 60+ 渠道零成本,简化测试 (apprise 自带 Mock)
- **风险**: 低 (API 兼容设计)

#### 建议 #8: Sector digest 实时化 (Phase 3+) — ROI ★★★★☆
- **动机**: 24h cache 对盘中场景不友好
- **方案**:
  - 引入 `SectorRefreshScheduler` 监听东财 np-ipick 增量接口
  - 用 `KlineBarUpdated` 类似的 SSE 推送
  - React 端实时刷新 heatmap
- **风险**: 高 (数据源稳定性需调研)

---

## 附录 A: 模块清单 (按 Bounded Context 分组)

| Context | 模块 | LOC | 关键类 |
|---|---|---|---|
| Analysis | `backend/core/tracker.py` | 216 | `AnalysisTracker`, `TrackerStore` |
| Analysis | `backend/core/history_store.py` | 379 | `HistoryEntry`, `HistoryStore` |
| Analysis | `backend/core/runner.py` | 273 | `run_one_analysis` |
| Log | `backend/core/log_store.py` | 458 | `LogStore`, `LogWriter`, `TaskSummary`, `LogChunk` |
| Chart | `tradingagents/dataflows/a_stock.py` (subset) | ~200 | `get_stock_data` + 3-fallback |
| Sector | `tradingagents/dataflows/a_stock.py` (subset) | ~250 | `SectorRotationDigest`, `get_sector_rotation_digest` |
| Sector | `backend/api/sector.py` | 311 | 5 GET endpoints |
| Portfolio | `backend/core/portfolio_store.py` | 923 | `Position`, `Transaction`, `AlertRule`, `Account`, `PortfolioStore` |
| Portfolio | `backend/core/portfolio_calc.py` | 743 | XIRR/Sharpe/MaxDD/Brinson |
| Portfolio | `backend/core/portfolio_alerts.py` | 175 | 7 rule evaluators |
| Portfolio | `backend/core/portfolio_import.py` | 494 | 4 CSV format parsers |
| Scheduler | `backend/core/scheduler.py` | 889 | `Schedule`, `ScheduleRun`, `Scheduler` |
| Batch | `backend/core/job_queue.py` | 423 | `Job`, `BatchJob`, `JobQueue` |
| Notifier | `backend/core/notifier.py` | 396 | `Notifier`, `ChannelConfig`, `Channel` enum |
| Watchlist | `backend/core/watchlist.py` | 204 | `WatchEntry`, `WatchlistStore` |

---

## 附录 B: 跨 Context 协作关键路径

### B.1 单笔分析流 (Analysis 主导)
```
POST /api/analyze
  → start_analysis (backend.core)
  → TrackerStore.create() ──────────┐
                                    ├─→ HistoryStore.create() (P2.25 共享 ID)
                                    └─→ AnalysisTracker (in-memory)
  → AnalysisTracker 同步被后台 thread 持有
    → graph.stream() loop
      → 每 chunk: LogWriter.append_chunk() (Log Context)
      → 每 stage 完成: AnalysisTracker.mark_stage_done()
                    └→ HistoryStore.mark_stage_done()
  → finish: AnalysisTracker.mark_complete()
           └→ HistoryStore.mark_complete()
  → ❌ 无事件发布
```

### B.2 批量分析流 (Batch 主导)
```
POST /api/batch
  → JobQueue.create_batch({ticker, date}[])
  → JobQueue.submit(batch_id, jobs, configs)
    → stagger 1.5s 防东财 429
    → executor.submit(_run_one, ...) × N
      → Job._run_pipeline() → web.runner.run_one_analysis() (直接 import, 无 ACL)
  → ❌ 无 BatchJobCompleted 事件
```

### B.3 定时分析流 (Scheduler 主导)
```
Scheduler daemon thread (60s tick)
  → _tick() 判定 cron 到点
  → _dispatch(sched, now)
    → executor.submit(_run_schedule, sched, False)
      → _load_tickers_for_source (Portfolio | Watchlist | Manual)
      → JobQueue.create_batch + submit (复用 Batch Context)
      → wait_for_batch (1800s timeout)
      → _append_run (runs/YYYY-MM-DD.jsonl)
      → ❌ _notify(sched, run) — direct call (应改为事件订阅)
        → Notifier.send(channels, ...)
```

---

## 附录 C: 验证清单

- [x] 写了 `docs/DDD_ANALYSIS.md` 文件 (本文档)
- [x] 10 个 bounded contexts 全部识别 + 上下游标注
- [x] 10 个聚合根完整梳理 (Root + Entities + Value Objects + Invariants)
- [x] 18 个领域事件列举 + 当前实现状态
- [x] 9 个 Repository 接口 vs 10 个实现类映射
- [x] 9 个架构债务按严重性排序 (🔴×3 / 🟡×3 / 🟢×3)
- [x] 8 条重构建议按 ROI 排序 (短/中/长期)
- [x] 3 个 Context Map (ASCII + 关系表 + ACL 缺失)
- [x] Subdomain 分类 (Core / Supporting / Generic)
- [x] **0 改代码 / 0 commit / 0 改 pytest / pyproject.toml / spec**

---

*文档结束 — 如需扩展 (e.g. 详细 ADR / Event Storming / Bounded Context Canvas), 可在 v0.7.0 Phase 3 单独发起*