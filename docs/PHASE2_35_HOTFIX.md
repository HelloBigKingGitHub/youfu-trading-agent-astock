# Phase 2.35 Hotfix 报告：rerun 创建后立即启动

> **状态**：代码与自动化验收完成；当前 8000 端口进程未 reload，live curl 仍表现为 P2.34 pending 语义。
>
> **授权声明**：Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (P2.35 hotfix 收尾)

## 0. TL;DR

P2.34 已保证 rerun 的原子替换、状态校验和 60 秒防抖，
但只创建 pending history entry，没有真正调用 `start_analysis`。

P2.35 把两段动作串成一个 helper：

1. 原子 rerun，得到 helper 临时 entry；
2. 读取旧任务 ticker / trade_date；
3. 构造 `AnalyzeRequest`；
4. 调用 `start_analysis`；
5. 返回真正 live analysis id；
6. 清理 helper 临时 entry；
7. endpoint 直接返回启动结果。

本次收尾只修测试 fixture：

- 移除 `HistoryStore.create(..., error=...)` 非法参数；
- 让 mocked `start_analysis` 模拟真实函数创建 running history entry；
- 不修改 runtime；
- 新增本报告；
- 目标测试 7/7 通过；
- 全量测试 860 passed，2 skipped；
- TypeScript `tsc --noEmit` exit 0。

## 1. 实施细节

### 1.1 `rerun_and_start`

P2.35 主体已由前序 subagent 完成，入口位于：

```text
backend/core/rerun_helper.py
```

职责边界：

- 复用 P2.34 `rerun_analysis`；
- 不扩展 `HistoryStore.create`；
- 不修改 protected runtime store；
- 从旧 entry 继承 ticker / trade_date；
- 接收可选 LLM override config；
- 调用统一 `backend.core.start_analysis`；
- 返回 endpoint 可直接透传的结构化 payload。

成功响应字段：

```text
ok
analysis_id
ticker
trade_date
start_analysis
```

其中 `analysis_id` 应是 `start_analysis` 返回的 live id，
而不是 P2.34 helper 的 `_r<timestamp>_<hex>` 临时 id。

### 1.2 endpoint 改动

P2.35 前序改动已位于：

```text
backend/api/history.py
```

endpoint 从“仅 rerun 建 pending entry”改为调用：

```text
rerun_and_start(analysis_id)
```

错误映射继续保留：

- 不存在旧 entry：404；
- 状态不允许或 debounce：409；
- 启动失败：按 helper 异常语义返回；
- 成功：200 + live analysis id。

本次收尾没有叠加修改该文件。

### 1.3 测试 fixture 修复

文件：

```text
tests/test_rerun_and_start.py
```

第一处修复：删除无效参数：

```text
error="previous run failed"
```

原因是 `HistoryStore.create` 的真实签名仅接受：

```text
ticker, trade_date, status, analysis_id
```

测试仍用 `status="error"` 表达旧任务失败状态，
不要求 store 在 create 阶段写 error message。

第二处修复：目标测试暴露 fixture 与真实行为不一致。
mocked `start_analysis` 原先只返回 `(live_id, tracker)`，
没有模拟真实 `start_analysis` 创建 running history entry 的副作用。

因此 helper 正确清理临时 entry 后，测试 store 为空，
`test_rerun_creates_new_entry_and_marks_running` 得到 0 条而非 1 条。

fixture 现模拟真实契约：

- 生成 canonical live id；
- 用相同 ticker / trade_date 创建 history entry；
- status 设置为 running；
- 返回 `(live_id, tracker)`。

这属于测试 mock 修复，不是 runtime 逻辑修改。

### 1.4 七个测试覆盖

1. 创建新 entry 并进入 running；
2. LLM config 正确传播；
3. ticker / trade_date 从旧 entry 传播；
4. 60 秒 debounce 仍返回冲突；
5. running 旧 entry 仍被拒绝；
6. `start_analysis` 异常继续传播；
7. rerun 日志包含 old id 与 new id。

## 2. 验收

### V1 — Git 基线

```text
git HEAD: 456b499
```

结果：符合任务指定基线。

