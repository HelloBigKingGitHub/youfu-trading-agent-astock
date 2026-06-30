# Sector Rotation UI — Concept-Block Table

## Why

`web/app.py:148-178` 的"板块轮动"tab 当前直接渲染 `SectorRotationDigest.markdown` 原始文本,这种形式有两个具体问题:

1. **不可消费**: 4 段标题 + 列表 + free text reason tags, 用户只能"读"不能"操作"。看完整页才能找到 1-2 只感兴趣的股票, 没法直接发起分析。
2. **没有"分析"入口**: 板块轮动日报的真正价值是给"今天该看哪些股"提供候选池, 但当前 UI 没有任何方式从日报跳到分析流程。 用户必须手动切到"分析"tab → 手敲 6 位代码 → 重输日期。

v0.2.12 已经把数据(`hot_strategies` / `hot_stocks` / `concept_blocks` / `sources_ok`)准备齐全, 数据结构已支持"分组 + 表格化 + 操作列", 缺的只是 UI 层。

## What Changes

- **新建组件 `web/components/sector_panel.py`**: 把当前 `app.py:148-178` 的 sector tab 内联代码抽出为独立组件, 渲染概念板块分组表格 + [分析] 操作列。
- **修改 `web/app.py`**: sector tab 改为 `from web.components.sector_panel import render_sector_panel; render_sector_panel()`, 删掉 30 行内联代码。
- **扩展 `web/styles/elements.css`**: 新增 ~5 个 `.bb-*` class 支持表格+操作列样式 (复用现有 `.bb-table-cell` / `.bb-signal` 体系, 不重新发明)。
- **不修改 `tradingagents/dataflows/a_stock.py`**: `SectorRotationDigest` 字段已够用, 数据层零改动。

### Non-goals (明确不做的)

- ❌ 不改 `SectorRotationDigest` 数据结构
- ❌ 不新增 vendor 函数
- ❌ 不改 `hot_money_tracker` Analyst 的 prompt 或工具列表
- ❌ 不实现"板块级"分析(目前没有板块聚合数据, 且 [分析] 必须 1 stock 1 run)
- ❌ 不实现"加入观察列表" (观察列表功能尚未存在)
- ❌ 不做实时分钟级自动刷新(单次拉取 + 手动刷新, 与 v0.2.12 一致)

## Capabilities

### Modified Capabilities
<!-- 没有新增 spec 字段, 只改 UI 层 user-facing 行为. 通过 modification 表达: -->
- `sector-rotation-digest` (现有 spec 保持 schema 不变; 改 markdown 章节结构可作单独 ISSUE 跟进, 不在本 change 范围)

### Impact
| 文件 | 改动 | 性质 |
|---|---|---|
| `web/components/sector_panel.py` | 新建 ~180 行 | **核心** |
| `web/app.py` | sector tab 改 import + 删内联, 净减 ~25 行 | 改造 |
| `web/styles/elements.css` | 新增 5 个 class, ~30 行 | 扩展 |
| `tests/components/test_sector_panel.py` | 新建 ~80 行 | 测试 |
| `CLAUDE.md` / `CHANGELOG.md` | 版本号 v0.2.13 | 文档 |

零数据层改动, 零新依赖, 零 API key 变化.

## Risks

| 风险 | 等级 | 缓解 |
|---|---|---|
| Streamlit expander 状态在 `st.rerun()` 后丢失, 展开/折叠不持久 | 低 | 用 `st.session_state` 存每块展开状态, key=`sector_block_expand_{hash(name)}` |
| 搜索框输入触发整个 tab rerender, 性能 | 低 | 客户端过滤 (Python in-memory filter), 数据规模 < 100 行 |
| [分析] 点击 → 跳 analyze tab 时, 已有正在跑的 `tracker` 怎么办? | 中 | 检查 `tracker.is_running`, 提示 "已有进行中的分析, 请等待完成" |
| 概念板块名可能含特殊字符 (e.g. `+`, `&`), 影响 key 命名 | 低 | 用 `hashlib.md5(name.encode()).hexdigest()[:8]` 做 key 后缀 |
| 数据源全部失败时 UI 空状态不够 actionable | 中 | 显示具体失败源 + "重试" 按钮 (复用 st.button) |
