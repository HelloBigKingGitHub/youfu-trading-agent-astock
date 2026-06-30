# Sector Rotation UI — Design

## Context

`SectorRotationDigest` 数据结构 (v0.2.12 已落地) 提供 4 个字段:
- `hot_strategies: list[dict]` — {rank, heatValue, chg, question} Top N
- `hot_stocks: list[dict]` — {code, name, reason, zhangfu, huanshou, chengjiaoe, ddejingliang}
- `concept_blocks: dict[str, list[dict]]` — {block_name: [stocks...]}
- `sources_ok: dict[str, bool]` — 3 源独立状态

当前 `web/app.py:148-178` 把 `digest.markdown` 整段塞 `st.markdown(digest.markdown)` 给用户, 没用到 `concept_blocks` 的分组结构, 也没法从 UI 触发分析。

## Goals / Non-Goals

### Goals
1. 把 concept_blocks 分组结构直接消费, 主体是分组表格 (不重建 markdown)
2. 每个股票行可一键跳到分析 (2-step: 跳 tab + 预填, 不直接跑)
3. Top 3 板块默认展开, 其余折叠 (信息密度 + 可控性)
4. 机构选股策略作为顶部折叠 expander, 不丢信号
5. 复用现有 `bb-table-*` / `bb-signal-*` CSS class, 不新建大量 class
6. 单元测试覆盖核心过滤/排序/降级逻辑

### Non-Goals
- 不做板块级一键分析(必须单股)
- 不做自动刷新定时器 (手动按钮 + 时间戳提示已够)
- 不做"加入关注" (观察列表功能未存在)
- 不做"分析整个板块的成分股"(push2 不可用, 且超出 v0.1 数据能力)

## Layout

```
板块轮动日报                       [🔄 拉取最新]   [⏱ 数据 11:00]
─────────────────────────────────────────────────────
搜索: [_________]  仅看 ≥[3 只涨停 ▼]
─────────────────────────────────────────────────────
▼ 📌 机构选股策略 Top 3  (np-ipick 热度)             (默认折叠)
   1. 涨幅>5%或涨停+连续三天10日线>30度拉升   heat=8234
   2. 量比>2+换手>5%+均线多头                  heat=6721
   3. 近 3 日涨停+创业板+MACD 金叉              heat=5430
─────────────────────────────────────────────────────
47 只涨停 · 8 个概念板块 · 按股票数降序

▼ 🔋 电池+储能 · 8 只涨停 · 板块涨幅 +5.2%           (展开)
  ┌────────┬──────┬───────┬──────┬──────┬──────┬──────┬──────┐
  │ 代码   │ 名称 │ 涨幅  │ 题材 │ 换手 │ 成交额│ DDE  │ 操作 │
  ├────────┼──────┼───────┼──────┼──────┼──────┼──────┼──────┤
  │ 300750 │ 宁德 │+10.01%│ 电池 │ 2.34%│ 38.5亿│ +1.2 │[分析]│
  │ 002594 │ 比亚迪│+9.99%│ 电池 │ 4.21%│ 22.1亿│ +0.8 │[分析]│
  │ ...                                                       │
  └────────┴──────┴───────┴──────┴──────┴──────┴──────┴──────┘

▼ 🧠 芯片 · 3 只涨停 · 板块涨幅 +3.8%                  (展开)
  [同上表]

▶ 📱 AI+视频 · 2 只涨停 · 板块涨幅 +4.1%              (折叠)
```

## Decisions

### Decision 1: 概念板块优先, 不用 hot_stocks 平铺 (Option C)

**Why**: 用户表述"板块轮动查询导数据后我希望能展示成一个表格", 主语是"板块"不是"股"。`concept_blocks` 已经按主题聚类, 这是板块轮动最有价值的视图; 平铺会丢失"主题聚集"信号。

**替代**:
- A (单表 hot_stocks): 简单但丢失主题信号
- B (3 段全保留): 太多信息干扰"分析"主目标

### Decision 2: 2-step 跳转, 不直接 1-click 启动

**Why**: 1-click 启动会让用户失去"确认 ticker + 改日期"的机会; 多用户误点会浪费 LLM token。2-step 复用现有 `st.session_state["start_analysis"]` 机制, `app.py` 已有的 trigger 流程不用改。

**实现**:
```python
if st.button("分析", key=f"analyze_{code}"):
    st.session_state["start_analysis"] = {
        "ticker": code,
        "trade_date": date.today().strftime("%Y-%m-%d"),
    }
    st.session_state["nav"] = "analyze"
    st.session_state["viewing_history"] = None
    if st.session_state.get("tracker") and st.session_state["tracker"].is_running:
        st.warning("已有进行中的分析, 请等待完成")
    st.rerun()
```

### Decision 3: Top 3 板块默认展开, 其余折叠

**Why**: Bloomberg Terminal 风格的密度 + 用户的"先看最强的"心智模型。Top 3 占 80% 资金关注度 (设计依据见原 sector-rotation design.md Decision 1)。

**持久化**: `st.session_state[f"sector_block_expand_{block_key}"]`, 首次访问默认展开 Top 3, 用户手动展开/折叠后状态保留。

### Decision 4: 复用现有 CSS 体系, 仅新增 5 个 class

