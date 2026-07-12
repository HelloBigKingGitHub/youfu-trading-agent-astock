# 定时分析 v0.6.0 — Tasks (Phase 1-5, 50+ checkboxes)

## Phase 1 — 数据层 + 通知 (无 UI, 纯函数 + 文件 IO)

### 1.1 `backend/core/scheduler.py` 骨架

- [ ] 1.1.1 `Schedule` dataclass: schedule_id / name / cron_expr / source_type / source_config / enabled / notify_channels / notify_template / config / last_run_at / last_run_batch_id / last_run_status / last_error / created_at / created_by
  - `to_dict()` / `from_dict()` 方法
  - `next_run_at()` 用 croniter
  - `validate()` 返回 None 或错误信息
- [ ] 1.1.2 `ScheduleRun` dataclass: run_id / schedule_id / started_at / finished_at / status / batch_id / job_ids / duration / summary / error / ticker_count
  - `to_dict()` / `from_dict()`
- [ ] 1.1.3 `SourceType` enum: portfolio / watchlist / manual
- [ ] 1.1.4 `RunStatus` enum: never / ok / partial / error / skipped
- [ ] 1.1.5 `Scheduler` 单例 (类级 Lock + 实例 RLock, 跟 portfolio_store 同模式)
- [ ] 1.1.6 路径常量: `SCHEDULES_DIR = ~/.tradingagents/schedules/`, `RUNS_DIR = SCHEDULES_DIR / "runs"`
- [ ] 1.1.7 Schedule CRUD: add / update / delete / get / list (enabled_only 参数)
- [ ] 1.1.8 Schedule 控制: pause / resume (改 enabled) / run_now (立即跑)
- [ ] 1.1.9 调度器状态: start / stop / is_running / last_tick_at
- [ ] 1.1.10 内部 IO: _load (从 schedules.json) / _save (原子写) / _file_lock (fcntl)
- [ ] 1.1.11 _tick (60s polling, 算哪些该跑)
- [ ] 1.1.12 _run_schedule (拉 ticker + create_batch + submit + 注册回调)
- [ ] 1.1.13 _load_tickers_for_source (portfolio / watchlist / manual 三种源)
- [ ] 1.1.14 _append_run (写 runs/YYYY-MM-DD.jsonl)
- [ ] 1.1.15 _prune_old_runs (清 30 天前)
- [ ] 1.1.16 后台 thread: daemon=True, name="scheduler-tick"
- [ ] 1.1.17 预置 2 个 schedule (每日持仓复盘 + 周一前瞻) 在 install 时创建

### 1.2 `backend/core/watchlist.py` 自选股

- [ ] 1.2.1 `WatchEntry` dataclass: entry_id / ticker / tag / note / created_at
- [ ] 1.2.2 `WatchlistStore` 单例 (RLock + JSON 持久化, 跟 portfolio_store 同模式)
- [ ] 1.2.3 `VALID_TAGS` 常量: {"长线", "短线", "观察", "T0", "T1", "T2"}
- [ ] 1.2.4 CRUD: add (ticker 6 位 + tag 合法 + 唯一) / remove / list (tag 过滤) / count
- [ ] 1.2.5 路径: `WATCHLIST_FILE = ~/.tradingagents/watchlist.json`

### 1.3 `backend/core/notifier.py` 通知

- [ ] 1.3.1 `Channel` enum: wecom / email / desktop / log
- [ ] 1.3.2 `ChannelConfig` dataclass: wecom_webhook / smtp_host/port/user/password / smtp_to
- [ ] 1.3.3 `Notifier` 单例, 4 channel 发送
- [ ] 1.3.4 Jinja2 默认模板: schedule_name / status_emoji / status_text / started_at / duration / summary / batch_id / run_id
- [ ] 1.3.5 WeCom channel: HTTP POST webhook, markdown 格式
- [ ] 1.3.6 Email channel: SMTP with MIMEText
- [ ] 1.3.7 Desktop channel: subprocess notify-send (Linux)
- [ ] 1.3.8 Log channel: logger.info
- [ ] 1.3.9 失败 fallback: 1 channel 失败不影响其他 + scheduler
- [ ] 1.3.10 配置文件: `~/.tradingagents/schedules/channels.yaml`

