# History Page Parity Gate P2.2.P1

## 5 维度结果
- data_hash: `5ff72eacc0f680608814ce6e60245078`
- data_count: `50` entries (parity check reads the same canonical history directory and applies the 50-entry page cap)
- visual_diff (raw AE): `4.62%` (`1600x900` viewport; React `<main>` with SPA header hidden vs Streamlit viewport)
- structural_diff: `0.00%` (5 子项：identity / table_columns / table_rows / action_header / computed_style)
- perf_ms: `history_FastAPI=7.98ms history_React=3.51ms history_Streamlit=3.17ms` (same run also emitted settings: `settings_FastAPI=11.42ms settings_React=3.69ms settings_Streamlit=3.13ms`)
- fault_diff_history: React shows `加载历史失败` with `GET /api/history 422` and the invalid-integer detail; Streamlit remains on its own legacy history rendering and has no corresponding injected FastAPI fault text. The API fault itself is confirmed as HTTP `422` for `GET /api/history?limit=invalid`.

### Visual gate interpretation
Raw pixel AE is above 1% because the React Bloomberg layout and legacy Streamlit layout/rendering engine intentionally differ. The structural fallback is `0.00%`, so the page contract passes under the documented Phase 2 tolerance without changing Streamlit rendering or business code.

## Streamlit 同等性
- Streamlit 8501: `/tmp/streamlit_history_page.png`, md5 `d781663942ab06603ad332b4fdc73f30`
- React 5173: `/tmp/react_history_page.png`, md5 `77e4ab75c8304a144f24c0d0272a88fc`
- Diff heatmap: `/tmp/history_visual_diff.png`

## P2.2.P1 Gate 5 步
- [x] Step 1 Patch (8 新 + 2 改 + 1 后端扩；本轮另扩展 `parity_perf.py`、`parity_fault_inject.py` 为注册表模式，并补充 frontend test harness 兼容性)
- [x] Step 2 Verify (4 parity 脚本 + pytest + npm build + Playwright + Vitest)
- [ ] Step 3 用户确认 - **等用户文字回复 "✅ history parity 通过"**
- [x] Step 4 记录 (本文档)
- [ ] Step 5 进下一步 (P2.3 日志, 等 P2.2 用户文字确认后)

## 测试结果
- 后端 smoke：`/api/health` 返回 `{"status":"ok"}`；`/api/history?status=completed&limit=2` 返回 HTTP 200、`total=30`、2 条记录。
- pytest：`759 passed, 2 skipped, 1 warning, 44 subtests passed in 7.35s` ✅，命令按要求忽略 `tests/test_google_api_key.py`。实际 collection 比用户期望的 757 多 2 个通过测试；没有失败。
- npm run build：成功，`1651 modules transformed` ✅
- Playwright：`3 passed`（history 2 + settings 回归 1）✅
- Vitest：`2 test files passed / 6 tests passed` ✅（`env -u NODE_ENV ./node_modules/.bin/vitest run --reporter=default`；`--reporter=line` 在当前 Vitest 2.1.9 中会将 `line` 当作缺失的自定义 reporter，已改用内置 default reporter）
- 4 parity 脚本：4/4 命令成功 ✅
  - `parity_check.py --page history`: `data_hash=5ff72eacc0f680608814ce6e60245078`, `data_count=50`
  - `parity_visual.py --page history`: raw `visual_diff=4.62%`, structural `0.00%`
  - `parity_perf.py --page history`: settings + history 六个 probe 均 HTTP 200，并输出一次性 `perf_ms` 行
  - `parity_fault_inject.py --page history`: settings + history 两条 fault 均完成；history API HTTP 422，并输出 `fault_diff_history`
- 2 screenshots：均存在，已由 `/tmp/snap_history.mjs` 实际生成并校验 md5 ✅

## 不删 streamlit (硬约束)
任何 P*.P1 ❌ → Phase 2 不算完成 → Phase 3 不删 streamlit。
当前 P2.2 history parity 的结构门禁与功能验证跑通，Streamlit 8501 继续跑作为 fallback。

## 端口状态
本次报告生成时三个服务仍在运行：
- `127.0.0.1:8000` FastAPI / uvicorn（PID `3136312`）
- `0.0.0.0:5173` React / Vite（PID `2999965`）
- `0.0.0.0:8501` Streamlit（PID `3141907`；Streamlit hot-reload 可能更换 Python PID）

## 改动与边界
- 本轮实际修改：`scripts/parity_perf.py`、`scripts/parity_fault_inject.py`；为让既有 history unit harness 在 `useQuery` 轻量 mock 下可验证，保留了 history row test-id 修正和 `HistoryPage` 搜索 warm-up；`frontend/vitest.config.ts` 排除 e2e 文件，避免 Vitest 误收 Playwright spec。
- 未修改：`backend/core/history_store.py`、`web/components/history_panel.py`、`pyproject.toml`、openspec spec 文件、既有 pytest 文件。
- 未修改业务逻辑；未删除 Streamlit；**不 commit（hermes 手动）**。

---

**Step 3 用户确认 - 等用户文字回复 `✅ history parity 通过`**
