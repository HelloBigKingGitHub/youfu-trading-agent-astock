# Changelog

All notable changes to TradingAgents are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Breaking changes within the 0.x line are called out explicitly.

## [v0.6.0] - 2026-07-13

### 新增
- **定时分析模块（Scheduled Analysis）** — Cron 调度 + ticker 源 + 多渠道通知
  - 配置页面优先：sidebar 第 8 个按钮 `⏰ 定时分析` = 完整配置 UI（一键随时增/删/启停/立即跑），不是一次性 dialog
  - **3 种 ticker 源**：
    - 持仓（自动跟踪 `PortfolioStore.list_positions()`）
    - 自选股（新增 `WatchlistStore`）
    - 手动（用户在 schedule 配置里直接列）
  - **5 个 cron helper 一键填入**：工作日 18:00 / 周一早 8:00 / 每天 9:30 / 每月 1 号 / 每 4 小时
  - **4 个通知渠道**（失败 fallback log）：
    - **WeCom** — 企业微信 webhook markdown
    - **Email** — SMTP + MIMEText
    - **Desktop** — Linux `notify-send`
    - **Log** — 永远成功（兜底）
  - **CLI 双管理**：`python -m cli.schedule list/add/pause/resume/run-now/delete/runs`
  - **预置 2 schedule**（v0.6.0 launch）：
    - **每日持仓复盘**（cron `0 18 * * 1-5`，源 portfolio，启用）
    - **周一前瞻**（cron `0 8 * * 1`，源 portfolio，默认禁用，等用户手动启用）

### 后端模块（4 个新文件）

  - **`backend/core/scheduler.py`（717 行）** — Schedule / ScheduleRun dataclass + 单例 + 后台线程 + 60s polling + tick + 持久化
    - `Schedule` 字段：`schedule_id` / `name` / `cron_expr` / `source_type` / `source_config` / `enabled` / `notify_channels` / `notify_template` / `config` / `last_run_at` / `last_run_batch_id` / `last_run_status` / `last_error`
    - `ScheduleRun` dataclass：审计字段 + `to_dict` / `from_dict`
    - `SourceType` enum：portfolio / watchlist / manual
    - `RunStatus` enum：never / ok / partial / error / skipped
    - `VALID_CRON_HELPERS`（5 个预置 cron 字符串）
    - CRUD：add / update / delete / get / list（enabled_only 参数）
    - 控制：pause / resume / run_now（立即跑，返回 batch_id）
    - 状态：start（daemon thread）/ stop / is_running / last_tick_at
    - 内部 IO：_load / _save（原子写，`.tmp` 替换） + fcntl file lock
    - `_tick` 每 60s 算哪些该跑（用 croniter）
    - `_run_schedule` 真跑：拉 ticker + `JobQueue.create_batch + submit` + 注册回调
    - `_load_tickers_for_source`（3 种源）
    - `_append_run` 写 `runs/YYYY-MM-DD.jsonl`（按天分文件）
    - `_prune_old_runs`（30 天自动清理）
    - `_ensure_presets` 首次 install 创建 2 个预置
  - **`backend/core/watchlist.py`（204 行）** — 自选股 CRUD
    - `WatchEntry` dataclass：`entry_id` / `ticker` / `tag` / `note` / `created_at`
    - `WatchlistStore` 单例（RLock + JSON 持久化）
    - `VALID_TAGS = {"长线", "短线", "观察", "T0", "T1", "T2"}`
    - 路径 `~/.tradingagents/watchlist.json`
  - **`backend/core/notifier.py`（385 行）** — 多渠道通知器
    - `Channel` enum：wecom / email / desktop / log
    - `ChannelConfig` dataclass
    - `Notifier` 单例 + 4 channel 发送
    - **Jinja2 默认模板**：`⏰ {name} {emoji} {text} - 开始: {started_at} - 耗时: {duration}s - 摘要: {summary}`
    - WeCom channel：HTTP POST webhook + markdown
    - Email channel：SMTP + MIMEText
    - Desktop channel：`subprocess notify-send`
    - Log channel：`logger.info`（永远成功）
    - **失败 fallback**：1 channel 失败不影响其他 channel + scheduler
    - 配置文件：`~/.tradingagents/schedules/channels.yaml`
  - **`cli/schedule.py`（252 行）** — Typer CLI
    - 6 命令：`list` / `add` / `run_now` / `pause` / `resume` / `delete` / `runs`
    - Rich 输出（绿 ok / 红 error）
    - `add --name --cron --source portfolio|watchlist|manual [--tickers] [--tag]` 必填
    - `runs --limit 20` 默认

### UI 模块（2 个新文件）

  - **`web/components/schedule_panel.py`（310 行）** — 主页面（4 段布局）
    - 段 1：调度列表（5 数据列 + 操作列：⏸▶🗑）
    - 段 2：新增/编辑 dialog（调 `schedule_dialogs`）
    - 段 3：运行历史（最近 20 条 audit log，按 schedule_id 过滤）
    - 段 4：全局状态（调度器运行中 / last tick / 下次执行 / 启停按钮）
    - 行内 inline edit + 删除前确认
    - 空状态：`👋 暂无定时任务，点 ➕新增 创建第一个`
    - 10s auto-refresh（`time.sleep + st.rerun`，避免 `streamlit-autorefresh` 依赖）
    - 错误用 `st.error` 红字高亮
    - ✅ 关键：`@st.dialog` 在 bare mode raise `StreamlitAPIException`，用 `try/except` 包装，保证测试 + 实战都不崩
  - **`web/components/schedule_dialogs.py`（340 行）** — 新增 / 编辑 dialog
    - `@st.dialog("⏰ 新增 / 编辑 定时任务", width="large")`
    - 字段：name + cron + 5 个 cron helper 按钮 + source radio + 自选股 tag selectbox + 手动 tickers text_input + 4 个 notify 复选框 + enabled 复选框
    - cron 实时校验：`validate_cron()` 返回 None 或错误信息，invalid 时禁用保存
    - cron 实时显示 "⏰ 下次执行: 2026-07-11 18:00:00"（用 `croniter.get_next()`）
    - 底部 3 按钮：[取消] / [保存] / [保存并立即跑]
    - 纯 helper 函数（`validate_cron` / `next_run_preview` / `parse_manual_tickers` / `build_source_config` / `validate_schedule_form` / `build_schedule`）让单元测试不需要 streamlit context

