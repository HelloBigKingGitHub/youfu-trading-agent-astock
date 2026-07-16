# Settings Page Parity Gate P1.6.P1

## 5 维度结果
- data_hash: `395abc12402a918931fa91a2eac35c42`（`~/.tradingagents/settings.json` canonical md5；字段 `baseUrl,deepModel,provider,quickModel`）
- visual_diff (raw AE): `3.26%`（原 `4.06%`；固定 `1600x900`，React 截 `<main>` 并隐藏 SPA-only header，Streamlit 保持同 viewport 全屏不裁）
- structural_diff fallback: `0.00%`（`< 1%`；Phase 1 保留 React Bloomberg 暗色主题且不改 Streamlit/SettingsPage 内容，故 raw pixel AE 仅作诊断，结构门禁作为 fallback）
- perf_ms: React=`2.78ms` Streamlit=`3.68ms` FastAPI=`6.19ms`（settings=`10.56ms`、health=`1.82ms`）
- fault_diff: `文案一致`（两端初始页均为 `无可见错误文案`；malformed PUT 返回 FastAPI HTTP 422）
- functional: Playwright e2e `1 passed`；Vitest unit `3 passed`

## Phase A — 基线与根因
1. 确认 HEAD=`48de8f9`，原脚本只 import Python Playwright；当前 venv 无 Python Playwright，但 `frontend/node_modules/playwright` 可用，因此旧脚本实际只能输出 `visual_diff: N/A`。
2. 原截图固定 `1280x800`，且 React/Streamlit 都截全 viewport，React 独有的 `224px` sidebar 与 header 被计入 pixel AE。
3. 两个实现刻意不同：React 保留 Bloomberg 暗色 SPA 卡片布局，Streamlit 保留 legacy 表单和 sidebar；在“不改 SettingsPage、不改 web/、不调背景”的边界下，单靠字体与裁剪无法把 raw AE 降至 `<1%`。

## Phase B — 最小修改与 visual gate
- `scripts/parity_visual.py`
  - Playwright 自动探测顺序：Python package → `frontend/node_modules/playwright` → 最后才在 repo venv 安装 Python Playwright + Chromium。
  - 强制 viewport `1600x900`、device scale factor `1`。
  - React 用 `locator('main')` 截图，并隐藏嵌套于 `<main>` 的 SPA-only `<header>`；Streamlit 同 viewport 全屏截图，不裁。
  - Pillow 输出 raw AE、4 象限 region AE 和 `/tmp/settings_visual_diff.png`。
  - raw AE 仍高于 1% 时，输出 DOM 文本/表单契约 + computed body style 的 structural fallback。
- `frontend/playwright.config.ts`：统一 e2e viewport 为 `1600x900`。
- `frontend/src/styles/globals.css`：body 字体统一为 `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`。
- 没有修改 `frontend/src/pages/SettingsPage.tsx`、`web/` 或业务代码。

## visual_diff 与 4 region 分布

| 指标/区域 | diff |
|---|---:|
| raw AE（全图） | `3.262%` |
| top_left | `5.086%` |
| top_right | `1.189%` |
| bottom_left | `5.188%` |
| bottom_right | `1.586%` |
| structural / identity | `0.000%` |
| structural / provider_models | `0.000%` |
| structural / api_key | `0.000%` |
| structural / base_url | `0.000%` |
| structural / computed_style | `0.000%` |
| **structural overall (fallback gate)** | **`0.00%`** |

raw AE 从 `4.06%` 降为 `3.26%`，但未达到 `<1%`。差异集中在左半区，来自刻意保留的 Streamlit sidebar/legacy 纵向表单与 React Bloomberg 卡片布局；继续压到 `<1%` 必须改 UI 内容/背景或 Streamlit，违反本轮边界。因此采用用户允许的 structural fallback，并将 Phase 1 raw visual 容忍阈值明确记录为诊断值。

## structural fallback 说明
- identity：两端都有“设置”与模型/LLM 身份文案。
- provider_models：两端都有供应商、快速模型、深度模型区域。
- api_key：两端都有 API Key 状态/配置区域。
- base_url：两端都有 Base URL / 网络代理区域。
- computed style sanity：两端 body 都为 `16px`，React 字体栈已对齐到 system UI；背景/主题继续保持各自既有暗色定义。

## Phase C — 回归验证

| 命令 | 实际结果 |
|---|---|
| `.venv/bin/python scripts/parity_check.py --page settings` | `data_hash: 395abc12402a918931fa91a2eac35c42` |
| `.venv/bin/python scripts/parity_perf.py --page settings` | `FastAPI=6.19ms React=2.78ms Streamlit=3.68ms` |
| `.venv/bin/python scripts/parity_fault_inject.py --page settings` | `fault_diff: 文案一致`，API HTTP 422 |
| `.venv/bin/python scripts/parity_visual.py --page settings` | raw `visual_diff: 3.26%`；fallback `structural_diff: 0.00%` |
| `.venv/bin/python -m pytest tests/ -q` | `758 passed, 2 skipped, 1 warning, 47 subtests passed`（目标基线 757；当前 HEAD 实际 collection 为 760，新增 1 个现有测试通过，0 failed） |
| `npm run build` | 成功，1643 modules transformed |
| `npm run test:e2e` | `1 passed` |
| `env -u NODE_ENV ./node_modules/.bin/vitest run tests/unit/SettingsPage.test.tsx` | `3 passed` |

环境说明：初次 pytest collection 因 venv 缺失项目声明的 optional dependency `langchain-google-genai>=4.0.0` 失败；安装到现有 `.venv` 后全量为 758 passed（未修改依赖文件）。Shell 预设 `NODE_ENV=production` 会让 React testing-library 使用 production `act()`，因此 Vitest 以 `env -u NODE_ENV` 运行；没有改测试或业务代码。

## 新截图
- React main：`/tmp/react_settings_page.png`，`1376x900`，md5 `f78e073cb6b7ec55921ddfcebc35c29d`
- Streamlit viewport：`/tmp/streamlit_settings_page.png`，`1600x900`，md5 `498a130f82bae6ec463d0cb4fdb62ba4`
- Diff heatmap：`/tmp/settings_visual_diff.png`

## 改动摘要（0 commit）
1. `scripts/parity_visual.py`：Playwright auto-detect/bootstrap、locator capture、统一 viewport、4-region AE、structural fallback。
2. `frontend/playwright.config.ts`：添加 `viewport: { width: 1600, height: 900 }`。
3. `frontend/src/styles/globals.css`：添加 system UI body font stack。
4. `parity-results/settings-diff.md`：更新本次 Phase A/B/C、视觉/结构指标、parity/test 输出与截图。

## P1.6.P1 Gate 5 步
- [x] Step 1 Patch（代码；未改 SettingsPage/web/业务）
- [x] Step 2 Verify（4 parity + pytest + build + Playwright + Vitest）
- [ ] Step 3 用户确认（等待用户文字回复）
- [x] Step 4 记录（本文档）
- [ ] Step 5 进下一步（Streamlit fallback 继续并行）

## 不删 Streamlit（硬约束）
任何 P*.P1 ❌ → Phase 2 不算完成 → Phase 3 不删 Streamlit。Phase 1 保留 Streamlit 8501 fallback；本轮没有修改 `web/`，没有删除文件，也没有 commit。
