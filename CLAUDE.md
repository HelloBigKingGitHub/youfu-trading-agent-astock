# Youfu-Trading-Agent-Astock

## 项目概述
基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)（65K Stars）的 A 股深度特化 fork。多 Agent 投研框架，7 个 Analyst 角色通过 Bull/Bear 辩论 + 三方风险辩论生成投资报告。

- **仓库**: https://github.com/HelloBigKingGitHub/youfu-trading-agent-astock
- **协议**: Apache 2.0
- **Python**: >=3.10
- **当前版本**: 0.5.0

## 架构

### 数据层（v0.2.5 全部直连 HTTP，零第三方数据库依赖）
| 来源 | 协议 | 数据 |
|------|------|------|
| mootdx | TCP 7709 | OHLCV K线、财务快照、F10 文本 |
| 腾讯财经 | HTTP (qt.gtimg.cn) | PE/PB/市值/换手率 |
| 东方财富 datacenter | HTTP (datacenter-web) | 龙虎榜、限售解禁、板块行情 |
| 东方财富 push2/push2his | HTTP (push2.eastmoney) | 实时行情、个股信息、板块列表、资金流(分钟+日级) |
| 东方财富 np-weblist | HTTP | 滚动新闻 |
| 新浪财经 | HTTP (money.finance.sina) | K线历史、财报三表 |
| 同花顺 10jqka | HTTP | EPS 一致预期、热股题材 |
| 财联社 cls.cn | HTTP | 全球财经快讯 |
| 百度股市通 | HTTP (gushitong.baidu) | 概念板块归属（资金流已迁移至东财push2） |
| 东方财富 np-ipick | HTTP | 选股热度排名（板块轮动日报用） |

### Agent 角色（7 个 + 板块轮动日报 + 个人仓位模块）
原版 4 个（市场/情绪/新闻/基本面）+ A 股特化 3 个（政策分析师/游资追踪/解禁监控）+ **v0.2.12 新增「板块轮动日报」**（侧边栏按钮直接调用 `get_sector_rotation_digest`，不走 LangGraph 也不消耗 LLM token）：东财 np-ipick 选股热度 + 同花顺涨停归因 + 百度 PAE 概念反查 → 4 段式 Markdown。**v0.5.0 新增「个人仓位跟踪」**（侧边栏第 8 按钮）：手工录入持仓 + 交易流水，与 Bull/Bear 信号联动，按行业/板块/资产类别归因，配套 XIRR / Sharpe / 最大回撤 / Brinson 业绩归因。

### 关键路径
- `tradingagents/dataflows/a_stock.py` — A 股数据 vendor，所有数据获取入口
- `tradingagents/dataflows/utils.py` — `safe_ticker_component` 路径安全校验 + 中文 ticker 自动解析
- `tradingagents/agents/` — 7 个 Analyst + Bull/Bear 辩论逻辑
- `web/app.py` — Streamlit Web UI 入口
- `web/components/sector_panel.py` — v0.2.13 板块轮动 UI（独立组件，依赖 `SectorRotationDigest`）
- `backend/core/portfolio_store.py` — v0.5.0 个人仓位持久化（positions/transactions/alerts JSON + audit.log，单例 + RLock）
- `backend/core/portfolio_calc.py` — v0.5.0 仓位指标计算（XIRR / Sharpe / MaxDD / Brinson / 板块归因）
- `web/components/portfolio_panel.py` — v0.5.0 仓位面板入口（6 tabs + Bull/Bear 联动 banner）
- `cli/` — CLI 入口

### 中文股票名解析链路
用户/LLM 输入 → `safe_ticker_component` 检测中文 → `resolve_ticker()` → `_build_name_code_map()`（mootdx 全市场映射，缓存）→ 返回 6 位代码

## 日志监控模块 (v0.3.0)

按分析任务持久化全部 LangGraph stream chunks，实时 + 历史查询。