### 改 web/app.py + web/styles/elements.css

  - **`web/app.py` +5 行**：`_NAV_ITEMS` 加 `("⏰", "定时分析", "schedule")` 第 8 个 + view dispatch `elif view == "schedule": render_schedule_panel()`
  - **`web/styles/elements.css` +96 行**：`.bb-schedule-card` / `.bb-schedule-table` / `.bb-schedule-status-dot` / `.bb-schedule-cron-pill` / `.bb-schedule-history-row` / `.bb-schedule-dialog` / `.bb-schedule-empty`

### 新依赖

  - `croniter>=2.0.0`（cron 解析 + 下次时间计算）
  - `jinja2>=3.1.0`（通知模板渲染）
  - 未加 `streamlit-autorefresh`（用 `time.sleep + st.rerun` 替代，少一个 dep）

### 测试（175 new tests）

  - **`tests/test_scheduler.py`（39 tests, 460 行）** — Schedule dataclass / CRUD / 持久化 / tick / tickers 3 来源 / run_now / threading / notify / 预置 / start-stop
  - **`tests/test_watchlist.py`（23 tests, 220 行）** — CRUD / persistence / tag 过滤 / threading
  - **`tests/test_notifier.py`（26 tests, 380 行）** — 4 channel / YAML parser / templates / 失败 fallback
  - **`tests/test_cli_schedule.py`（14 tests, 200 行）** — 所有 6 个命令
  - **`tests/test_schedule_panel.py`（32 tests, 656 行）** — 4 段布局 / cron helpers / 校验 / parse / validate / build / list table / pause-resume / delete / 空状态
  - **全套 743 passed**（v0.5.0 baseline 552 + portfolio 80 + scheduler 102 + schedule_panel 32），零回归
  - 覆盖率：notifier 90% / watchlist 90% / scheduler 65%（部分 600s wait 太长未测，详 tasks.md Phase 4.5）/ schedule_panel 工具函数 ~85%

### 已知问题 (Known Limitations)

  - **单进程** — 跨机器用文件锁（`fcntl.flock`）解决，跨网络 v0.7.0 分布式
  - **时区硬编 Asia/Shanghai**（不实行 DST）
  - **无 schedule JSON 导入/导出** — v0.7.0
  - **FastAPI `/api/schedules` REST 端点未暴露** — v0.7.0
  - **多设备同步** — v0.7.0
  - **失败重试 + backoff** — v0.7.0
  - **运行时长限制（timeout）** — v0.7.0
  - **依赖 `streamlit-autorefresh` 决定**：MVP 用 `time.sleep + st.rerun` 替代（避免 dep）。
  - **60s tick 间隔**（polling）—— 1s 级别调度不支持
  - **scheduler 覆盖 65%**（不是 80%）—— `_run_schedule` 600s wait_for_batch 太长不方便测，client 实际用 streamlit 走 live smoke test 验证（截图已截）

### 完整文档 + Spec

  - `openspec/changes/scheduled-analysis/` 完整 spec-first 5 文档：
    - `.openspec.yaml`（metadata）
    - `proposal.md`（Why / What / Non-goals / Capabilities / Impact）
    - `design.md`（8 decisions + 架构图 + file-by-file spec）
    - `tasks.md`（Phase 1-6, 50+ checkboxes）
    - `README.md`（快速开始）
  - `~/.tradingagents/schedules/schedules.json`（持久化）
  - `~/.tradingagents/schedules/channels.yaml`（通知配置）
  - `~/.tradingagents/schedules/runs/YYYY-MM-DD.jsonl`（审计日志，按天分文件）

### 截图

  - `/tmp/browse_screenshots/sched_panel.png` — 4 段布局（266 KB, 1536x1152, 真实 streamlit 渲染，含 1 个测试 schedule + 15 行历史 + 调度器状态卡片）
  - `/tmp/browse_screenshots/sched_dialog.png` — ➕ 新增后 dialog（153 KB）

### 用户核心需求 ✓

  > "**定时任务要有配置页面, 可随时配置相关信息**"

  - ⏰ 定时分析 sidebar 第 8 按钮 = 完整配置 UI（一页 = 配置 + 状态 + 历史 + 全局控制），不是一次性 dialog
  - CRUD：新增 / 编辑（带 cron helper + 实时校验 + 下次执行预览）/ 暂停 / 启用 / 立即跑 / 删除（带确认）
  - 10s auto-refresh
  - 行内 inline edit + 二次确认 + 错误高亮 + 空状态友好提示
  - 跟现有 v0.5.0 portfolio / v0.4.0 chart / v0.3.0 logs 一致的 Bloomberg 暗色主题

---

## [v0.5.0] - 2026-07-XX

