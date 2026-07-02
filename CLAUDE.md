# Youfu-Trading-Agent-Astock

## 项目概述
基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)（65K Stars）的 A 股深度特化 fork。多 Agent 投研框架，7 个 Analyst 角色通过 Bull/Bear 辩论 + 三方风险辩论生成投资报告。

- **仓库**: https://github.com/HelloBigKingGitHub/youfu-trading-agent-astock
- **协议**: Apache 2.0
- **Python**: >=3.10
- **当前版本**: 0.2.14

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

### Agent 角色（7 个 + 板块轮动日报）
原版 4 个（市场/情绪/新闻/基本面）+ A 股特化 3 个（政策分析师/游资追踪/解禁监控）+ **v0.2.12 新增「板块轮动日报」**（侧边栏按钮直接调用 `get_sector_rotation_digest`，不走 LangGraph 也不消耗 LLM token）：东财 np-ipick 选股热度 + 同花顺涨停归因 + 百度 PAE 概念反查 → 4 段式 Markdown。

### 关键路径
- `tradingagents/dataflows/a_stock.py` — A 股数据 vendor，所有数据获取入口
- `tradingagents/dataflows/utils.py` — `safe_ticker_component` 路径安全校验 + 中文 ticker 自动解析
- `tradingagents/agents/` — 7 个 Analyst + Bull/Bear 辩论逻辑
- `web/app.py` — Streamlit Web UI 入口
- `web/components/sector_panel.py` — v0.2.13 板块轮动 UI（独立组件，依赖 `SectorRotationDigest`）
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
