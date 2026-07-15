# Settings Page Parity Gate P1.6.P1

## 5 维度结果
- data_hash: `395abc12402a918931fa91a2eac35c42` (canonical md5 of `~/.tradingagents/settings.json`)
- visual_diff: `4.06%` (actual settings views after navigating Streamlit's `⚙️ 设置` button; measured with Pillow; target is `< 1%`, so this dimension is **not yet at target**)
- perf_ms: React=`4.29ms` Streamlit=`2.72ms` FastAPI=`6.38ms` (mean of `/api/settings`=`11.10ms` and `/api/health`=`1.66ms`)
- fault_diff: `文案一致` (both initial HTML responses had `无可见错误文案`; malformed PUT returned FastAPI HTTP 422)
- functional: Playwright e2e `1 passed`; Vitest unit `3 passed`

## Streamlit 同等性
- Streamlit 8501: `/tmp/streamlit_settings_page.png` (captured after clicking `⚙️ 设置`), md5 `97222f2ff2a533e776bf5dc620429a46`
- React 5173:    `/tmp/react_settings_page.png`, md5 `3c64e5beb72e6f0056af612a5deeb1ae`
- FastAPI health: `/tmp/fastapi_health.json`, body `{"status":"ok"}`, md5 `0f0479874bf6f4a7281099b15df27c27`

## P1.6.P1 Gate 5 步
- [x] Step 1 Patch (代码)
- [x] Step 2 Verify (4 工具脚本)
- [ ] Step 3 用户确认 (⏳ 等用户文字回复 "⚙️ settings parity 通过")
- [x] Step 4 记录 (本文档)
- [ ] Step 5 进下一步 (Streamlit fallback 继续并行)

## 测试结果
- pytest `757 passed, 2 skipped, 1 warning, 44 subtests passed` ✅
- npm run build ✅
- Playwright `1 passed` ✅
- Vitest `3 passed` ✅

## 不删 streamlit (硬约束)
任何 P*.P1 ❌ → Phase 2 不算完成 → Phase 3 不删 streamlit。
当前 Phase 1 parity 已跑通基础功能，但 visual_diff 为 4.76%（高于目标），因此 Streamlit 8501 继续运行作为 fallback。