### 1.4 复用现有模块

- [ ] 1.4.1 Scheduler 调 `PortfolioStore.get_instance().list_positions()` 拉持仓 ticker
- [ ] 1.4.2 Scheduler 调 `JobQueue.get_instance().create_batch() + submit()` 跑分析
- [ ] 1.4.3 Scheduler 注册 `BatchStatus.on_complete` 回调 → 通知
- [ ] 1.4.4 Job 复用现有 web/runner (LLM provider/model 透传)

## Phase 2 — Streamlit UI (核心: 配置页面!)

### 2.1 `web/components/schedule_panel.py` 主页面

- [ ] 2.1.1 `render_schedule_panel()` 入口
- [ ] 2.1.2 顶部工具栏: 标题 + ➕新增 + ▶立即跑全部 + ⏸停止调度器 + ⟳刷新
- [ ] 2.1.3 st_autorefresh 10s 自动刷新
- [ ] 2.1.4 段 1: 调度列表 (表格 5 列: 名称 / cron / 源 / 启用 / 上次 + 操作)
- [ ] 2.1.5 段 2: 新增/编辑 dialog (调 schedule_dialogs._add_edit_dialog)
- [ ] 2.1.6 段 3: 运行历史 (runs/YYYY-MM-DD.jsonl 读取, 按 schedule_id 过滤)
- [ ] 2.1.7 段 4: 全局状态 (调度器运行中 / last tick / 下次执行 / 启停)
- [ ] 2.1.8 行操作: ⏸暂停 / ▶立即跑 / 🗑删除
- [ ] 2.1.9 删除前确认 dialog (st.warning + 2 button)
- [ ] 2.1.10 空状态: "👋 暂无定时任务, 点 ➕新增 创建第一个"

### 2.2 `web/components/schedule_dialogs.py` 新增/编辑 dialog

- [ ] 2.2.1 `@st.dialog("新增 / 编辑 schedule")` 装饰器
- [ ] 2.2.2 name 文本输入 (必填)
- [ ] 2.2.3 cron 文本输入 + 5 个 helper 按钮 (一键填入: 工作日 18:00 / 周一早 8:00 / 每天 9:30 / 每月 1 号 / 每 4 小时)
- [ ] 2.2.4 cron 实时校验: invalid → st.error 红字 + 禁用保存按钮
- [ ] 2.2.5 cron 实时显示 "⏰ 下次执行: 2026-07-11 18:00:00"
- [ ] 2.2.6 source radio: 持仓 / 自选股 / 手动
- [ ] 2.2.7 持仓: 无额外 config
- [ ] 2.2.8 自选股: tag 下拉 (从 VALID_TAGS 拉)
- [ ] 2.2.9 手动: 文本输入 "tickers" 逗号分隔 (600595,688017)
- [ ] 2.2.10 notify_channels 4 checkbox (WeCom / Email / Desktop / Log)
- [ ] 2.2.11 notify_template 文本输入 (默认 v0.6.0 default)
- [ ] 2.2.12 config 字典 (LLM provider + model)
- [ ] 2.2.13 enabled checkbox (默认 true)
- [ ] 2.2.14 底部: [取消] [保存] [保存并立即跑] (3 按钮)
- [ ] 2.2.15 保存: 调 scheduler.add_schedule / update_schedule, st.success toast
- [ ] 2.2.16 保存并立即跑: 调 scheduler.run_now, 跳转运行历史

### 2.3 改 `web/app.py`

- [ ] 2.3.1 `_NAV_ITEMS` 加 `("⏰", "定时分析", "schedule")` 第 9 个
- [ ] 2.3.2 view dispatch: `elif view == "schedule": render_schedule_panel()`

### 2.4 改 `web/components/sidebar.py`

- [ ] 2.4.1 无功能改动 (sort 顺序自然)

### 2.5 改 `web/styles/elements.css`

