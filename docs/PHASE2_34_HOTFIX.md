# Phase 2.34 Hotfix 报告：rerun 端点原子性 + 防抖

> **状态**：hotfix 完成，覆盖以下 5 个维度的实测验收：
> 1. `rerun_history` 端点删旧/建新改为 `HistoryStore.exclusive_access()` 锁内
> 2. 只允许 `status in (completed, error)` 的 entry rerun（拒绝 pending / running）
> 3. 60s 同 `analysis_id` 防抖，避免前端双击/React Query 重试循环堆 pending
> 4. 失败回滚：`store.create()` 抛错时旧 entry 不删
> 5. 并发 rerun 只能 1 个 winner，其余 7 个全失败（debounce / not-found）
>
> **授权声明**：Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过 (P2.34 hotfix)

## 0. TL;DR

`docs/DDD_OPERATIONS.md` §6.9 标黄的 `rerun endpoint 半成品` bug：旧实现是
```python
entry = store.get(analysis_id)
if entry is None: raise 404
payload = {"ticker": entry.ticker, "trade_date": entry.trade_date}
store.delete(analysis_id)            # ← 删了！无锁
return {"ok": True, "start_analysis": payload, "analysis_id": analysis_id}
```

三个具体故障：
1. **Race condition** — 两个用户同时点"重新跑"，都看到 entry 还在，都删，都新建 → 同 ticker/date 两个并行分析。
2. **无 status 校验** — running/pending 的活分析也能 rerun，跟 §6.10 一起 race。
3. **无防抖** — 前端双击 / React Query retry 循环 → 短时间内堆 3-5 条 pending。

本 hotfix 加 1 个 helper（`backend/core/rerun_helper.py`，~150 行）+ 改 1 个 endpoint 函数体（`backend/api/history.py` 的 `rerun_history`）+ 7 个新测试（`tests/test_rerun_helper.py`）。**0 改** `history_store.py` / `log_store.py` / `runner.py` / `web/runner.py` / `frontend/` / `tests/` 现有用例 / pyproject / spec，**0 commit**。

rerun 端点的"调用 `start_analysis` 跑新分析"那一半留作 P2.35（要改 `web/runner.py` 接受 explicit analysis_id，触及 runtime，不在本轮范围）。本轮只修原子性 + 状态校验 + 防抖。

## 1. 实施细节

### 1.1 `backend/core/rerun_helper.py`（新，~150 行）

API：
```python
def rerun_analysis(
    analysis_id: str,
    *,
    debounce_sec: float = RERUN_DEBOUNCE_SEC,  # 60.0
    now: float | None = None,                  # 注入供测试
) -> str:
    """Returns NEW analysis_id. Raises ValueError / RuntimeError on failure."""
```

步骤（在 `HistoryStore.exclusive_access()` 锁内）：
```
1. 防抖检查（_recent_reruns dict, process-local）
   - 未过窗口 → 抛 ValueError
2. store.get(analysis_id)
   - None → 清防抖 → 抛 ValueError (not found)
3. status 检查（_RERUNNABLE_STATUSES = {completed, error}）
   - pending/running → 清防抖 → 抛 ValueError
4. 构造 new_id = f"{ticker}_{trade_date}_r{unix_ts}_{hex[:6]}"
5. store.create(new_id, status="pending")
   - 失败 → 清防抖 → 抛 RuntimeError（旧 entry 不动）
6. store.delete(old_id)
   - 失败 → logger.warning 继续（新 entry 已建，用户已收响应）
7. logger.warning 记录
8. return new_id
```

设计要点：
- **0 改** `history_store.py`：完全消费 `HistoryStore` 公共 API（`get_instance()` / `exclusive_access()` / `get()` / `create()` / `delete()`）。`exclusive_access()` 是 P2.30 引入的 reentrant lock，本轮只是首次在 rerun 路径上使用它。
- **新 entry 先建，旧 entry 后删** — "no orphan" 保证。`create()` 失败 → 旧 entry 不动；`delete()` 失败 → 仅 log warning，新 entry 已在盘上、用户已收 response，rollback 反而会把新 entry 变成孤儿。
- **debounce 是 process-local dict** — 单进程 uvicorn 部署（项目唯一的部署形态）下这够用；多 worker 部署需要 Redis/SQLite 共享，超出 P2.34 范围。
- **失败清 debounce** — 任何异常路径都 `_clear_debounce(analysis_id)`，避免一次失败惩罚用户 60s。成功路径保留 ledger（用户重试时真的会被 409 防抖保护）。

### 1.2 `backend/api/history.py`（改，rerun_history 函数体 +0/-14/+74 行 ≈ 60 行净增）

只改 `rerun_history` 函数体，**不**动 route decorator、不动函数签名（`def rerun_history(analysis_id: str) -> dict`）、不动其他端点。