新 class (扩 `web/styles/elements.css`):
- `.bb-sector-block-header` — 板块头, 含 emoji + 板块名 + 计数 + 板块涨幅
- `.bb-sector-block-stats` — 板块头内的统计行
- `.bb-sector-empty` — 全数据源失败时空状态
- `.bb-sector-toolbar` — 顶部工具栏 (搜索 + 阀值)
- `.bb-sector-meta` — 数据源状态指示 (3 源 ✓/✗)

**复用** (不新增):
- `.bb-table-cell` / `.bb-table-cell--date` / `.bb-table-cell--id` — 表格行
- `.bb-signal--buy/sell/hold` — 涨幅列颜色
- `.bb-section-label` — 板块头"📌 机构选股策略"
- `.bb-card` — 顶部统计 chip (如 "47 只涨停 · 8 个板块")

### Decision 5: 搜索 + 阀值过滤都是 Python in-memory

**Why**: 数据规模 < 100 行 (涨停 Top 20 + Top 8 板块), 完全不需要 SQL/Lucene。`st.text_input` 配 `on_change` rerun, `st.selectbox` 配默认 value, 都用 session_state 存用户输入。

**实现**:
```python
search = st.text_input("搜索", key="sector_search").strip().upper()
min_count = st.selectbox("仅看 ≥", [1, 2, 3, 5, 10], index=2, key="sector_min")

# 过滤逻辑
blocks_filtered = [
    (name, stocks) for name, stocks in blocks_sorted
    if len(stocks) >= min_count
    and (not search or any(
        search in s["code"].upper() or search in s["name"]
        for s in stocks
    ))
]
```

### Decision 6: 数据源失败降级 — 显示空状态 + 原因

**Why**: 让用户知道"系统挂了"还是"今天没数据", 不假装有数据。

**实现**:
```python
ok = digest.sources_ok
# 顶部小行: ✓ 东财 np-ipick  ✓ 同花顺  ✗ 百度 PAE  [重试]
# 任一 source 失败 → 显示具体源名 + "重试" 按钮
# 全部失败 → 全局空状态 + 单股平铺表
```

### Decision 7: 题材列保留, 行内重复显示

**Why**: 同一板块下, 股票级 `reason` 经常比板块名更细 (e.g. 板块"电池+储能"下, A 股 reason="电池+储能+固态电池", B 股 reason="电池+储能+钠电池")。 用户需要看具体归因来选股。

## File Layout

```
web/
├── components/
│   └── sector_panel.py       (新建, ~180 行)
│       ├── render_sector_panel()    # 入口
│       ├── _render_header()         # 工具栏 + 数据源状态
│       ├── _render_strategies()     # 顶部 expander
│       ├── _render_blocks()         # 概念板块列表
│       ├── _render_block_table()    # 单板块表格
│       └── _render_empty_state()    # 全部失败
├── app.py                    (改: sector tab 改 import + 删 30 行)
├── styles/elements.css       (扩展 5 个 class)
tests/
└── components/
    └── test_sector_panel.py  (新建, ~80 行)
        ├── test_sort_blocks_by_stock_count()
        ├── test_search_filter()
        ├── test_min_count_filter()
        ├── test_top3_expand_default()
        ├── test_click_analyze_sets_session_state()
        └── test_empty_state_when_all_sources_fail()
```

## CSS 增量 (`web/styles/elements.css`)

```css
/* Sector panel — top toolbar */
.bb-sector-toolbar {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    margin-bottom: 1rem;
}

/* Sector panel — data source status row */
.bb-sector-meta {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.5rem;
}
.bb-sector-meta-ok    { color: var(--bb-up); }
.bb-sector-meta-fail  { color: var(--bb-down); }

/* Sector panel — block header (in expander) */
.bb-sector-block-header {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    font-family: var(--font-mono);
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.bb-sector-block-stats {
    color: var(--text-secondary);
    font-size: 0.8rem;
    font-weight: 400;
    margin-left: auto;
}

/* Sector panel — empty state */
.bb-sector-empty {
    text-align: center;
    padding: 3rem 1rem;
    color: var(--text-secondary);
    font-size: 0.9rem;
    background: var(--bg-elevated);
    border: 1px dashed var(--border-1);
    border-radius: var(--radius-md);
}
```

## Open Questions

- **Q1**: 排序是否要给用户可切换 (按股票数 / 按板块涨幅 / 按 DDE 净量)? 当前默认按股票数; v0.1 不加切换, v0.2 再加。
- **Q2**: 板块涨幅用什么计算? (简单平均 vs 加权平均 vs 中位数) — v0.1 用简单平均, 后期可改。
- **Q3**: 表格用 `st.dataframe` (内置, 不可深度样式) 还是 `st.html` + bb-table (完全自定义, 跟其他面板一致)? **选 st.html**, 保持视觉一致。
- **Q4**: [分析] 按钮是否要 confirm step (e.g. "确认对 300750 开始分析?")? 当前选 2-step (跳 tab + 预填), 不再加 confirm。

## Migration Plan

1. 实现 `web/components/sector_panel.py` + CSS
2. 改 `web/app.py` 接入
3. 单元测试
4. 手动验证: 浏览器跑一遍 4 个场景 (正常 / 数据空 / 单源失败 / 全部失败)
5. 截图对比 before/after
6. CHANGELOG.md 写 v0.2.13
7. 不涉及数据迁移, `git revert` 可回滚