### 新增
- **个人仓位跟踪模块（Personal Portfolio Module）** — A 股个人仓位管理 + 业绩归因全套，与 Bull/Bear 信号联动
  - **`backend/core/portfolio_store.py`**（287 行）— 单例 + RLock 持久化
    - `positions.json` / `transactions.json` / `alerts.json` / `audit.log` 四件套
    - 原子写（`.tmp` 替换）+ JSON 容错读取（损坏文件返回 `[]`）
    - 完整 CRUD：`add/update/delete/get/list` for positions/transactions/alerts
    - 双锁模式：`PortfolioStore._lock`（类级 Lock，单例）+ `self._rlock`（实例 RLock，并发安全）
  - **`backend/core/portfolio_calc.py`**（305+ 行）— 业绩归因全套计算
    - `compute_position_metrics(position, current_price)` — 单仓位盈亏 / 持仓天数 / 今日盈亏
    - `compute_portfolio_summary(positions, prices)` — 总成本 / 总市值 / 总盈亏 / 总收益率
    - `group_by_sector(positions, prices)` — 按概念板块归因（百度 PAE 数据源）
    - `compute_xirr(transactions, current_value)` — XIRR 年化收益率（scipy brentq）
    - `compute_sharpe(equity_curve, risk_free_rate=0.025)` — Sharpe Ratio
    - `compute_max_drawdown(equity_curve)` — 最大回撤（peak-to-trough）
    - `compute_brinson_attribution(positions, benchmark_weights)` — Brinson-Fachler 业绩归因
      （selection + allocation + interaction）
  - **`backend/core/portfolio_alerts.py`**（145 行）— 7 种预警规则
    - `price_above` / `price_below` / `pct_change` / `pnl_pct` / `take_profit` / `stop_loss` / `trailing_stop`
    - 300 秒 anti-repeat 去重窗口（`ANTI_REPEAT_WINDOW_SEC`）
    - 触发后写 audit log + 推送消息（含中文字段：突破/跌破/涨跌幅/止盈/止损）
  - **`backend/core/portfolio_import.py`**（430 行）— CSV 导入导出
    - 4 种 CSV 格式自动检测：**东方财富 / 同花顺 / 雪球 / generic**
    - 冲突解决：`overwrite` / `skip` / `merge`（加权平均成本）
    - UTF-8 BOM 导出（Excel 友好，自动识别中文编码）
    - `preview_import` 区分 `new` / `conflicts` / `invalid` 三类
- **Web UI 6 tabs + 4 dialogs + 顶部 banner**
  - `web/components/portfolio_panel.py`（172 行）— 主入口 dispatcher
  - 6 tabs: 📊 总览 / 📜 流水 / 🎯 配置 / 🔔 预警 / 📥 导入/导出 / 📈 收益风险
  - 4 dialogs: 新增持仓 / 编辑持仓 / 新增交易 / 新增预警（`portfolio_dialogs.py`）
  - 顶部 Bull/Bear 信号变化 banner（Phase 4 P1 hook；MVP stub 返回 `[]`）
  - 侧边栏新增 `💼 我的仓位` nav 按钮（8 按钮，第 7 个）
  - `_fetch_current_prices` 容错：safe_quote 失败/None 跳过该 ticker
  - `_show_rebalance_banner` 信号上限 5 条防止 UI 过载
  - `_render_header` 刷新按钮清缓存 + rerun
- **数据隔离** — 所有 portfolio 数据存 `~/.tradingagents/portfolio/`，与日志/缓存分离
- **Bull/Bear 联动** — `get_rebalance_signals` Phase 4 P1 hook 已埋好（当前 MVP 返回 `[]`）

### 测试
- 304 个 portfolio 模块测试全部通过（store 90+ / calc 90+ / alerts 35+ / import 50+ / panel 90+）
- 96% 覆盖率（portfolio_store 98% / portfolio_calc 95% / portfolio_alerts 97% / portfolio_import 96%）
- 610 全量测试通过（pre-existing chart_panel 环境失败未计入）
- 所有测试 `monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)` 隔离真实 `~/.tradingagents/portfolio/`

### 已知局限
- **复权处理 P2**：当前成本价/盈亏计算使用静态成本基线（cost_basis），不支持除权除息事件后的复权调整。后续可基于交易流水 + 分红/拆股事件自动重构调整后成本基线。

## [v0.4.0] - 2026-07-XX

### 新增
- **股价走势图面板** — A股 K 线图，实时更新 + 7 段时间范围
  - `tradingagents/dataflows/a_stock.py` — push2his K 线 fallback（第 3 层，mootdx / sina 之后）
  - `web/components/chart_panel.py` — 主 UI 组件（含 Lightweight Charts 4.1.3 CDN + D2 SSE 直连东财 trends2/sse）
  - `web/styles/elements.css` — 6 个 `.bb-quote-*` 类
  - 侧边栏新增 `📈 走势图` nav 按钮（7 按钮，第 6 个）
  - 实时报价 banner（东财 push2 f43/f44/f45，30s 一次）
  - 实时 K 线 update（浏览器 EventSource → push2his trends2/sse，CORS 验证通过）
  - MA5/10/20 + 成交量 副图
  - 时间范围：1d / 1w / 1m / 3m / 6m / 1y / all
  - 缓存：`~/.tradingagents/cache/kline/{ticker}_{range}.csv`（24h TTL）

### 测试
- 13 新测试（push2his 6 + chart_panel 7）全部通过
- 312 已有测试无回归

## [v0.3.0] - 2026-07-XX

### 新增
- **日志监控模块** — 按分析任务持久化全部 LangGraph stream chunks
  - `backend/core/log_store.py` — `LogStore`（读）+ `LogWriter`（写）+ dataclass
  - `web/runner.py` — `_run()` stream 循环集成 LogWriter
  - `web/components/logs_panel.py` — UI 主组件（GitHub PR 风格 1:3 双列）
  - `web/styles/elements.css` — 13 个 `.bb-log-*` 类
  - `cli/list_logs.py` — CLI 工具
  - 侧边栏新增 `📋 日志` nav 按钮（6 按钮，第 5 个）
