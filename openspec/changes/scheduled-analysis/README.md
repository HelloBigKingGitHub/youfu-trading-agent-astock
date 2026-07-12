# 定时分析 v0.6.0 (Scheduled Analysis)

> v0.5.0 之上新增的"定时分析"模块 (Cron + ticker 源 + 通知)。
> 用户核心需求: 定时任务要有**配置页面**, 可**随时配置**相关信息。

## 核心特性 (5 个)

1. **配置页面优先** ⏰ — 整个 sidebar 第 9 按钮 = 调度 UI, 不是一次性 dialog
2. **3 种 ticker 源** — 持仓 (自动) / 自选股 (新) / 手动 (列表)
3. **5 个 cron helper** — 一键填入 "工作日 18:00" / "周一早 8:00" 等
4. **4 个通知渠道** — WeCom / Email / Desktop / Log (失败 fallback log)
5. **CLI + UI 双管理** — `python -m cli.schedule list/add/pause/resume/run-now/delete`

## 快速开始

```bash
# CLI
python -m cli.schedule list
python -m cli.schedule add --name "每日持仓复盘" --cron "0 18 * * 1-5" --source portfolio
python -m cli.schedule run-now <schedule_id>

# UI
streamlit run web/app.py  # 点 sidebar "⏰ 定时分析"
```

## 关键文件

| 路径 | 状态 |
|---|---|
| `backend/core/scheduler.py` | 350 行 (单例 + tick + CRUD) |
| `backend/core/watchlist.py` | 150 行 (自选股) |
| `backend/core/notifier.py` | 200 行 (4 channel) |
| `cli/schedule.py` | 180 行 (Typer) |
| `web/components/schedule_panel.py` | 280 行 (主页面 4 段) |
| `web/components/schedule_dialogs.py` | 220 行 (新增/编辑) |
| 改 `web/app.py` | +30 行 (NAV_ITEMS + dispatch) |
| 改 `web/styles/elements.css` | +80 行 (.bb-schedule-* 类) |
| 4 个测试文件 | 750 行 (50+ tests) |

## 新依赖

- `croniter>=3.0.0` (cron 解析)
- `jinja2>=3.1.0` (通知模板)
- `streamlit-autorefresh>=1.0.1` (10s 自动刷新)

## 详见

- `proposal.md` — Why / What / Non-goals / Capabilities / Impact
- `design.md` — Context / Goals / Decisions (8) / Architecture / File-by-File
- `tasks.md` — Phase 1-5 (50+ checkboxes) + Phase 6 (v0.7.0 后续)
