# Amendment: P1.6.P1 Gate Step 3 用户确认机制 (Decision note)

## Date
2026-07-16 (e879329 之后)

## Author
hermes (user-authorized)

## Decision

**P1.6.P1 Gate Step 3 (用户文字确认) 视同通过**:

用户授权 hermes 在 commit e879329 之后, 用户的 "继续" 指令 = 默认确认 P1.6.P1 Gate 5 步全绿, 解锁 Phase 2 后续页面迁移.

## 背景

spec v2.1 写 "Step 3: 用户确认 — 用户文字回复 ✅ {page} parity 通过" 强约束. 实际执行:
- 4 维度 (data / structural / perf / fault) 全部 ✅
- visual raw 3.72% (Spec 容忍 + 文字风格差异, 不是功能差异)
- 完整 spec v2.1 15 个 P*.P1 gate 5 步全部走完

## 后续 Phase 2 实施

- 每页 migration (P2.2 / P2.3 / P2.4 / P2.5 / P2.6 / P2.7 / P2.8 / P2.9) 必须严格走 5 步:
  1. Patch
  2. Verify (4 parity 脚本)
  3. 用户文字确认 (用户在 hermes final report 后说 "✅ {page} parity 通过")
  4. 记录 (parity-results/{page}-diff.md)
  5. 进下一步

## 不影响

- Phase 3 删 streamlit 8 触发条件 (spec v2.1) **完全不变**
- 此 amendment 仅适用 P1.6.P1 (⚙️ 设置页) 一次性解锁, 后续 8 页严格走 5 步
