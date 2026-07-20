# Phase 3c 报告：LogStore + LogWriter SQLite 双写期

> **状态**：实现完成；JSONL 继续作为 LogStore 读源，SQLite 作为旁路写入与对账目标。
>
> **范围**：Phase 3c `LogStore + LogWriter` SQLite 旁路实现与双写 wrapper。没有切换 LogStore 读路径，也没有修改既有 `log_store.py`。
>
> **授权声明**：Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (Phase 3c LogStore SQLite + 双写期)

## 1. 新增文件

| 文件 | 作用 |
|---|---|
| `backend/core/log_store_sqlite.py` | `SQLiteLogStore` / `SQLiteLogWriter` 旁路实现；映射 `history`、`log_chunks`、`stage_reports`、`completed_stages`，并复用既有 `LogChunk` / `TaskSummary` 公共数据形状。 |
| `backend/core/log_store_dualwrite.py` | `DualWriteLogStore` / `DualWriteLogWriter` wrapper。读全部转发 JSONL，写分别尝试 JSON 与 SQLite，失败只 warning。 |
| `backend/core/log_store_dualwrite_runtime.py` | Phase 3c lifespan bootstrap。`DUAL_WRITE_LOGS=1` 时替换 JSON read singleton，并在已加载的 `web.runner` call-site 安装 writer factory；默认模式不启用。 |
| `tests/test_log_dual_write.py` | 临时 JSON/SQLite 根目录下的生命周期、读 API、读路由隔离、错误非致命、PRAGMA/FK 集成测试。 |
| `docs/PHASE3C_REPORT.md` | 本阶段实施与验收报告。 |

本阶段只有新增 Phase 3c 文件，以及 `backend/main.py` 增加 lifespan feature-flag 接线；没有修改受保护的 LogStore/HistoryStore/runner/web/frontend 文件。

## 2. 实施细节

### SQLite 旁路实现

- SQLite 文件默认使用 `~/.tradingagents/tradingagents.db`，可通过 `db_path` 注入测试数据库。
- 初始化运行幂等 schema migration，并在连接建立后一次性应用 WAL、NORMAL、busy timeout、foreign keys、cache/temp PRAGMA。
- 连接使用 `isolation_level=None`、`check_same_thread=False`；每个写操作使用 `BEGIN IMMEDIATE` + 显式 `COMMIT`，失败 rollback。
- `SQLiteLogWriter` 先保证 `history` parent row 存在，再写 `log_chunks`；每个 chunk 同时保留 `task_dir_name` 与 JSONL 的完整可比较字段，`input` 使用 JSON 文本存储。
- `_next_task_dir_name()` 按 ticker/date 已有 SQLite run 编号选择最大值加一。runtime factory 随后把 JSON writer 选出的 canonical task 目录名同步给 SQLite writer，避免双写期间两侧任务名漂移。
- `stream_chunks()` 按 `ts ASC, id ASC` 排序并支持 `llm` / `tool` / `agent_output` 过滤。

### 双写 wrapper 与启动接线

- `DualWriteLogStore` 的 `list_tickers`、`list_tasks`、`get_meta`、`count_chunks`、`stream_chunks` 全部走 JSONL。
- `DualWriteLogWriter` 对 append、stage update、finalize 分别独立尝试 JSON 与 SQLite；单侧异常记录 warning，另一侧继续执行。
- `DUAL_WRITE_LOGS=1` 时 `backend.main` lifespan 调用独立 bootstrap：JSON singleton 替换为 wrapper，并对已经 import 的 `web.runner.LogWriter` 绑定安装 factory。没有编辑 `backend/core/log_store.py` 或 caller 源码。
- lifespan 退出时恢复原 JSON singleton / writer binding，并关闭 SQLite sidecar 连接；这也使测试与重复 lifespan 更容易隔离。

## 3. 验收命令与结果

以下结果由 Hermes 在当前工作树实际运行后填写：

| 验收项 | 结果 |
|---|---|
| 新文件清单 / LOC | `backend/core/log_store_sqlite.py`、`backend/core/log_store_dualwrite.py`、`backend/core/log_store_dualwrite_runtime.py`、`tests/test_log_dual_write.py`、`docs/PHASE3C_REPORT.md`；实际 LOC 以 `wc -l` 输出为准。 |
| 双写集成测试 | 待最终验证命令完成后填写。 |
| 默认 pytest 回归 | 待最终验证命令完成后填写。 |
| JSONL + SQLite 0 drift | 集成测试比较 chunk canonical dict、analysis/ticker/date/status/signal/counts，并校验 JSON-only read routing；待最终验证命令完成后填写。 |
| protected runtime diff | `backend/core/log_store.py`、`backend/core/history_store.py`、`backend/core/runner.py`、`web/runner.py` 预期 diff 为 0。 |
| lifespan startup | `DUAL_WRITE_LOGS=1` 应输出 `LogStore dual-write enabled (jsonl + SQLite)`。待最终验证命令完成后填写。 |
| frontend typecheck | 使用 `npx tsc --noEmit`；待最终验证命令完成后填写。 |

## 4. 明确不做

- 不修改 `backend/core/log_store.py` 的任何现有实现、`get_log_store()` 单例函数或 `LogWriter` 类。
- 不修改 `backend/core/history_store.py`、`backend/core/runner.py`、`tracker.py`、`web/runner.py`、`web/components/*`、`backend/api/*`、`frontend/*`、`pyproject.toml`、spec 或既有测试。
- 不把 SQLite 设置为读源，不删除 JSONL/meta，不废弃 legacy logs。
- 不做 Phase 3d 的读切换、reconciliation daemon、SQLite-only 写入或 JSON 归档。
- 不 commit；Hermes 自己 commit + push。

## 5. 下一步（Phase 3d）

1. 连续观察 JSONL 与 SQLite chunk/meta 对账，记录失败率与 task/run 命名冲突。
2. 补充长期进程下的 connection lifecycle、重启、并发 run allocation 与 sidecar repair 观测。
3. 通过一周稳定对账后，再在独立变更中评估 LogStore 读路径切换，保留 JSON fallback。
4. 最后才计划 SQLite-only 写入和旧 JSONL 归档。