- [ ] 2.5.1 `.bb-schedule-card` (调度列表卡片)
- [ ] 2.5.2 `.bb-schedule-table` (调度表)
- [ ] 2.5.3 `.bb-schedule-status-dot` (启用/暂停 红绿点)
- [ ] 2.5.4 `.bb-schedule-cron-pill` (cron 标签)
- [ ] 2.5.5 `.bb-schedule-history-row` (历史行)
- [ ] 2.5.6 `.bb-schedule-dialog` (dialog 标题)
- [ ] 2.5.7 `.bb-schedule-empty` (空状态)

## Phase 3 — CLI

### 3.1 `cli/schedule.py`

- [ ] 3.1.1 Typer app, 6 个命令: list / add / run_now / pause / resume / delete / runs
- [ ] 3.1.2 `list` --enabled-only flag
- [ ] 3.1.3 `add --name --cron --source --tickers --tag` 必填 name + cron, source 选 portfolio/watchlist/manual
- [ ] 3.1.4 `add` 默认 enabled=true
- [ ] 3.1.5 `run_now <schedule_id>` 返回 batch_id + 状态
- [ ] 3.1.6 `pause / resume / delete` 操作单 schedule
- [ ] 3.1.7 `runs <schedule_id?>` 显示运行历史 (Rich table)
- [ ] 3.1.8 `runs --limit 20` 默认 20 条
- [ ] 3.1.9 Rich 输出 (table + color: 绿色 ok, 红色 error)

## Phase 4 — 测试 (50+ tests, 目标 ≥ 80% 覆盖率)

### 4.1 `tests/test_scheduler.py` (~25 tests)

- [ ] 4.1.1 TestScheduleDataclass: to_dict / from_dict / round_trip
- [ ] 4.1.2 TestScheduleValidate: 空 name / 空 cron / invalid cron / valid
- [ ] 4.1.3 TestScheduleNextRunAt: 5 个 helper cron 验证下次时间
- [ ] 4.1.4 TestSchedulerSingleton: 双调用 get_instance 返回同一对象
- [ ] 4.1.5 TestSchedulerLoadSave: 写入 → 读取一致
- [ ] 4.1.6 TestSchedulerFileLock: 并发写不破坏 JSON
- [ ] 4.1.7 TestSchedulerStartStop: 启停后 thread 状态
- [ ] 4.1.8 TestSchedulerCRUD: add / list / get / update / delete
- [ ] 4.1.9 TestSchedulerPauseResume: pause 后 _tick 不跑, resume 后跑
- [ ] 4.1.10 TestSchedulerRunNow: 立即跑 + 返回 batch_id
- [ ] 4.1.11 TestSchedulerTick: 模拟 tick 该跑的时间, 验证 _run_schedule 被调
- [ ] 4.1.12 TestSchedulerTickNotRun: 不该跑的时间, 验证 _run_schedule 不被调
- [ ] 4.1.13 TestSchedulerLoadTickersPortfolio: mock portfolio_store 拉 ticker
- [ ] 4.1.14 TestSchedulerLoadTickersWatchlist: mock watchlist 拉 ticker
- [ ] 4.1.15 TestSchedulerLoadTickersManual: 读 source_config.tickers
- [ ] 4.1.16 TestSchedulerRunCreatesBatch: 调 job_queue.create_batch + submit
- [ ] 4.1.17 TestSchedulerOnComplete: 模拟 batch 完成, 验证通知 + _append_run
- [ ] 4.1.18 TestSchedulerNotifyFailureDoesNotCrash: 1 channel 失败不影响 scheduler
- [ ] 4.1.19 TestSchedulerPruneOldRuns: 30 天前 run 被删
- [ ] 4.1.20 TestSchedulerPersistsAcrossRestart: 模拟重启, 验证 schedule 还在
- [ ] 4.1.21 TestSchedulerThreading: 多线程 add / list 不破坏
- [ ] 4.1.22 TestSchedulerPresets: install 时创建 2 个预置
- [ ] 4.1.23 TestSchedulerManualSourceValidation: manual 源无 tickers 报错
- [ ] 4.1.24 TestSchedulerNotifyChannels: 4 channel 都启用 / 部分启用