### 数据流
```
~/.tradingagents/logs/{ticker}/{date}_run{NN}/
├── meta.json              # task metadata
├── llm_messages.jsonl     # stream chunk type=llm
├── tool_calls.jsonl       # stream chunk type=tool
└── agent_outputs.jsonl    # stream chunk type=agent_output
```

兼容旧结构 `~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json`（LogStore 降级读，标记 `is_legacy=True`）。

### 后端模块
- `backend/core/log_store.py` — `LogStore`（读）+ `LogWriter`（写）+ `TaskSummary` + `LogChunk` dataclass + `get_log_store()` 单例
- `web/runner.py` — `_run()` stream 循环里调 `LogWriter.append_chunk()`，跑完 `finalize()`
- `_classify_chunk()` — 把 LangGraph state snapshot 分类成 9 个 agent_output + 3 个 llm chunks（debate judge / risk judge / trader）

### UI 入口
侧边栏 6 按钮（第 5 个）：`📋 日志` → 切到 `render_logs_panel()`。布局 GitHub PR 风格：1:3 双列（左 ticker 列表，右 task 列表 + 展开 chunks）。

### CLI
```bash
python -m cli.list_logs           # 所有 ticker
python -m cli.list_logs 600595    # 单 ticker
```

### 关键文件
| 文件 | 行数 | 作用 |
|---|---|---|
| `backend/core/log_store.py` | 458 | LogStore + LogWriter |
| `web/runner.py` | 263 | stream 循环 hook |
| `web/components/logs_panel.py` | 178 | UI 主组件 |
| `cli/list_logs.py` | 45 | CLI |
| `web/styles/elements.css` | +88 行 | 13 个 `.bb-log-*` 类 |
| `tests/test_log_store.py` | 205 | 16 测试 |
| `tests/test_log_streaming.py` | 149 | 7 测试 |
| `tests/test_logs_panel.py` | 103 | 6 测试 |
| `tests/test_cli_list_logs.py` | 63 | 3 测试 |
| **总计** | **~1652** | — |

### 测试
- 31 新测试（LogStore 16 + Runner 7 + UI 6 + CLI 3）全部通过
- 263 已有测试无回归
- 所有测试用 `monkeypatch._LOGS_ROOT = tmp_path` 避免污染真实 `~/.tradingagents/`

## 股价走势图面板 (v0.4.0)

A 股股价 K 线图，实时更新 + 历史查询。

### 数据流
- **3-fallback 历史 K 线** (`get_stock_data`)：mootdx TCP → sina HTTP → push2his HTTP
- **实时报价**：东财 push2 f43/f44/f45（走 `_em_get` 节流）
- **实时 K 线**：浏览器直连 push2his `trends2/sse` SSE（D2 集成，CORS 验证通过）

### 后端模块
- `tradingagents/dataflows/a_stock.py` — `_push2his_kline_fallback` 新增（push2his HTTP），`get_stock_data` 加第 3 层 fallback
- `web/components/chart_panel.py` — `render_chart_panel` + 6 helpers
- `~/.tradingagents/cache/kline/{ticker}_{range}.csv` — 24h CSV cache

### UI 入口
侧边栏 7 按钮（第 6 个）：`📈 走势图` → 切到 `render_chart_panel()`。顶部 ticker input + 7 时间范围（1d/1w/1m/3m/6m/1y/all），实时报价 banner，K 线 + MA5/10/20 + 成交量 副图（Lightweight Charts CDN v4.1.3）。

### 关键文件
| 文件 | 行数 | 作用 |
|---|---|---|
| `web/components/chart_panel.py` | 313 | 主组件（含 SSE realtime） |
| `tradingagents/dataflows/a_stock.py` | +88 | push2his fallback |
| `tests/test_push2his_kline.py` | 145 | 6 测试 |
| `tests/test_chart_panel.py` | 236 | 7 测试 |
| **总计** | **~782** | - |

