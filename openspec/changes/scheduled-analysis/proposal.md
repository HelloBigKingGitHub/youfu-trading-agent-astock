# 定时分析模块 v0.6.0 — Proposal (Why / What / Non-goals / Capabilities / Impact)

## Why

**问题**：

1. **手动重复操作** —— 你要每天/每周手动跑同一组 ticker 的分析（持仓复盘、自选股监控），**易忘 / 费时**。
2. **没有"自动复盘"机制** —— Bull/Bear 信号变了，没法自动通知，只能你手动点。
3. **没有"事件驱动"提醒** —— 现在分析跑完只能你自己看 streamlit 页面（不一定开着）。
4. **portfolio 联动缺失** —— v0.5.0 加了"我的仓位"，但"持仓的 ticker 能不能自动每天分析一次"做不到。

**现状**：

- v0.5.0 已有 `backend/core/job_queue.py` 做批量任务调度（threading + ThreadPoolExecutor）
- v0.5.0 已有 `web/components/batch_panel.py` 手动批量 UI
- **缺一层**："什么时候跑" (scheduler / cron)

**调研 4 个国内竞品**（已在前置 spec 写过）：

| 竞品 | 定时分析 | 通知 |
|---|---|---|
| 东方财富 | 智能盯盘（条件单） | App push + 微信 |
| 雪球 | 自选股动态 | App push |
| 腾讯自选股 | 价格预警 | 微信 + 短信 |
| 有知有行 | 周报月报（邮件） | 邮件 |

**共同短板**：都是 **券商 App 锁定**，不支持任意 LLM 模型 + 自由 ticker 源。

**差异化**：本模块 = **A 股投研生态的 cron 调度**，**用户自填 ticker + 自由 LLM 模型 + 多通知渠道 + 完全可配置 UI**。

## What Changes

### 新增 6 个模块 + 改 3 个文件

| 路径 | 估时 | 说明 |
|---|---|---|
| `backend/core/scheduler.py` | 350 | Scheduler + Schedule + ScheduleRun dataclass + 后台 thread + tick |
| `backend/core/watchlist.py` | 150 | WatchlistStore + CRUD (自选股) |
| `backend/core/notifier.py` | 200 | 4 channel (WeCom / Email / Desktop / Log) + 模板渲染 |
| `cli/schedule.py` | 180 | Typer CLI (list/add/pause/resume/run-now/delete) |
| `web/components/schedule_panel.py` | 280 | streamlit 主页 (4 段布局) |
| `web/components/schedule_dialogs.py` | 220 | 新增/编辑 dialog (cron picker + 表单) |
| 改 `web/app.py` | +30 | NAV_ITEMS 第 9 个, view dispatch |
| 改 `web/components/sidebar.py` | +5 | sidebar 链接到新面板 |
| 改 `web/styles/elements.css` | +80 | `.bb-schedule-*` 类 |

### 新增 4 个测试文件

- `tests/test_scheduler.py` (300 行, ~25 tests)
- `tests/test_watchlist.py` (100 行, ~10 tests)
- `tests/test_notifier.py` (150 行, ~10 tests)
- `tests/test_schedule_panel.py` (200 行, ~10 tests)

**总计 ~2200 行新代码 + ~750 行测试** (类比 portfolio v0.5.0 = 3000 行)

### 新增 3 个依赖

```toml
"croniter>=3.0.0",     # cron 解析
"jinja2>=3.1.0",       # 通知模板
"streamlit-autorefresh>=1.0.1",  # 10s 自动刷新 UI
```

### 预置 2 个 schedule (v0.6.0 launch)

| 名称 | cron | 源 | 启用 | 备注 |
|---|---|---|---|---|
| 每日持仓复盘 | `0 18 * * 1-5` | portfolio | ✅ | 工作日 18:00 跑持仓 |
| 周一前瞻 | `0 8 * * 1` | portfolio | ❌ | 用户手动启用 |

## Non-Goals (本 v0.6.0 不做)

- ❌ **实盘** (零券商 API 接入，与现有零-cookie 原则一致)
- ❌ **分布式** (单进程, 跨进程用文件 lock)
- ❌ **时区切换 UI** (硬编 Asia/Shanghai)
- ❌ **导入/导出 schedule JSON** (v0.7.0)
- ❌ **FastAPI `/api/schedules` REST** (v0.7.0, 现有 batch 有, 但 schedule 不暴露)
- ❌ **多设备同步** (v0.7.0)
- ❌ **失败重试** (v0.7.0, 加 backoff)
- ❌ **运行时长限制** (v0.7.0, 加 timeout)
- ❌ **依赖 watchlist v0.6.0 没 watchlist_tag 过滤** (v0.7.0)

## Capabilities (v0.6.0 必须)

### C1: Schedule CRUD (后端)
- 添加 / 编辑 / 启停 / 删除 / 立即跑
- 持久化 `~/.tradingagents/schedules/schedules.json`
- 单例 + 跨进程文件 lock

### C2: Watchlist CRUD (后端)
- 添加 / 列表 / 删除
- 标签分类 ("长线" / "短线" / "观察")
- 持久化 `~/.tradingagents/watchlist.json`

### C3: 调度引擎 (后端)
- 1 分钟 polling
- croniter 算下次执行
- 触发时拉 ticker 源 → create_batch + submit
- 注册完成回调 → 通知

### C4: 通知 (后端)
- 4 channel: WeCom (webhook) / Email (SMTP) / Desktop toast / Log only
- Jinja2 模板渲染
- 失败 fallback (channel down 不会让 scheduler 挂)

### C5: 配置 UI (前端 - 核心!)
- 整个 ⏰ 页面 = 配置 + 状态 + 历史
- 4 段布局: 列表 / 新增编辑 / 历史 / 全局
- 行内 inline edit + dialog 弹窗
- st_autorefresh 10s 自动刷新
- 5 个预置 cron helper (一键填入)
- 实时显示 "下次执行时间"

### C6: CLI
- `python -m cli.schedule list`
- `python -m cli.schedule add --name "..." --cron "0 18 * * 1-5" --source portfolio`
- `python -m cli.schedule run-now <id>`
- `python -m cli.schedule pause/resume/delete <id>`

### C7: 与 portfolio 联动
- scheduler 跑 portfolio 源时, 调 `PortfolioStore.get_instance().list_positions()` 拉 ticker
- 复用 portfolio 已有 RLock (不重复锁)

### C8: 运行历史 (审计)
- `~/.tradingagents/schedules/runs/2026-07-10.jsonl` (按天分文件)
- 30 天后自动清理

## Impact (影响现有代码)

| 现有文件 | 改动 |
|---|---|
| `web/app.py` | +1 NAV_ITEMS 行 + 1 view dispatch 行 (不破坏现有) |
| `web/components/sidebar.py` | 改 1 个 import 顺序 (无功能影响) |
| `web/styles/elements.css` | +80 行 `.bb-schedule-*` 类 (新增, 不动现有) |
| `pyproject.toml` | +3 deps (新) |
| `backend/core/job_queue.py` | 改 0 行 (v0.6.0 scheduler 复用 v0.5.0 job_queue) |
| `backend/core/portfolio_store.py` | 改 0 行 (复用 RLock + list_positions) |

**零破坏性** —— 现有 v0.5.0 所有 304 portfolio tests + 609 总 tests 不改一行也通过。
