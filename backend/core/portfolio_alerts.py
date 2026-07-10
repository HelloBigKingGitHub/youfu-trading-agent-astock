"""Portfolio alerts — 预警规则评估引擎。

按需触发（用户进入 Tab 1 或手动按"检查预警"按钮时调 evaluate_alerts）。
复用 backend.core.portfolio_store.AlertRule + PortfolioStore。
不直接做价格查询（由调用方传入 current_prices dict）。

设计要点（v0.5.0 MVP）：
  * MVP 只实现 2 种 rule_type：price_above / price_below
  * 其它 5 种（pct_change / pnl_pct / take_profit / stop_loss / trailing_stop）
    在 P2 阶段实现，需要成本联动（cost_basis）或历史价格（prev_close）
    等新数据源 —— 见 openspec/changes/portfolio-module/design.md Decision 3
  * 防重复：last_triggered_at 距今 < ANTI_REPEAT_WINDOW_SEC 跳过
  * 触发后立即调 store.record_trigger(rule_id, current_value) 写回
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 复用 Round 1 的 AlertRule + PortfolioStore
from backend.core.portfolio_store import AlertRule, PortfolioStore


# 防重复窗口：5 分钟（300 秒）。同一规则在窗口内最多触发 1 次，
# 避免 Streamlit 每次 rerun 反复推送同一条预警。
ANTI_REPEAT_WINDOW_SEC: int = 300


@dataclass
class AlertTrigger:
    """单条预警触发记录。

    evaluate_alerts 返回的 UI 渲染单元。message 字段由 _make_trigger
    在生成时一次性格式化好（中文 + 当前价 + 阈值），UI 直接显示即可。
    """

    rule_id: str
    ticker: str
    rule_type: str
    threshold: float
    current_value: float
    triggered_at: float  # time.time() 时间戳
    message: str         # 人类可读："价格突破 7.00，当前 7.05 (+0.71%)"


# ── 单条规则评估（v0.5.0 MVP 只实现 2 种 type）────────────────────


def evaluate_alert(
    rule: AlertRule,
    current_price: float,
) -> AlertTrigger | None:
    """评估单条规则是否触发。返回 AlertTrigger 或 None（未触发）。

    MVP 实现：
      - price_above: current_price > rule.threshold → 触发
      - price_below: current_price < rule.threshold → 触发
      - 其它 5 种 type 抛 NotImplementedError（P2 阶段实现）
    """
    if rule.rule_type == "price_above":
        if current_price > rule.threshold:
            return _make_trigger(rule, current_price)
        return None
    if rule.rule_type == "price_below":
        if current_price < rule.threshold:
            return _make_trigger(rule, current_price)
        return None

    # 其余 5 种 rule_type 需要 cost_basis（pnl_pct / take_profit /
    # stop_loss / trailing_stop）或 prev_close（pct_change）。
    # 留待 P2 阶段结合 Portfolio 成本联动 + 历史 K 线数据源实现。
    raise NotImplementedError(
        f"rule_type {rule.rule_type!r} 在 v0.5.0 MVP 暂未实现（需要成本联动或历史价格）"
    )


def _make_trigger(rule: AlertRule, current_price: float) -> AlertTrigger:
    """构造 AlertTrigger 并格式化为中文 message。

    pct 变化用 (current - threshold) / threshold 估算（不算严格"涨跌幅"，
    真实涨跌幅需要 prev_close，留 P2）。只在 threshold > 0 时附加。
    """
    pct_change_str = ""
    if rule.threshold > 0:
        delta = (current_price - rule.threshold) / rule.threshold
        pct_change_str = f" ({delta:+.2%})"
    msg = {
        "price_above": f"价格突破 {rule.threshold:.2f}，当前 {current_price:.2f}{pct_change_str}",
        "price_below": f"价格跌破 {rule.threshold:.2f}，当前 {current_price:.2f}{pct_change_str}",
    }[rule.rule_type]
    return AlertTrigger(
        rule_id=rule.rule_id,
        ticker=rule.ticker,
        rule_type=rule.rule_type,
        threshold=rule.threshold,
        current_value=current_price,
        triggered_at=time.time(),
        message=msg,
    )


# ── 批量评估（主入口）────────────────────────────────────────────


def evaluate_alerts(
    store: PortfolioStore,
    current_prices: dict[str, float],
    now: float | None = None,
) -> list[AlertTrigger]:
    """遍历 store.list_alerts(enabled_only=True) 评估所有 enabled 规则。

    Parameters
    ----------
    store : PortfolioStore
        单例 store，CRUD 与持久化由其负责。
    current_prices : dict[str, float]
        ticker → 当前价；缺 key 的 ticker 直接 skip（不抛错）。
    now : float, optional
        注入"当前时间"以便测试 mock；默认 wall-clock time.time()。

    Returns
    -------
    list[AlertTrigger]
        所有成功触发的记录。已自动调 store.record_trigger 写回。
    """
    if now is None:
        now = time.time()

    enabled = store.list_alerts(enabled_only=True)
    out: list[AlertTrigger] = []
    for rule in enabled:
        price = current_prices.get(rule.ticker)
        if price is None:
            # 该 ticker 暂无报价 → skip
            continue
        # 防重复：last_triggered_at 距今 < ANTI_REPEAT_WINDOW_SEC 跳过
        if (
            rule.last_triggered_at is not None
            and now - rule.last_triggered_at < ANTI_REPEAT_WINDOW_SEC
        ):
            continue

        try:
            trigger = evaluate_alert(rule, price)
        except NotImplementedError as exc:
            # P2 类型：单条规则 skip，不影响同 batch 其它规则
            # 实际项目里可加 audit log；本 MVP 静默
            _ = exc  # 占位：避免 lint warning
            continue

        if trigger is None:
            continue

        # 触发后立即写回 last_triggered_at 等字段 —— 下次调用就在冷却窗内
        try:
            store.record_trigger(rule.rule_id, price, now=now)
        except KeyError:
            # 规则在 list → record 之间被删除：静默丢弃这条 trigger
            continue
        out.append(trigger)
    return out


# ── 消息格式化（v0.5.0 MVP 直接透传 _make_trigger 预格式化结果）─


def format_trigger_message(trigger: AlertTrigger) -> str:
    """直接返回 trigger.message（_make_trigger 已格式化为中文）。"""
    return trigger.message