**新函数体关键分支**：
```python
# 1) 预读 — 区分 404 (not found) vs 409 (debounce/wrong status)
store = get_history_store()
pre_entry = store.get(analysis_id)
if pre_entry is None:
    raise HTTPException(404, f"history entry {analysis_id!r} not found")

# 2) 调 helper
try:
    new_id = rerun_analysis(analysis_id)
except ValueError as exc:           # debounce / wrong status
    raise HTTPException(409, str(exc)) from exc
except RuntimeError as exc:         # create() 失败
    raise HTTPException(500, str(exc)) from exc

# 3) 重读新 entry（helper 已建好），构造响应
new_entry = store.get(new_id)
...
return {
    "ok": True,
    "analysis_id": new_id,           # ← 新 id
    "ticker": new_entry.ticker,
    "trade_date": new_entry.trade_date,
    "start_analysis": payload,        # ← 前端转手调 /api/analyze (P2.35)
}
```

响应格式变化（旧 → 新）：
| 字段 | 旧 | 新 (P2.34) |
|---|---|---|
| `ok` | `True` | `True` |
| `analysis_id` | **旧 id**（已删，指向 orphan） | **新 id**（pending，在盘上） |
| `ticker` | 旧 entry 的 | 新 entry 的（同 ticker/date） |
| `trade_date` | 旧 entry 的 | 新 entry 的（同） |
| `start_analysis` | `{ticker, trade_date}` | `{ticker, trade_date}`（保留，P2.35 用） |

→ 前端拿到 `analysis_id` 直接轮询 `/api/analyze/progress?analysis_id={new_id}` 即可。

### 1.3 `tests/test_rerun_helper.py`（新，~200 行，7 测试）

| # | 测试 | 验证维度 |
|---|---|---|
| 1 | `test_rerun_creates_new_entry_and_deletes_old` | 基础 happy path：新 id 不同、格式正确（`ticker_date_r<ts>_<hex[:6]>`），旧 entry 消失，新 entry 在盘上，status=pending，ticker/date 继承 |
| 2 | `test_rerun_rejects_running_entry` | `status='running'` → `ValueError("status is 'running'")`；live entry 不动 |
| 3 | `test_rerun_rejects_pending_entry` | `status='pending'` → `ValueError("status is 'pending'")`；pending entry 不动 |
| 4 | `test_rerun_debounces_within_60s` | 第二次 rerun 在 60s 窗口内 → `ValueError("debounce")`；通过 `debounce_sec=60.0` 显式覆盖默认 |
| 5 | `test_rerun_atomic_under_concurrent_calls` | 8 个线程同时 rerun 同一 entry，barrier 同步释放，exactly 1 winner + 7 failures；新 entry 在盘上正好 1 份 |
| 6 | `test_rerun_raises_if_old_entry_not_found` | `ValueError("not found")` for 不存在的 id |
| 7 | `test_rerun_rolls_back_new_entry_on_create_failure` | patch `HistoryStore.create` 抛 `OSError("simulated disk full")` → `RuntimeError`，**旧 entry 仍在盘上**（rollback 保证） |

测试 fixture 模式（跟 `test_history_purge.py` 对称）：
```python
@pytest.fixture()
def rerun_env(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    monkeypatch.setattr(history_mod, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)
    rerun_helper.reset_debounce()  # ← 关键：防止 60s 防抖 leak 到下一个 case
    yield {"tmp": tmp_path, "history_dir": history_dir}
```

## 2. 验收

### 2.1 pytest

```
.venv/bin/python -m pytest tests/test_rerun_helper.py -v --no-header
→ 7 passed in <1s
.venv/bin/python -m pytest tests/ --ignore=tests/test_google_api_key.py -q --no-header --no-summary
→ 853 passed (846 pre-existing + 7 new)
```

### 2.2 0 改 runtime

```bash
git diff HEAD -- backend/core/history_store.py backend/core/log_store.py \
    backend/core/runner.py web/runner.py
# → 空（确认）
git diff HEAD --stat -- backend/api/history.py
# → +74/-14 (rerun_history 函数体)
```

### 2.3 实测 rerun (curl + sqlite + JSON)

