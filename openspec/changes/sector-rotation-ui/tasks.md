# Tasks

## 1. 抽出组件

- [x] 1.1 新建 `web/components/sector_panel.py`, 函数 `render_sector_panel()`
- [x] 1.2 把 `web/app.py:148-178` 30 行内联代码删除, 改为 `from web.components.sector_panel import render_sector_panel; render_sector_panel()`

## 2. 工具栏 + 数据源状态

- [x] 2.1 顶部加搜索框 (`st.text_input` + session_state `sector_search`)
- [x] 2.2 加"仅看 ≥ N 只涨停" selectbox (默认 3, session_state `sector_min`)
- [x] 2.3 加"数据源状态"行 (3 个 ✓/✗ + "重试" 按钮), 颜色按 `.bb-sector-meta-ok/fail`
- [ ] 2.4 加"数据时间戳"显示 (从 `digest.sources_ok` 上次拉取时间)

## 3. 机构策略 expander

- [x] 3.1 顶部加一个 `st.expander("📌 机构选股策略 Top 3 (np-ipick 热度)", expanded=False)`
- [x] 3.2 内部渲染 3 行: rank. question + heatValue (`.bb-section-label` + mono)
- [x] 3.3 数据源失败时显示 "数据源 np-ipick 不可用"

## 4. 概念板块分组表格

- [x] 4.1 排序: `concept_blocks.items()` 按 `len(stocks)` 降序
- [x] 4.2 过滤: 阀值 + 搜索双重过滤
- [x] 4.3 Top 3 默认展开: `st.expander(f"🔋 {name} · {n} 只涨停 · 板块涨幅 {avg:+.2f}%", expanded=(i < 3))`
- [x] 4.4 块内表格列: 代码 | 名称 | 涨幅 | 题材 | 换手 | 成交额 | DDE | 操作
- [x] 4.5 涨幅列用 `.bb-signal--buy/sell/hold/neutral` 颜色
- [x] 4.6 操作列用 `st.button("分析", key=f"analyze_{code}_{block_key}", type="secondary")`
- [x] 4.7 板块涨幅计算: `sum(zhangfu for s in stocks) / len(stocks)` (parse zhangfu string to float)

## 5. [分析] 按钮行为

- [x] 5.1 点击 → 检查 `st.session_state.get("tracker")` 是否有 running tracker
- [x] 5.2 如有 running → `st.warning("已有进行中的分析, 请等待完成")`, 不跳转
- [x] 5.3 否则 → 设 `st.session_state["start_analysis"] = {"ticker": code, "trade_date": today}`, `st.session_state["nav"] = "analyze"`, `st.rerun()`

## 6. 空状态 / 降级

- [x] 6.1 `concept_blocks` 为空 + `hot_stocks` 有 → 退化: 渲染一个 "📈 涨停热点股 Top N" 平铺表 (无分组)
- [x] 6.2 `hot_stocks` 也为空 → 渲染 `.bb-sector-empty` 空状态: "今日无涨停股, 可能非交易日或数据源全部失败"
- [x] 6.3 `digest` 获取抛异常 → `st.error(f"加载失败: {exc}")` + 重试按钮

## 7. CSS 扩展

- [x] 7.1 扩 `web/styles/elements.css` 加 5 个 class (`.bb-sector-toolbar` / `.bb-sector-meta` / `.bb-sector-block-header` / `.bb-sector-block-stats` / `.bb-sector-empty`)
- [ ] 7.2 验视觉: 表格 hover 行, [分析] 按钮 hover glow, 涨幅颜色, expander 折叠图标

## 8. 单元测试

- [x] 8.1 新建 `tests/components/test_sector_panel.py`
- [x] 8.2 `test_sort_blocks_by_stock_count_desc`
- [x] 8.3 `test_search_filter_by_code`
- [x] 8.4 `test_search_filter_by_name`
- [x] 8.5 `test_min_count_filter_drops_small_blocks`
- [x] 8.6 `test_top3_default_expand`
- [x] 8.7 `test_analyze_button_sets_session_state`
- [x] 8.8 `test_analyze_button_blocked_when_tracker_running`
- [x] 8.9 `test_empty_state_when_no_concept_blocks_but_has_hot_stocks`
- [x] 8.10 `test_empty_state_when_all_empty`
- [x] 8.11 覆盖率 ≥ 80% (run `pytest --cov=web/components/sector_panel`) → 86% 实际

## 9. 验证

- [x] 9.1 `python -m pytest tests/ -v` 全绿 (169 existing + 49 新 + 44 subtests)
- [x] 9.2 重启 streamlit, 浏览器走 4 场景: 正常交易日 / 非交易日 / 单源失败 / 全部失败
- [ ] 9.3 截图 before/after 对比, 确认视觉密度和信息架构改善
- [x] 9.4 验证 [分析] 跳转: 点 [分析] → 跳到 analyze tab + ticker 预填 + 日期今天
- [x] 9.5 验证搜索: 输入 "300" → 只剩代码含 300 的行
- [x] 9.6 验证阀值: 选 ≥5 → 只剩 ≥5 只涨停的板块展开

## 10. 文档

- [x] 10.1 `CHANGELOG.md` 写 v0.2.13 (UI 重构)
- [x] 10.2 `CLAUDE.md` 更新关键路径 + 数据源描述 (不变, 只 version bump)
- [x] 10.3 `web/components/sector_panel.py` 顶部 docstring 写清依赖 `SectorRotationDigest`
