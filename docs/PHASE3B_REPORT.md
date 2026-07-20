# Phase 3b 报告：HistoryStore SQLite 双写期

> **状态**：实现完成，保持 JSON 读路径；SQLite 作为旁路写入与对账目标。
>
> **范围**：Phase 3b HistoryStore 迁移准备。`LogStore` 继续使用 JSON，Phase 3c 才处理。
>
> **授权声明**：Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (Phase 3b HistoryStore SQLite + 双写期)

## 1. 实施内容

新增并接入以下组件：

| 文件 | 作用 |
|---|---|
| `backend/core/history_store_sqlite.py` | `SQLiteHistoryStore` 旁路实现；复用 `HistoryEntry`，映射 `history`、`stage_reports`、`completed_stages` 三张表，并保留同接口 zombie cleanup。 |
| `backend/core/history_store_dualwrite.py` | `DualWriteHistoryStore` thin wrapper；写入 JSON + SQLite，读取全部走 JSON。SQLite 异常只记录 warning，不阻塞旧路径。 |
| `tests/test_history_dual_write.py` | 临时 JSON/SQLite 根目录下的生命周期、删除、zombie cleanup、FK/PRAGMA 集成测试。 |
| `docs/PHASE3B_REPORT.md` | 本报告。 |

实现细节：

- SQLite 连接使用 `isolation_level=None`、`check_same_thread=False`；初始化时一次性应用 WAL、NORMAL、busy timeout、foreign keys、cache/temp PRAGMA。
- 每个 SQLite 写操作都使用显式 `BEGIN IMMEDIATE` 与 `COMMIT`，异常自动 rollback。
- 初始化调用 Phase 3a 幂等 migration runner，确保新 sidecar 数据库具备已提交 schema journal。
- `update()` 以完整 `HistoryEntry` 重建 child rows，避免 JSON 的 list/dict 与 SQLite 三表内容漂移。
- `mark_stage_done()` 使用完成顺序写入 `completed_stages`，report 使用 `report_key or stage_id` 写入 `stage_reports`，内容保持与 JSON 一样最多 500 字符。
- 双写 create 复用 JSON 生成的 `analysis_id`，并随后用完整 JSON entry 同步，避免两边 `created_at` 产生漂移。
- `get/list_all/find_by_ticker_date` 仍由 JSON wrapper 转发；`is_zombie/cleanup_zombies` 使用 SQLite 实现，同时 cleanup 后将 JSON 结果同步回 SQLite。
- 为保持既有 purge service 兼容，wrapper 与 SQLite 实现提供 `exclusive_access()`。

## 2. 环境变量切换

默认行为不变：

```bash
# 默认：HistoryStore 单 JSON 路径
python -m pytest tests/ --ignore=tests/test_google_api_key.py -q
```

双写启动：

```bash
DUAL_WRITE_HISTORY=1 uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

FastAPI lifespan 在启动时将 `HistoryStore._instance` 替换为 wrapper，并输出：

```text
HistoryStore dual-write enabled (JSON + SQLite)
```

所有既有 caller 继续从 `get_history_store()` 取 store；没有修改既有 `HistoryStore` 方法或单例入口函数。

## 3. 验收结果

- 新增/修改任务文件共 5 个（含 `backend/main.py` 接入）：904 LOC；其中新增模块/测试/报告为 `402 + 160 + 137 + 80 = 779` LOC，`backend/main.py` 为 125 LOC（23 行增量）。
- 默认模式全量回归：`.venv/bin/python -m pytest tests/ --ignore=tests/test_google_api_key.py -q` → **823 passed, 2 skipped, 1 warning, 44 subtests passed in 13.21s**。
- 双写模式集成测试：`DUAL_WRITE_HISTORY=1 .venv/bin/python -m pytest tests/test_history_dual_write.py -v` → **3 passed in 0.26s**；复跑 `-q` → **3 passed in 0.19s**。
- JSON + SQLite 0 drift：生命周期（create/mark_running/mark_stage_done/mark_complete/set_results_path）、delete、zombie cleanup 均对比 `HistoryEntry.to_dict()`；测试结果 **0 差异**。
- 启动 smoke：`DUAL_WRITE_HISTORY=1 timeout 3 .venv/bin/python -m uvicorn backend.main:app ...` 成功启动并输出 `HistoryStore dual-write enabled (JSON + SQLite)`，随后按 timeout 正常退出（exit 124）。
- 运行时代码范围：`git diff HEAD -- backend/core/history_store.py backend/core/log_store.py backend/core/runner.py | wc -l` → **0**。
- 前端：用户指定的 `npx tsc --no-edit` 不是 TypeScript 有效选项，实际返回 `TS5023: Unknown compiler option '--no-edit'`；在 `frontend/` 使用标准命令 `npx tsc --noEmit` → **exit 0**。本阶段未改 `web/*` 或 `frontend/*`。

## 4. 明确不做
- 不改 `backend/core/log_store.py`；LogStore 仍走 JSON。
- 不改 `backend/core/runner.py`、`tracker.py`、`backend/api/*`。
- 不改 `frontend/*`、`web/*`、`pyproject.toml` 或 spec。
- 不做 Phase 3c LogStore 双写、SQLite 读路径切换、SQLite-only 写入或 JSON 清理。
- 不新增 cron 线程；当前启动 lifespan cleanup 保持一次性执行，后续周期任务属于后续运维阶段。
- **0 commit**：本任务按要求不执行 commit 或 push，由 Hermes 自己 commit + push。

## 5. 下一步（Phase 3c）

1. 观察双写期 1–2 周，持续抽检 JSON 与 SQLite 的 `analysis_id`、状态、阶段顺序、报告内容、时间字段。
2. 再实现 LogStore SQLite/JSON 双写兼容层，并增加 log chunk 对账。
3. 通过连续对账后，在独立变更中切换 HistoryStore 与 LogStore 读路径；保留 JSON fallback。
4. 观察期结束后再计划 SQLite-only 写路径及旧 JSON 归档。