### 4.2 `tests/test_watchlist.py` (~10 tests)

- [ ] 4.2.1 TestWatchEntry: to_dict / from_dict
- [ ] 4.2.2 TestWatchlistStoreSingleton
- [ ] 4.2.3 TestAddValid: ticker 6 位 + tag 合法
- [ ] 4.2.4 TestAddInvalidTicker: 非 6 位 raise
- [ ] 4.2.5 TestAddInvalidTag: tag 不在 VALID_TAGS raise
- [ ] 4.2.6 TestRemove: entry_id 存在 → 删除, 不存在 → False
- [ ] 4.2.7 TestListAll: 多个 entry 全部返回
- [ ] 4.2.8 TestListByTag: tag 过滤
- [ ] 4.2.9 TestPersistence: 写入 → 重启 → 一致
- [ ] 4.2.10 TestThreading: 并发 add 安全

### 4.3 `tests/test_notifier.py` (~10 tests)

- [ ] 4.3.1 TestChannelEnum: 4 个值
- [ ] 4.3.2 TestNotifierRender: Jinja2 模板渲染 (summary / duration 替换)
- [ ] 4.3.3 TestNotifierSendLog: log channel 写 logger
- [ ] 4.3.4 TestNotifierSendWeCom: mock requests.post 验证 URL + payload
- [ ] 4.3.5 TestNotifierSendEmail: mock smtplib
- [ ] 4.3.6 TestNotifierSendDesktop: mock subprocess
- [ ] 4.3.7 TestNotifierFailureDoesNotPropagate: 1 channel 失败 → send 返回 False
- [ ] 4.3.8 TestNotifierMultiChannel: 4 channel 都发
- [ ] 4.3.9 TestNotifierLoadConfig: 读 channels.yaml
- [ ] 4.3.10 TestNotifierNoConfig: 没 channels.yaml → log 仍工作

### 4.4 `tests/test_schedule_panel.py` (~10 tests)

- [ ] 4.4.1 TestRenderSchedulePanel: mock streamlit snapshot 4 段都渲染
- [ ] 4.4.2 TestScheduleList: 列表表格 5 列
- [ ] 4.4.3 TestAddScheduleDialog: 新增表单字段
- [ ] 4.4.4 TestEditScheduleDialog: 预填值
- [ ] 4.4.5 TestCronHelpers: 5 个 helper cron 字符串
- [ ] 4.4.6 TestCronValidation: invalid cron → 红字
- [ ] 4.4.7 TestNextRunPreview: croniter.get_next() 显示
- [ ] 4.4.8 TestPauseResumeButton: 行操作
- [ ] 4.4.9 TestDeleteConfirmation: 二次确认
- [ ] 4.4.10 TestEmptyState: 没 schedule 时提示

### 4.5 集成 / 回归

- [ ] 4.5.1 `python -m pytest tests/ -v` 全套 0 回归
- [ ] 4.5.2 `python -m pytest tests/test_scheduler.py tests/test_watchlist.py tests/test_notifier.py tests/test_schedule_panel.py --cov=backend.core.scheduler --cov=backend.core.watchlist --cov=backend.core.notifier --cov-fail-under=80` ≥ 80%

## Phase 5 — 文档与发布

### 5.1 `CLAUDE.md`

- [ ] 5.1.1 版本号升到 v0.6.0
- [ ] 5.1.2 在 "Agent 角色" 加 "定时分析 (v0.6.0 新增)" 一行
- [ ] 5.1.3 在 "关键路径" 加 4 个新文件 (scheduler / watchlist / notifier / schedule_panel)
- [ ] 5.1.4 在 "个人仓位模块" 段加 1 行 (v0.6.0 联动: portfolio ticker 自动分析)

### 5.2 `README.md`

- [ ] 5.2.1 功能列表加 "定时分析" 段
- [ ] 5.2.2 3-5 句话介绍 (cron / 配置页 / 通知 / CLI)

### 5.3 `CHANGELOG.md`