### 测试
- 13 新测试（push2his 6 + chart_panel 7）全部通过
- 312 已有测试无回归
- D2 SSE 集成：CORS 验证（`Access-Control-Allow-Origin: http://localhost:8501`）

## 个人仓位模块 (v0.5.0)

A 股个人仓位跟踪 + 业绩归因，与 Bull/Bear 信号联动。手工录入持仓 / 流水 → 实时计算盈亏 / 集中度 / 板块归因 / XIRR / Sharpe / 最大回撤 / Brinson 业绩归因。预警支持 7 种规则（price_above/below/pct_change/pnl_pct/take_profit/stop_loss/trailing_stop），导入支持 4 种 CSV 格式（东财 / 同花顺 / 雪球 / generic）。

### 数据流
```
用户录入 / CSV 导入
    ↓
backend/core/portfolio_store (单例 + RLock，原子写 JSON)
    ↓
backend/core/portfolio_calc (XIRR/Sharpe/MaxDD/Brinson/板块归因)
    ↓
web/components/portfolio_panel (6 tabs: 总览/流水/配置/预警/导入导出/收益风险)
```

### 后端模块
- `backend/core/portfolio_store.py` — 单例 + RLock 持久化（positions.json / transactions.json / alerts.json / audit.log）
- `backend/core/portfolio_calc.py` — `compute_position_metrics` / `compute_portfolio_summary` / `group_by_sector` / `compute_xirr` / `compute_sharpe` / `compute_max_drawdown` / `compute_brinson_attribution`
- `backend/core/portfolio_alerts.py` — 7 种规则评估器 + 300s anti-repeat 去重
- `backend/core/portfolio_import.py` — 4 种 CSV 格式检测/解析/预览/导入/导出（UTF-8 BOM Excel 友好）

### UI 入口
侧边栏 8 按钮（第 7 个）：`💼 我的仓位` → 切到 `render_portfolio_panel()`。布局 6 tabs：📊 总览 / 📜 流水 / 🎯 配置 / 🔔 预警 / 📥 导入/导出 / 📈 收益风险。Bull/Bear 信号变化触发顶部 banner（Phase 4 启用 MVP stub，目前显示空）。

### 关键文件
| 文件 | 行数 | 作用 |
|---|---|---|
| `backend/core/portfolio_store.py` | 287 | 单例 + RLock + JSON 原子写 + audit |
| `backend/core/portfolio_calc.py` | 305+ | 业绩归因全套计算 |
| `backend/core/portfolio_alerts.py` | 145 | 7 种规则 + 300s 去重 |
| `backend/core/portfolio_import.py` | 430 | 4 种 CSV 格式 + UTF-8 BOM |
| `web/components/portfolio_panel.py` | 172 | 主入口 6 tabs dispatcher |
| `web/components/portfolio_dialogs.py` | ~300 | 4 个对话框 (新增/编辑/交易/预警) |
| `web/components/portfolio_overview.py` | ~200 | 总览 tab |
| `web/components/portfolio_transactions.py` | ~150 | 流水 tab |
| `web/components/portfolio_allocation.py` | ~180 | 配置 tab |
| `web/components/portfolio_alerts_view.py` | ~150 | 预警 tab |
| `web/components/portfolio_import_view.py` | ~200 | 导入导出 tab |
| `web/components/portfolio_risk.py` | ~180 | 收益风险 tab |
| `tests/test_portfolio_store.py` | 90+ | 单例 + 校验 + 过滤 |
| `tests/test_portfolio_calc.py` | 90+ | 业绩归因全套 |
| `tests/test_portfolio_alerts.py` | 35+ | 7 种规则 + 去重 |
| `tests/test_portfolio_import.py` | 50+ | 4 种 CSV 格式 |
| `tests/test_portfolio_panel.py` | 90+ | Streamlit UI |
| **总计** | **~3000** | - |