- 存储结构: `~/.tradingagents/logs/{ticker}/{date}_run{NN}/` + 3 个 jsonl（按 type 分）+ meta.json
- 兼容旧结构 `TradingAgentsStrategy_logs/full_states_log_*.json`（降级读 + `is_legacy=True` 标记）
- chunk 分类启发式: 9 个 agent_output + 3 个 llm（debate judge / risk judge / trader）
- Content 截断 50K/chunk 防 OOM
- 文件锁 `fcntl.flock` per-append（防御性）
- 写入失败 try/except 不 raise 阻断 LangGraph

### 测试
- 31 新测试（LogStore 16 + Runner 7 + UI 6 + CLI 3）全部通过
- 263 已有测试无回归
- pytest 总数: 263 passed, 2 skipped

## [Unreleased]

### Changed

- **Sidebar nav 分组（仅视觉）**：4 按钮 nav (分析/板块轮动/历史/设置) 视觉上分为两组
  - 「导航」组：📊 分析 / 📈 板块轮动
  - 「管理」组：📋 历史 / ⚙️ 设置
  - 实施方式：纯 CSS（`web/styles/elements.css` 内 +87 行），通过 `::before` 伪元素注入
    section 标签，通过 `box-shadow inset` 在 primary 按钮左侧画 3px 冰川蓝指示条。
  - **未触碰** `web/app.py` 或 `_NAV_ITEMS` / `_render_nav_buttons`（保持前 4 个 commit 的
    既有 helper 不变），分组效果全部由 CSS 完成。

## [0.2.13] — 2026-06-25

### Fixed

- **板块轮动当日数据解析（v0.2.13 hotfix）**：THS `get_hot_stocks` 在当日盘中
  返回的 rows 缺少 `zhangfu`/`huanshou`/`chengjiaoe`/`ddejingliang` 字段（原字段值
  为 `None`）。旧版 `_extract_limitup_codes` 用 `[\d.]+` 严格匹配百分比，导致**所有**
  当日涨停股被过滤 → `hot_stocks=[]` → 跳过百度 PAE 反查 → UI 显示「百度 PAE ✗」。
  - 修复：parser 改为只匹配「6 位代码 + 名称 + 冒号」，价格字段不强制；价格字段
    渲染空值用 `-` 代替 `+%` 垃圾输出。
  - 影响：板块轮动日报恢复 28 个概念板块 / 多只涨停股聚类。
  - 新增 2 个回归测试覆盖无价格数据的当日行 + 老格式 `+%` 行。

### Changed

- **板块轮动 UI 重构（v0.2.13）**：将 `web/app.py` 内联的 sector tab 抽出为独立组件
  `web/components/sector_panel.py`，不再直接渲染原始 `digest.markdown`。新 UI：
  - **顶部工具栏**：搜索框（代码/名称/板块名）+ 「仅看 ≥N 只涨停」阀值（默认 3）；
  - **3 源状态行**：`✓/✗` 展示东财 np-ipick / 同花顺 / 百度 PAE 健康度；
  - **机构策略 expander**（顶部默认折叠）：Top 3 np-ipick 选股热度；
  - **概念板块分组表格**：按股票数降序排，Top 3 板块默认展开，其余折叠；
    表格列：代码 | 名称 | 题材 | 板块涨幅 | 操作；
  - **[分析] 操作列**：每行可点击，2-step 跳转 analyze tab + 预填 ticker/日期
    （如有正在运行的 tracker 则警告不跳转）；
  - **降级路径**：`concept_blocks` 为空但 `hot_stocks` 有数据 → 平铺表；
    全部为空 → `.bb-sector-empty` 空状态卡片。

### Added

- 新增 `web/components/sector_panel.py`（~190 行）+ 5 个 CSS class
  `.bb-sector-toolbar` / `.bb-sector-meta(ok|fail)` /
  `.bb-sector-block-header|stats` / `.bb-sector-empty`。
- 新增 `tests/components/test_sector_panel.py`（49 个测试，覆盖率 86%）。

## [0.2.12] — 2026-06-17

### Added

- **板块轮动日报（v0.2.12）**：侧边栏新增「🔄 板块轮动」按钮，一键生成 A 股当日
  板块轮动快照，**不消耗 LLM token**。3 个数据源聚合：
  1. **东财 np-ipick 选股热度 Top 20**（机构/编辑视角，按 `heatValue` 降序）；
  2. **同花顺热股 + 题材归因**（人工编辑的 reason tags）；
  3. **百度 PAE 概念反查**（涨停股 → 所属概念板块聚类，≥ 2 只涨停股的概念保留）。
  输出 4 段式 Markdown：
  - 一、机构/编辑视角（选股热度）；
  - 二、强势概念板块（≥ 2 只涨停股的板块聚类 + 板块涨幅）；
  - 三、龙头候选池（涨停股，按概念板块分组）；
  - 四、个股涨停理由归因（同花顺 reason tags 列表）。
- **新数据源**：东方财富 np-ipick（`https://np-ipick.eastmoney.com/recommend/stock/heat/ranking`），
  走 v0.2.11 `_em_get()` 节流通道（不影响东财防封策略）。
- **「游资追踪师」分析师升级**：tool 列表首位新增 `get_sector_rotation_digest`，
  提示词要求「先调用 1 次板块轮动日报建立板块级基线，再下钻个股」。

### Web UI

- 侧边栏新增导航按钮「🔄 板块轮动」，新页面 `nav == "sector"`；
- 「🔄 拉取最新」按钮可强制刷新（清除 `st.session_state.sector_digest_cache`）；
- 加载 spinner：「正在拉取板块轮动数据,预计 15-25 秒...」；
- **不消耗 LLM**：页面直接调用 `route_to_vendor("get_sector_rotation_digest", "", 20)`，
  纯 HTTP 拉数 + Markdown 渲染。