- [ ] 5.3.1 v0.6.0 entry (在 v0.5.0 前面)
  - Added: 定时分析模块 (scheduler + 配置页面 + watchlist + 通知)
  - Added: Schedule CRUD (cron + source + notify)
  - Added: WatchlistStore (自选股)
  - Added: Multi-channel notifier (WeCom / Email / Desktop / Log)
  - Added: CLI: `python -m cli.schedule list/add/pause/resume/run-now/delete`
  - Added: 5 个 cron helper (工作日 18:00 / 周一早 8:00 / 每天 9:30 / 每月 1 号 / 每 4 小时)
  - Added: st_autorefresh 10s 自动刷新 + 实时显示下次执行时间
  - Added: 50+ 测试, 覆盖率 ≥ 80%
  - Known Limitations: 单进程 (v0.7.0 分布式) / 时区硬编 Asia/Shanghai / 无导入导出 schedule (v0.7.0)

### 5.4 `pyproject.toml`

- [ ] 5.4.1 version: 0.5.0 → 0.6.0
- [ ] 5.4.2 dependencies 加 3 行: croniter, jinja2, streamlit-autorefresh
- [ ] 5.4.3 README 项目描述: 提一下 v0.6.0

### 5.5 Pre-merge Verification

- [ ] 5.5.1 pytest tests/ -v 全套 0 回归 (609 + 50+)
- [ ] 5.5.2 coverage ≥ 80% (scheduler / watchlist / notifier)
- [ ] 5.5.3 live test: 启动 streamlit → 看到 ⏰ 按钮 → 点 → 配置页 4 段都显示
- [ ] 5.5.4 live test: 新增 schedule "test" cron "* * * * *" → 1 分钟内跑 → 看 audit log
- [ ] 5.5.5 live test: 编辑 "test" cron → 改成 "0 12 * * *" → 保存 → 看到下次第 2 个 12 点跑
- [ ] 5.5.6 live test: 立即跑全部 → scheduler.run_now → streamlit 显示 batch_id
- [ ] 5.5.7 live test: 删除 "test" → 二次确认 → 删
- [ ] 5.5.8 live test: 启停调度器 → 看到 last_tick 暂停
- [ ] 5.5.9 CLI test: `python -m cli.schedule list` → 输出 schedule 列表
- [ ] 5.5.10 CLI test: `python -m cli.schedule add` → 新增 → list 看到
- [ ] 5.5.11 code-review: hardcoded secrets / SQL injection / error handling

## Phase 6 — (可选) v0.7.0 后续

- [ ] 6.1 分布式 (Redis / 跨进程 lock)
- [ ] 6.2 FastAPI `/api/schedules` REST 端点
- [ ] 6.3 导入/导出 schedule JSON
- [ ] 6.4 失败重试 (exponential backoff)
- [ ] 6.5 运行时长限制 (timeout)
- [ ] 6.6 多设备同步 (云)
- [ ] 6.7 时区切换 UI
- [ ] 6.8 自选股 tag 过滤 + 多 tag 组合
- [ ] 6.9 LLM 调度 (按 schedule 选不同 model)
- [ ] 6.10 通知模板高级自定义 (Jinja2 playground)
- [ ] 6.11 实时 SSE 推送进度到 streamlit
- [ ] 6.12 调度器 metrics 面板 (每 schedule 成功率 / 平均耗时)

## 阶段时间估算 (单 developer, spec-first 全流程)

| 阶段 | 估时 |
|---|---|
| Phase 1 (数据 + 通知) | 4-5h |
| Phase 2 (UI) | 4-5h |
| Phase 3 (CLI) | 1-2h |
| Phase 4 (测试) | 3-4h |
| Phase 5 (文档) | 1h |
| **总计** | **~14-17h = 2 个工作日** |

按之前 portfolio v0.5.0 节奏 (3 轮 claude + 中间补丁), 预计 **4 轮 claude**:
- Round 1: Phase 1 (数据 + 通知)
- Round 2: Phase 2 (UI)
- Round 3: Phase 3 (CLI) + Phase 4 (测试)
- Round 4: Phase 5 (文档)
