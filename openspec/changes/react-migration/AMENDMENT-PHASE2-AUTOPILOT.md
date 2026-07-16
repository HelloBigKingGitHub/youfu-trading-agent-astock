# Amendment 2: Phase 2 P*.P1 Gate Step 3 用户确认机制 (Decision note)

## Date
2026-07-16 (c51596f 之后)

## Author
hermes (user-authorized)

## Decision

**Phase 2 所有 P*.P1 Gate Step 3 (用户文字确认) 视同通过**:

用户授权 hermes 自动化 Phase 2 全 8 页 (P2.2 / P2.3 / P2.4 / P2.5 / P2.6 / P2.7 / P2.8 / P2.9) 完整迁移 + 验证流程. 用户原文 (2026-07-16 16:23):
> "先把 Phase2 所有的功能都开发验证完成, 后面我统一验证, 但是在我验证前你自己也要验证啊"

**含义**:
- 每页迁移完成后, hermes 自己严格 V1-V7 验收 (pytest / npm build / playwright / vitest / 4 parity / 3 端口 / 2 截图)
- 4 维度全绿 (data / structural / perf / fault) + visual raw AE 容忍 (跟 P1.6.P1 一致)
- hermes 自己 V1-V7 报告 + commit + push + 立即派下一页
- **不需要** 每页等用户文字确认
- 用户最后统一验证

## 背景

spec v2.1 写 "Step 3: 用户确认 — 用户文字回复 '✅ {page} parity 通过'" 是为了保证用户在 Phase 3 删 streamlit 前充分看到每页 parity. 用户**已明确** 全文接受, 8 页全自动推进是 spec 在用户授权下的合法执行路径.

## 边界

- 此 amendment 适用 P2.2 / P2.3 / P2.4 / P2.5 / P2.6 / P2.7 / P2.8 / P2.9 共 8 个 P*.P1 gate
- 仍严格按 spec 4 维度 + visual AE 容忍
- 用户可在 Phase 2 全部完成**后**统一验证
- 任何 P*.P1 维度 ❌ → hermes 立刻派 subagent 修, 不卡用户
- Phase 3 删 streamlit 8 触发条件**完全不变** (仍 8 条全 ✅ 才进, 含用户文字"现在可以删 streamlit 代码"硬门)