### 测试
- 304 portfolio 测试全部通过
- 96% 覆盖率（portfolio_store 98%、portfolio_calc 95%、portfolio_alerts 97%、portfolio_import 96%）
- 610 全量测试通过（pre-existing chart_panel 环境失败未计入）
- 所有测试用 `monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)` 隔离真实 `~/.tradingagents/portfolio/`

## 已知问题与注意事项

### 依赖冲突（v0.2.6 已缓解）
mootdx 锁死 httpx==0.25.2，与 langchain-google-genai 的 httpx>=0.28.1 冲突。v0.2.6 将 google-genai 移至可选依赖 `[google]`，`pip install -e .` 不再冲突。需要 Google 模型时 `pip install -e ".[google]"`。

### akshare 已移除（v0.2.5）
v0.2.5 起完全移除 akshare 依赖，所有数据通过直连 HTTP API 获取。

### 百度 PAE 资金流接口已下线（v0.2.7 已修复）
`fundsortlist` 和 `fundflow` 两个接口返回空（2026-05-19 确认）。v0.2.7 已替换为东财 push2 资金流 API。同时修复了 `RPT_ORGANIZATION_BUSSINESS`（改用席位筛选机构）和东财全球资讯 `req_trace` 参数。

### 东财接口防封限流（v0.2.11 新增，移植自 a-stock-data v3.2）
`a_stock.py` 里所有指向 `eastmoney.com` 的请求（push2 / push2his / datacenter-web / search-api / np-weblist / np-ipick 共 8 个调用点）统一走节流入口 `_em_get()`：模块级时间戳串行限流（默认间隔 `EM_MIN_INTERVAL=1.0s`，可用同名环境变量覆盖）+ 0.1~0.5s 随机抖动 + 复用 `requests.Session`（Keep-Alive）+ 默认 UA。多 Agent 跑批量分析不再触发东财临时封 IP。**仅东财限流**——mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等非东财源不受影响。批量场景可设 `EM_MIN_INTERVAL=1.5~2` 进一步降速。新增东财端点时务必走 `_em_get` 而非裸 `requests.get`。

### 板块轮动日报 v0.2.12 局限
「板块轮动日报」采用「涨停股→百度 PAE 反查→概念板块聚类」路径（不是「行业→成分股」），因为部分网络环境 push2/push2his 不稳定（2026-06 验证：5 次本地请求 0 次成功）。本变体绕开 push2 走 np-ipick 选股热度 + THS 涨停归因 + 百度 PAE 反查，单次 15-25s 即可生成 4 段式 Markdown；属于 push2 不可用环境的兜底方案。如 push2 恢复，v0.3 可叠加「行业涨幅 Top N + 资金净流入 Top N」段落。

### 模型兼容性
deepseek-v4-flash 等模型在 tool call 时可能返回中文股票名而非 6 位代码。`safe_ticker_component` 已加兜底自动转码，但不同模型表现仍有差异。

### 待处理 PR
- PR #18（hejingchi）：start_date 功能 + 主题切换 + Windows 字体。不建议直接 merge（与 v0.2.6 冲突），start_date 功能值得后续自行实现。

## Issue 归档
所有 GitHub Issue 的详细记录在 `issues/` 文件夹中，包含问题描述、根因分析、修复方案和当前状态。

## 开发规范
- 改动前先跑 `python -m pytest tests/ -v` 确保不破坏现有测试
- `safe_ticker_component` 是安全边界，任何绕过路径校验的改动必须慎重评估
- 数据层新增接口遵循 `tradingagents/dataflows/interface.py` 的 vendor 路由模式
- Web UI 改动在 `web/` 目录，用 `streamlit run web/launch.py` 本地测试

## 相关项目
- 上游 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — 原版框架

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (`HelloBigKingGitHub/youfu-trading-agent-astock`) via the `gh` CLI. External pull requests are also a triage surface. The top-level `issues/` folder is a separate post-mortem archive, not the live tracker. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