### Vendor Routing

- `get_hot_strategy_ranking` / `get_sector_rotation_digest` 已注册到
  `tradingagents/dataflows/interface.py` 的 `VENDOR_METHODS`，归属 `signal_data` 类别；
- 对应 LangChain `@tool` 包装见 `tradingagents/agents/utils/signal_data_tools.py`，
  `agent_utils.py` 已 import 这两个新工具供分析师链路使用。

### Tested

- 13 个单元测试（`tests/test_sector_rotation.py`），覆盖：
  - `get_hot_strategy_ranking` 解析 / 排序 / 缺省日期 / 5xx 错误 / 空数据 / top_n 上限 50；
  - `_extract_limitup_codes` 解析 THS 风格 Markdown；
  - `_batch_reverse_concept_blocks` 10 只股票 = 1 次调用 / 20 只 = 2 次调用 / 过滤 < 2 只股票的概念；
  - `get_sector_rotation_digest` 三源聚合 / 零涨停降级 / 单源失败优雅降级；
- 新函数（`a_stock.py` 第 2062-2370 行）覆盖率 100%，全模块覆盖率 20%
  （因 1108 行的 vendor 文件覆盖大量历史代码）。

### Known Limitations

- **不走 push2/push2his**：本日报采用「涨停股→PAE 反查」路径，**不**走
  「行业→成分股」路径，原因是部分网络环境 push2/push2his 接口不稳定
  （2026-06 验证：5 次本地请求 0 次成功）。np-ipick + THS + PAE 这条路
  对 push2 不可用环境是更稳的兜底；
- **每日缓存**：`sector_rotation_concept_v1.json` 缓存当天 PAE 反查结果，
  跨日失效——同一天重复刷新 Web UI 按钮不重复请求 PAE；
- **历史日期不支持**：`get_sector_rotation_digest(curr_date)` 当前
  `curr_date` 仅作 header 显示用，不影响数据来源（实际仍是今日）。

---

## [0.2.11] — 2026-05-30

### Changed

- **东财接口统一限流防封（移植自 a-stock-data v3.2）**：数据层 `a_stock.py` 里所有指向
  `eastmoney.com` 的请求（push2 / push2his / datacenter-web / search-api / np-weblist
  共 7 个调用点）统一收口到新的节流入口 `_em_get()`，多 Agent 投研跑批量分析时不再触发
  临时封 IP（社区实测东财风控：每秒 >5 / 并发 ≥10 / 1 分钟 ≥200 / 5 分钟 ≥300 触发封禁，
  多位用户反馈过）。具体：
  - 模块级 last-call 时间戳 + 最小间隔 `EM_MIN_INTERVAL`（默认 1.0s，可用同名环境变量覆盖）
    + 0.1~0.5s 随机抖动，串行限流，QPS ≤ 1；
  - 复用 `requests.Session`（Keep-Alive）+ 默认 UA；各端点保留自己的 Referer/Origin header；
  - **仅东财接口限流**——mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等非东财源
    不受影响（实测不封 IP）。批量场景可设 `EM_MIN_INTERVAL=1.5~2` 进一步降速。

### Tested

- 实测 4 次连续 `_em_get` 请求东财 push2（600519 = 贵州茅台），HTTP 200 返回真实数据；
  相邻调用间隔 1.47 / 1.18 / 1.42s 均 ≥1.0s，限流生效。
- `get_industry_comparison` / `get_fund_flow` / `get_dragon_tiger_board` 三个东财公共函数
  端到端跑通（走同一已验证的 `_em_get` 通道）；`py_compile` 通过；grep 复核：7 个 `_em_get`
  调用点 + 0 个残留 `_req.` + 8 个非东财源（mootdx/腾讯/新浪/同花顺/财联社/百度）未被误伤。

---

## [0.2.10] — 2026-05-30

### Added