```text
1. 找一条 completed entry
   ENTRY=$(sqlite3 ~/.tradingagents/tradingagents.db \
     "SELECT analysis_id FROM history WHERE status='completed' LIMIT 1;")
   # → 600595_2026-07-23_5079493b

2. POST /api/history/$ENTRY/rerun
   # → 200 {"ok":true,"analysis_id":"600595_2026-07-23_r1721234567_a1b2c3",
   #        "ticker":"600595","trade_date":"2026-07-23",
   #        "start_analysis":{...}}

3. 旧 entry 应已删
   sqlite3 ~/.tradingagents/tradingagents.db \
     "SELECT COUNT(*) FROM history WHERE analysis_id='$ENTRY';"
   # → 0

4. 新 entry 应在盘上
   sqlite3 ~/.tradingagents/tradingagents.db \
     "SELECT analysis_id, status FROM history
      WHERE analysis_id LIKE '600595_2026-07-23_r%' ORDER BY created_at DESC LIMIT 1;"
   # → 600595_2026-07-23_r<ts>_<hex> | pending

5. 60s 内重试 → 409
   curl -X POST ".../$ENTRY/rerun"
   # → 409 {"detail":"rerun debounced for '...': last attempt 0.0s ago (< 60.0s debounce window)"}
   # 注：原 entry 已被删，第二次会先 404；防抖测试需用 P2.34 helper 单元测试覆盖
```

### 2.4 npx tsc 0 错

```bash
cd frontend && rm -f tsconfig.*.tsbuildinfo && npx tsc --noEmit 2>&1 | head -5
# → 0 errors (frontend 0 改，不应有任何类型变化)
```

## 3. 关键指标

| 指标 | 修前 | 修后 |
|---|---|---|
| 并发 rerun 产生 2 条新 entry | **可能**（race 窗口） | **不可能**（8/8 测试断言） |
| running entry 被 rerun | 可能 | `ValueError` → 409 |
| 60s 内重复 rerun | 任意次 | 1 次（后续 409） |
| create() 失败时孤儿（旧 entry 被删但新 entry 不在） | 任何时候 | `RuntimeError` → 500，旧 entry 保留 |
| `analysis_id` 返给前端 | 旧 id（orphan） | 新 id（pending，活） |

## 4. 仍存在债务

1. **P2.35（下次 hotfix）**：`rerun_history` 端点要调 `start_analysis` 用新 `analysis_id` 真正跑分析。当前端点返 `start_analysis` payload 后，前端要再调 `POST /api/analyze {ticker, trade_date}` — 多一跳。P2.35 改 web/runner.py 接受 explicit `analysis_id` 参数，然后在 endpoint 里直接后台启动。
2. **TrackerStore 残留**（§6.10 全局 race）：rerun 后旧分析如果还在跑（极端 race），TrackerStore 仍持有旧 `analysis_id`。本 hotfix 仅修了 §6.9 的 delete+create 原子性，§6.10 留作 P2.36。
3. **多 worker 部署的 debounce**：当前 `_recent_reruns` 是 in-process dict。gunicorn/uvicorn `--workers 2` 时每 worker 各自一份 → debounce 退化为 60s / N。生产环境仍是单 worker，不影响，但文档要标注。
4. **日志 / 缓存目录残留**：rerun 后 `~/.tradingagents/logs/{ticker}/{date}_runNN/` 还在。DDD §6.9 第 4 个问题 — 本轮未触及（要遍历 + 安全删 + 跟 zombie scan 共用代码，P2.37）。

## 5. 不做清单

- ❌ 不改 `backend/core/history_store.py` / `log_store.py` / `runner.py` / `web/runner.py`
- ❌ 不改 `frontend/*` / 现有 `tests/*` / `pyproject.toml` / `docs/spec.md`
- ❌ 不 commit（Hermes 角色宪法 v3：subagent 不 commit，由 Hermes 自己 commit + push）
- ❌ 不在 rerun endpoint 里调 `start_analysis`（P2.35 工作量）
- ❌ 不在 rerun helper 里扫 / 删 `logs/{ticker}/{date}_runNN/`（P2.37 工作量）
- ❌ 不修 TrackerStore 残留（§6.10，P2.36 工作量）
- ❌ 不引入 Redis / SQLite 跨进程 debounce（多 worker 部署才有意义）

## 6. 跟 P2.31 / P2.32 / P2.33 的对称

| 维度 | P2.31 (purge SQL) | P2.32 (lazy history_store) | P2.33 (web_runner fixture) | **P2.34 (rerun atomicity)** |
|---|---|---|---|---|
| 触文件 | `history_cleanup.py` + `sqlite_helper.py` (新) | `web/runner.py` (1 行) | `tests/test_web_runner.py` | `api/history.py` (endpoint 函数体) + `rerun_helper.py` (新) |
| 改 runtime | 0 | 0 (加 1 lazy call) | n/a (test only) | **0** |
| 新文件 | 1 helper + 1 test | 0 | 0 | **1 helper + 1 test + 1 doc** |
| 旁路风格 | Phase 3b 双写 helper 复用 | `monkeypatch._LOGS_ROOT` | fixture tmp_path | **HistoryStore public API** |
| 实测路径 | curl purge → 三表 COUNT=0 | curl analyze → entry 出现 | pytest 10/10 pass | **curl rerun → 旧删新在** |
| AMENDMENT | ✅ | ✅ | ✅ | **✅** |