### V2 — P2.35 目标测试

```text
7 passed, 1 warning in 0.27s
```

结果：7/7 通过。

warning 是 Starlette/httpx 兼容性 deprecation，
与本 hotfix 无关。

### V3 — 全量 pytest

命令：

```text
.venv/bin/python -m pytest tests/ --ignore=tests/test_google_api_key.py -q --no-header --no-summary
```

结果：

```text
860 passed, 2 skipped, 1 warning, 44 subtests passed in 12.54s
```

结论：0 pytest 回归。

### V4 — Protected runtime diff

检查：

```text
backend/core/history_store.py
backend/core/log_store.py
backend/core/runner.py
web/runner.py
```

结果：

```text
0 diff lines
```

结论：本轮 0 改 protected runtime。

### V5 — backend/api/history.py

本轮没有修改该文件。

相对 HEAD 的现有 P2.35 工作树 diff 为 133 行，
来源于前序 subagent 主体实现，未在收尾阶段叠加。

### V6 — TypeScript

命令：

```text
cd frontend
rm -f tsconfig.*.tsbuildinfo
npx tsc --noEmit
```

结果：exit 0，stdout 为空，0 errors。

### V7 — Live rerun curl

实际选择 error entry：

```text
600595_2026-07-17_f4b536fc
```

POST 返回 200，新 entry 确实创建：

```text
analysis_id=600595_2026-07-17_r1784865168_70c90a
```

3 秒后 `/api/analyze/recent?limit=2` 可见该新 entry，
但状态为 `pending`，不是 `running`。

响应仍含 P2.34 风格 `_r<timestamp>_<hex>` id，
说明 8000 端口当前进程未 reload 工作树中的 P2.35 endpoint/helper。

结论：

- 新 entry：✅ 真有；
- HTTP 200：✅；
- 当前进程真在跑：❌ 未证实，观测为 pending；
- 代码级目标测试：✅ mocked start contract 下 running；
- 后续需由 Hermes reload 服务后重跑 live curl。

### V8 — 文档与 commit

```text
docs/PHASE2_35_HOTFIX.md
```

文档已创建。

本轮 0 commit，0 push。

## 3. 关键成功指标

| 指标 | 验收结果 |
|---|---|
| 目标测试 | 7/7 passed |
| 全量测试 | 860 passed，2 skipped |
| pytest 回归 | 0 |
| protected runtime diff | 0 行 |
| TypeScript | 0 errors |
| 非法 `error=` kwarg | 已移除 |
| fixture 模拟 running entry | 已修复 |
| endpoint 工作树实现 | 已存在 |
| live 新 entry | 已创建 |
| live running | 当前旧进程未 reload，待复验 |
| commit | 0 |

## 4. 仍存在债务

1. 当前 8000 端口服务需要 reload，才能验证 P2.35 工作树代码。
2. live 环境缺少 LLM key 时，running 可能很快转为 error；验收应观察启动瞬间或日志。
3. debounce 仍为 process-local，多 worker 部署不共享。
4. helper 临时 entry 与 live entry 的清理依赖启动返回时序。
5. Starlette/httpx deprecation warning 尚未处理，且不属于本轮范围。

## 5. 不做清单

- 不改 `backend/core/history_store.py`；
- 不改 `backend/core/log_store.py`；
- 不改 `backend/core/runner.py`；
- 不改 `web/runner.py`；
- 不改 `backend/api/history.py`；
- 不给 `HistoryStore.create` 增加 `error` 参数；
- 不改 frontend source；
- 不改 pyproject；
- 不改 spec；
- 不改其它测试；
- 不 commit；
- 不 push。

## 6. AMENDMENT-PHASE2-AUTOPILOT 授权

Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (P2.35 hotfix 收尾)

自动通过依据：

- 目标测试 7 passed；
- 全量测试 860 passed；
- protected runtime 0 diff；
- TypeScript 0 errors；
- 文档已创建；
- 收尾阶段 0 commit。

live curl 的 running 条件需在服务 reload 后复验；
在复验为 running 或快速 error（并有明确 worker 启动证据）前，
不得把“当前 8000 进程真在跑”写成已通过。