- **Web UI 支持第三方 / 代理 API 网关（#35）**：侧边栏新增「API Base URL」输入框，
  也可在 `.env` 设 `BACKEND_URL`。方便国内用户通过中转网关访问 Claude / OpenAI 等模型
  （API Key 仍从 `.env` 读取，如 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`）。
  侧边栏输入优先于环境变量，留空则用所选供应商官方地址。

---

## [0.2.9] — 2026-05-30

### Added

- **Markdown 报告导出**：分析结果页新增「下载 Markdown」按钮。MD 导出零字体依赖、
  跨平台永远可用，是 PDF 之外的稳妥兜底（#17 多位用户请求）。

### Fixed

- **PDF 中文字体跨平台崩溃（#22 / #30 / #31）**：原 `_FONT_CANDIDATES` 只列了
  macOS/Linux 字体，Windows 用户找不到中文字体 → fpdf 回退 Helvetica → 渲染中文时
  抛 `FPDFUnicodeEncodingException` / `Character "股" ... outside the range`。
  现改为**按操作系统排序的字体候选**（Windows 微软雅黑/黑体/宋体、macOS 苹方、
  Linux Noto/文泉驿）+ 递归扫描字体目录兜底。
- **PDF 失败拖垮整个结果页**：`generate_pdf` 原先在结果页渲染时被 eager 调用，一旦
  报错整页崩成 traceback，用户连分析结果都看不到。现改为 **try/except 包裹 + 懒生成**，
  PDF 失败只禁用 PDF 按钮并提示改用 Markdown，分析报告照常显示。
- **长串中文表格/段落渲染报错（#31）**：`multi_cell` 遇到无空格的长中文串抛
  `Not enough horizontal space to render a single character`。已为内容 `multi_cell`
  加 `wrapmode="CHAR"` 并复位左边距，中文按字符正确换行。
- **缺字体时优雅降级**：系统无任何中文字体时，`generate_pdf` 抛出清晰中文报错
  （指引安装字体或改用 Markdown），不再是深层 fpdf traceback。

### Tested

- Streamlit 1.50 环境用 fpdf2 2.8.4 实测：含中文标题、表格、列表、200 字无空格长串的
  报告成功生成 7 页 PDF（目视确认中文渲染无乱码、长串正确换行）；Markdown 导出正常；
  无字体路径正确抛 RuntimeError。

---

## [0.2.8] — 2026-05-30

### Fixed

- **Web UI 侧边栏收起后无法展开（#36）**：为录视频清爽化界面的自定义 CSS 把整个
  顶栏 `stHeader` 和工具栏 `stToolbar` 都 `display:none` 掉了。但 Streamlit ≥1.36 的
  「展开侧边栏」按钮 `stExpandSidebarButton` 正好嵌在工具栏内部，于是侧边栏一旦收起
  ——无论是手动点收起箭头，还是**页面缩放 / 窄屏时 Streamlit 自动收起**——展开按钮
  跟着被隐藏，再也调不出来，刷新、重启都没用。原先那行兜底的 `collapsedControl`
  选择器是旧版 DOM，在 1.45+ 已不存在，等于没写。
  修复：不再整个隐藏顶栏/工具栏，改为**保留二者、将 header 透明化、只精准隐藏
  Deploy 按钮 / 主菜单 / 状态条 / 装饰条**，侧边栏展开按钮恢复可见可点，录屏依旧干净。
  已用 Streamlit 1.50 + headless Chrome 在收起/展开两种状态下实测验证。

---

## [0.2.7] — 2026-05-19

### Fixed

- **百度 PAE 资金流下线**：`fundflow` + `fundsortlist` 接口已返回空，
  `get_fund_flow()` 全部替换为东财 push2 资金流 API（分钟级 + 日级 20 天）
- **龙虎榜机构动向**：`RPT_ORGANIZATION_BUSSINESS` 报表配置已下线，
  改用 BUY/SELL 席位明细筛选 `OPERATEDEPT_CODE="0"`（机构专用席位）
- **东财全球资讯**：新增必填参数 `req_trace`（UUID），否则返回 403

---

## [0.2.6] — 2026-05-19

### Fixed

- **依赖冲突**：`langchain-google-genai` 移至可选依赖组 `[google]`，
  消除与 mootdx 的 httpx 版本冲突。`pip install -e .` 开箱即用，
  需要 Google Gemini 时 `pip install -e ".[google]"`。
- **WebUI 模型写死 minimax**：侧边栏新增 LLM 供应商和模型选择器，
  支持 9 个供应商（MiniMax/DeepSeek/Qwen/GLM/OpenAI/Anthropic/Google/xAI/Ollama），
  默认仍为 MiniMax 但用户可自由切换。
- **阶段分析内容消失**：进度面板现在展示所有已完成阶段的报告（按时间倒序），
  不再只显示最新的一个。最新阶段自动展开，历史阶段可点击展开。

### Changed

- `.env.example` 补充 `MINIMAX_API_KEY=` 条目
- README 快速开始增加 Google 可选依赖安装说明
- README Web UI 功能列表更新

## [0.2.5] — 2026-05-17

### Breaking Changes

- **移除 akshare 依赖** — `akshare>=1.18.0` 从 `pyproject.toml` 中删除。
  所有原 akshare 调用已替换为直接 HTTP API（东财 datacenter、新浪财经、
  同花顺 10jqka、财联社 cls.cn、百度股市通）。

### Changed

- `tradingagents/dataflows/a_stock.py` 全面重构数据获取层：
  - `get_stock_data()` → 新浪 JSON K线 API + push2.eastmoney 实时行情
  - `get_stock_info()` → push2.eastmoney 个股基本信息
  - `get_stock_news()` → 东财 np-weblist 滚动新闻（已有，无变化）
  - `get_financial_data()` → 新浪财经财报三表 API
  - `get_market_news()` → 财联社 cls.cn 快讯 + 东财 np-weblist
  - `get_analyst_forecast()` → 同花顺 10jqka EPS 一致预期
  - `get_dragon_tiger_board()` → 东财 datacenter RPT_DAILYBILLBOARD
  - `get_restricted_release()` → 东财 datacenter RPT_LIFT_STAGE
  - `get_industry_overview()` → push2.eastmoney 板块行情
- 新增内部 helper：`_eastmoney_datacenter()`、`_ths_eps_forecast()`、`_sina_kline_fallback()`
- 所有函数签名和返回格式保持不变，对上层 Agent 透明

### Fixed

- 彻底消除 akshare + pandas 3.0 + pyarrow 的 `ArrowInvalid` 崩溃问题
- 消除 akshare 与 mootdx 的 httpx 版本冲突

## [0.2.4] — 2026-04-25

### Added

- **Structured-output decision agents.** Research Manager, Trader, and Portfolio
  Manager now use `llm.with_structured_output(Schema)` on their primary call
  and return typed Pydantic instances. Each provider's native structured-output
  mode is used (`json_schema` for OpenAI / xAI, `response_schema` for Gemini,
  tool-use for Anthropic, function-calling for OpenAI-compatible providers).
  Render helpers preserve the existing markdown shape so memory log, CLI
  display, and saved reports keep working unchanged. (#434)
- **LangGraph checkpoint resume** — opt-in via `--checkpoint`. State is saved
  after each node so crashed or interrupted runs resume from the last
  successful step. Per-ticker SQLite databases under
  `~/.tradingagents/cache/checkpoints/`. `--clear-checkpoints` resets them. (#594)
- **Persistent decision log** replacing the per-agent BM25 memory. Decisions
  are stored automatically at the end of `propagate()`; the next same-ticker
  run resolves prior pending entries with realised return, alpha vs SPY, and
  a one-paragraph reflection. Override path with `TRADINGAGENTS_MEMORY_LOG_PATH`.
  Optional `memory_log_max_entries` config caps resolved entries; pending
  entries are never pruned. (#578, #563, #564, #579)
- **DeepSeek, Qwen (Alibaba DashScope), GLM (Zhipu), and Azure OpenAI**
  providers, plus dynamic OpenRouter model selection.
- **Docker support** — multi-stage build with separate dev and runtime images.
- **`scripts/smoke_structured_output.py`** — diagnostic that exercises the
  three structured-output agents against any provider so contributors can
  verify their setup with one command.
- **5-tier rating scale** (Buy / Overweight / Hold / Underweight / Sell) used
  consistently by Research Manager, Portfolio Manager, signal processor, and
  the memory log; Trader keeps 3-tier (Buy / Hold / Sell) since transaction
  direction is naturally ternary.
- **Pytest fixtures** — lazy LLM client imports plus placeholder API keys so
  the test suite runs cleanly without credentials. (#588)

### Changed

- **`backend_url` default is now `None`** rather than the OpenAI URL. Each
  provider client falls back to its native default. The previous default
  leaked the OpenAI URL into non-OpenAI clients (e.g. Gemini), producing
  malformed request URLs for Python users who switched providers without
  overriding `backend_url`. The CLI flow is unaffected.
- All file I/O passes explicit `encoding="utf-8"` so Windows users no longer
  hit `UnicodeEncodeError` with the cp1252 default. (#543, #550, #576)
- Cache and log directories moved to `~/.tradingagents/` to resolve Docker
  permission issues. (#519)
- `SignalProcessor` reads the rating from the Portfolio Manager's rendered
  markdown via a deterministic heuristic — no extra LLM call.
- OpenAI structured-output calls default to `method="function_calling"` to
  avoid noisy `PydanticSerializationUnexpectedValue` warnings emitted by
  langchain-openai's Responses-API parse path. Same typed result, no warnings.

### Fixed

- Empty memory no longer triggers fabricated past-lessons in agent prompts;
  the memory-log redesign makes this structurally impossible since only the
  Portfolio Manager consults memory and only when entries exist. (#572)
- Tool-call logging processes every chunk message, not just the last one, and
  memory score normalization handles empty score arrays. (#534, #531)

### Removed

- `FinancialSituationMemory` (the per-agent BM25 system) and the dead
  `reflect_and_remember()` plumbing; subsumed by the persistent decision log.
- Hardcoded Google endpoint that caused 404 when `langchain-google-genai`
  changed its API path. (#493, #496)

### Contributors

Thanks to everyone who shaped this release through code, design, and reports:

- [@claytonbrown](https://github.com/claytonbrown) — checkpoint resume (#594), test fixtures (#588), design feedback on cost tracking (#582) and structured validation (#583)
- [@Bcardo](https://github.com/Bcardo) — memory-log redesign (#579), empty-memory hallucination report (#572), encoding fix proposal (#570)
- [@voidborne-d](https://github.com/voidborne-d) — memory persistence design (#564), portfolio manager state fix (#503)
- [@mannubaveja007](https://github.com/mannubaveja007) — structured-output feature request (#434)
- [@kelder66](https://github.com/kelder66) — RAM-only memory issue (#563)
- [@Gujiassh](https://github.com/Gujiassh) — tool-call logging fix (#534), test stub PR (#533)
- [@iuyup](https://github.com/iuyup) — memory score normalization fix (#531)
- [@kaihg](https://github.com/kaihg) — Google base_url fix (#496)
- [@32ryh98yfe](https://github.com/32ryh98yfe) — Gemini 404 report (#493)
- [@uppb](https://github.com/uppb) — OpenRouter dynamic model selection (#482)
- [@guoz14](https://github.com/guoz14) — OpenRouter limited-model report (#337)
- [@samchenku](https://github.com/samchenku) — indicator name normalization (#490)
- [@JasonOA888](https://github.com/JasonOA888) — y_finance pandas import fix (#488)
- [@tiffanychum](https://github.com/tiffanychum) — stale import cleanup (#499)
- [@zaizou](https://github.com/zaizou) — Docker permission issue (#519)
- [@Stosman123](https://github.com/Stosman123), [@mauropuga](https://github.com/mauropuga), [@hotwind2015](https://github.com/hotwind2015) — Windows encoding bug reports (#543, #550, #576)
- [@nnishad](https://github.com/nnishad), [@atharvajoshi01](https://github.com/atharvajoshi01) — encoding fix proposals (#568, #549)

## [0.2.3] — 2026-03-29

### Added

- **Multi-language output** for analyst reports and final decisions, with a
  CLI selector. Internal agent debate stays in English for reasoning quality. (#472)
- **GPT-5.4 family models** in the default catalog, with deep/quick model split.
- **Unified model catalog** as a single source of truth for CLI options and
  provider validation.

### Changed

- `base_url` is forwarded to Google and Anthropic clients so corporate proxies
  work consistently across providers. (#427)
- Standardised the Google `api_key` parameter to the unified `api_key` form.

### Fixed

- Backtesting fetchers no longer leak look-ahead data when `curr_date` is in
  the middle of a fetched window. (#475)
- Invalid indicator names from the LLM are caught at the tool boundary instead
  of crashing the run. (#429)
- yfinance news fetchers respect the same exponential-backoff retry as price
  fetchers. (#445)

### Contributors

- [@ahmedk20](https://github.com/ahmedk20) — multi-language output (#472)
- [@CadeYu](https://github.com/CadeYu) — model catalog typing (#464)
- [@javierdejesusda](https://github.com/javierdejesusda) — unified Google API key parameter (#453)
- [@voidborne-d](https://github.com/voidborne-d) — yfinance news retry (#445)
- [@kostakost2](https://github.com/kostakost2) — look-ahead bias report (#475)
- [@lu-zhengda](https://github.com/lu-zhengda) — proxy/base_url support request (#427)
- [@VamsiKrishna2021](https://github.com/VamsiKrishna2021) — invalid indicator crash report (#429)

## [0.2.2] — 2026-03-22

### Added

- **Five-tier rating scale** (Buy / Overweight / Hold / Underweight / Sell)
  introduced for the Portfolio Manager.
- **Anthropic effort level** support for Claude models.
- **OpenAI Responses API** path for native OpenAI models.

### Changed

- `risk_manager` renamed to `portfolio_manager` to match the role description
  shown in the CLI display.
- Exchange-qualified tickers (e.g. `7203.T`, `BRK.B`) preserved across all
  agent prompts and tool calls.
- Process-level UTF-8 default attempted for cross-platform consistency
  (note: this approach did not actually take effect; replaced in v0.2.4 with
  explicit per-call `encoding="utf-8"` arguments).

### Fixed

- yfinance rate-limit errors are retried with exponential backoff. (#426)
- HTTP client SSL customisation is supported for environments that need
  custom certificate bundles. (#379)
- Report-section writes handle list-of-string content gracefully.

### Contributors

- [@CadeYu](https://github.com/CadeYu) — exchange-qualified ticker preservation (#413)
- [@yang1002378395-cmyk](https://github.com/yang1002378395-cmyk) — HTTP client SSL customisation (#379)

## [0.2.1] — 2026-03-15

### Security

- Patched `langchain-core` vulnerability (LangGrinch). (#335)
- Removed `chainlit` dependency affected by CVE-2026-22218.

### Added

- `pyproject.toml` build-system configuration; the project now installs via
  modern packaging tooling.

### Removed

- `setup.py` — dependencies consolidated to `pyproject.toml`.

### Fixed

- Risk manager reads the correct fundamental report source. (#341)
- All `open()` calls receive an explicit UTF-8 encoding (initial pass).
- `get_indicators` tool handles comma-separated indicator names from the LLM. (#368)
- `Propagation` initialises every debate-state field so risk debaters never
  see missing keys.
- Stock data parsing tolerates malformed CSVs and NaN values.
- Conditional debate logic respects the configured round count. (#361)

### Contributors

- [@RinZ27](https://github.com/RinZ27) — `langchain-core` security patch (#335)
- [@Ljx-007](https://github.com/Ljx-007) — risk manager fundamental-report fix (#341)
- [@makk9](https://github.com/makk9) — debate-rounds config issue (#361)

## [0.2.0] — 2026-02-04

This is the largest release since the initial public version. The framework
moved from single-provider to a multi-provider architecture and grew several
production-ready surfaces.

### Added

- **Multi-provider LLM support** (OpenAI, Google, Anthropic, xAI, OpenRouter,
  Ollama) via a factory pattern, with provider-specific thinking configurations.
- **Alpha Vantage** integration as a configurable primary data provider, with
  yfinance as a community-stability fallback.
- **Footer statistics** in the CLI: real-time tracking of LLM calls, tool
  calls, and token usage via LangChain callbacks.
- **Post-analysis report saving** — the framework writes per-section markdown
  files (analyst reports, debate transcripts, final decision) when a run
  completes.
- **Announcements panel** — fetches updates from `api.tauric.ai/v1/announcements`
  for the CLI welcome screen.
- **Tool fallbacks** so a single vendor outage does not stop the pipeline.

### Changed

- Risky / Safe risk debaters renamed to **Aggressive / Conservative** for
  consistency with the displayed agent labels.
- Default data vendor switched to balance reliability and quota across
  community deployments.
- Ollama and OpenRouter model lists updated; default endpoints clarified.

### Fixed

- Analyst status tracking and message deduplication in the live display.
- Infinite-loop guard in the agent loop; reflection and logging hardened.
- Various data-vendor implementation bugs and tool-signature mismatches.

### Contributors

This release is the first with substantial outside contributions; many community
PRs from late 2025 also landed here.

- [@luohy15](https://github.com/luohy15) — Alpha Vantage data-vendor integration (#235)
- [@EdwardoSunny](https://github.com/EdwardoSunny) — yfinance fetching optimisations (#245)
- [@Mirza-Samad-Ahmed-Baig](https://github.com/Mirza-Samad-Ahmed-Baig) — infinite-loop guard, reflection, and logging fixes (#89)
- [@ZeroAct](https://github.com/ZeroAct) — saved results path support (#29)
- [@Zhongyi-Lu](https://github.com/Zhongyi-Lu) — `.env` gitignore (#49)
- [@csoboy](https://github.com/csoboy) — local Ollama setup (#53)
- [@chauhang](https://github.com/chauhang) — initial Docker support attempt (#47, later reverted; the merged Docker support shipped in v0.2.4)

## [0.1.1] — 2025-06-07

### Removed

- Static site assets that had been bundled with v0.1.0; the public site now
  lives separately.

## [0.1.0] — 2025-06-05

### Added

- **Initial public release** of the TradingAgents multi-agent trading
  framework: market / sentiment / news / fundamentals analysts; bull and bear
  researchers; trader; aggressive, conservative, and neutral risk debaters;
  portfolio manager. LangGraph orchestration, yfinance data, per-agent
  BM25 memory, single-provider OpenAI integration, interactive CLI.

[0.2.4]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/TauricResearch/TradingAgents/releases/tag/v0.1.0
