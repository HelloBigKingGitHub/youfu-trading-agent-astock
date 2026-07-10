"""Portfolio calc — pure calculation functions (no IO, no streamlit).

复用 backend.core.portfolio_store 的 dataclass。
参考 backend.core.history_store.HistoryStore 作为 IO 抽象（仅 get_rebalance_signals 用）。

设计要点:
  * 单一职责: 输入 dataclass + 行情 dict，返回 dataclass / number / list
  * 零副作用: 不读盘、不发请求、不渲染 UI
  * 数值稳定: 除零 / 空输入都 graceful 退化为 0.0（UI 层负责显示 "N/A"）
  * numpy/scipy 是项目既有依赖（已在 requirements.txt 中）

API 概览（详见各函数 docstring）:
  - PositionMetrics / PortfolioSummary        # dataclass 输出
  - compute_position_metrics                  # 单只持仓盈亏
  - compute_portfolio_summary                 # 组合汇总（含板块/行业/账户归因）
  - compute_xirr / _extract_cashflows         # 不规则现金流内部收益率
  - compute_max_drawdown                      # 最大回撤
  - compute_sharpe                            # 年化夏普比率
  - compute_brinson_attribution               # Brinson 业绩归因 MVP
  - compute_equity_curve                      # MVP 占位（历史 K 线超出 P0）
  - get_rebalance_signals                     # 调仓推送（diff Bull/Bear 信号）
  - compute_annual_return                     # 年化收益工具
  - group_by_sector                           # 已废弃，仅保留兼容老版 portfolio_panel.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# numpy / scipy 是项目已有依赖（requirements.txt 已锁定）
import numpy as np
from scipy.optimize import brentq

# 复用 Round 1 的 dataclass（不重新定义）
from backend.core.portfolio_store import Position, Transaction


# ── 常量 ─────────────────────────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR: int = 252
DEFAULT_RISK_FREE_RATE: float = 0.025  # 年化无风险利率（2.5%）
DEFAULT_XIRR_GUESS: float = 0.08  # XIRR 初始猜测（年化 8%）
XIRR_TOL: float = 1e-6  # brentq 容差
XIRR_MAX_ITER: int = 1000  # brentq 最大迭代
XIRR_LO: float = -0.99  # brentq 下界（避免 (1+r)^t 数值爆炸）
XIRR_HI: float = 10.0  # brentq 上界


# ── Result dataclasses ──────────────────────────────────────────────────────


@dataclass
class PositionMetrics:
    """单只持仓的盈亏指标。

    所有金额单位都是元（CNY），比率是无量纲小数（0.05 = +5%）。
    """

    current_value: float  # 现价 × 持仓
    cost_value: float  # 成本价 × 持仓
    pnl_abs: float  # 浮动盈亏金额 (current_value - cost_value)
    pnl_pct: float  # 浮动盈亏比例 (pnl_abs / cost_value)
    today_pnl: float  # 当日盈亏金额（基于现价 - 昨收）
    today_pnl_pct: float  # 当日盈亏比例
    holding_days: int  # 持仓天数
    cost_basis: float  # 成本价（input echo）
    current_price: float  # 现价（input echo）
    prev_close: float  # 昨收（input echo）


@dataclass
class PortfolioSummary:
    """组合汇总（多持仓聚合 + 板块/行业/账户归因）。

    - by_industry / by_sector / by_asset_class / by_account：金额 dict
    - concentration_top5_pct：前 5 大持仓占总金额比例（小数，0.6 = 60%）
    """

    total_value: float
    total_cost: float
    total_pnl_abs: float
    total_pnl_pct: float
    today_pnl: float
    positions_count: int
    by_industry: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    by_asset_class: dict[str, float] = field(default_factory=dict)
    by_account: dict[str, float] = field(default_factory=dict)  # v0.5.0 增量
    concentration_top5_pct: float = 0.0


# ── 辅助函数 ────────────────────────────────────────────────────────────────


def _parse_date(s: str | None) -> date | None:
    """解析 YYYY-MM-DD 字符串为 date；解析失败返回 None（调用方决定 fallback）。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _today() -> date:
    """返回今天日期。集中调用以便测试 monkeypatch。"""
    return datetime.now().date()


# ── 2.1 单只持仓指标 ─────────────────────────────────────────────────────────


def compute_position_metrics(
    position: Position,
    current_price: float,
    prev_close: float,
    transactions: list[Transaction],
) -> PositionMetrics:
    """单只持仓的盈亏指标计算。

    参数:
      position:    单只持仓（已含 cost_basis / quantity / first_buy_date）
      current_price: 当前价（外部行情提供）
      prev_close:  昨日收盘价（外部行情提供，0 表示无昨收则 today_pnl=0）
      transactions: 交易流水——本版本**不**用其重算 cost_basis（cost_basis 已在
                    position 里）；该参数**必须保留**，未来 P2 复权处理 / 拆送股
                    处理需要从流水反推成本。

    返回:
      PositionMetrics（金额单位：元）

    算法:
      - current_value = current_price × position.quantity
      - cost_value    = position.cost_basis × position.quantity
      - pnl_abs       = current_value - cost_value
      - pnl_pct       = pnl_abs / cost_value (cost_value=0 时退化为 0.0)
      - today_pnl     = (current_price - prev_close) × position.quantity
      - today_pnl_pct = (current_price - prev_close) / prev_close
        (prev_close=0 时退化为 0.0)
      - holding_days  = (today - first_buy_date).days
        (first_buy_date 解析失败 → 0，today 用 _today())
    """
    _ = transactions  # 当前版本占位，未来 P2 复权处理用

    quantity = float(position.quantity)
    cost_basis = float(position.cost_basis)

    current_value = current_price * quantity
    cost_value = cost_basis * quantity
    pnl_abs = current_value - cost_value
    pnl_pct = (pnl_abs / cost_value) if cost_value > 0 else 0.0

    prev_close_f = float(prev_close) if prev_close else 0.0
    if prev_close_f > 0:
        today_pnl = (current_price - prev_close_f) * quantity
        today_pnl_pct = (current_price - prev_close_f) / prev_close_f
    else:
        today_pnl = 0.0
        today_pnl_pct = 0.0

    first = _parse_date(position.first_buy_date)
    if first is None:
        holding_days = 0
    else:
        holding_days = max(0, (_today() - first).days)

    return PositionMetrics(
        current_value=round(current_value, 2),
        cost_value=round(cost_value, 2),
        pnl_abs=round(pnl_abs, 2),
        pnl_pct=round(pnl_pct, 4),
        today_pnl=round(today_pnl, 2),
        today_pnl_pct=round(today_pnl_pct, 4),
        holding_days=holding_days,
        cost_basis=cost_basis,
        current_price=float(current_price),
        prev_close=prev_close_f,
    )


# ── 2.2 组合汇总 ────────────────────────────────────────────────────────────


def compute_portfolio_summary(
    positions: list[Position],
    current_prices: dict[str, float],  # ticker → 现价
    prev_closes: dict[str, float],  # ticker → 昨收
    get_industry_fn: Callable[[str], str],  # ticker → 行业名
    get_sector_fn: Callable[[str], list[str]],  # ticker → 板块名列表
) -> PortfolioSummary:
    """组合汇总：Σ 所有持仓的指标 + 板块 / 行业 / 账户归因 + 集中度。

    参数:
      positions:        持仓列表（可空）
      current_prices:   ticker → 当前价；缺失 ticker 回退到 cost_basis（pnl=0）
      prev_closes:      ticker → 昨收；缺失 ticker 视为 0（today_pnl=0）
      get_industry_fn:  行业回调——在 UI 层注入（get_industry(ticker)）
      get_sector_fn:    板块回调——在 UI 层注入，返回 ticker 所属板块列表（1 只
                        股票可能属多个板块，按权重分摊）

    返回:
      PortfolioSummary（含 4 个归因 dict + 集中度比例）

    注：本文件**不**直接 import a_stock——保持纯计算，IO 隔离。
    """
    total_value = 0.0
    total_cost = 0.0
    total_today_pnl = 0.0
    by_industry: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    by_asset_class: dict[str, float] = {}
    by_account: dict[str, float] = {}
    values_by_ticker: list[tuple[str, float]] = []

    for pos in positions:
        # 缺价回退：current_price 用 cost_basis（pnl=0，但有效持仓金额存在）
        cp = float(current_prices.get(pos.ticker, pos.cost_basis))
        pc = float(prev_closes.get(pos.ticker, 0.0))

        metrics = compute_position_metrics(
            position=pos,
            current_price=cp,
            prev_close=pc,
            transactions=[],  # 占位，本函数不用
        )

        total_value += metrics.current_value
        total_cost += metrics.cost_value
        total_today_pnl += metrics.today_pnl

        # 行业 / 板块 / 大类 / 账户归因（按 current_value 金额聚合）
        try:
            industry = get_industry_fn(pos.ticker) or "未知行业"
        except Exception:
            industry = "未知行业"
        by_industry[industry] = by_industry.get(industry, 0.0) + metrics.current_value

        try:
            sectors = get_sector_fn(pos.ticker) or []
        except Exception:
            sectors = []
        if sectors:
            share = metrics.current_value / len(sectors)
            for s in sectors:
                by_sector[s] = by_sector.get(s, 0.0) + share
        else:
            by_sector["未分类"] = by_sector.get("未分类", 0.0) + metrics.current_value

        by_asset_class[pos.asset_class] = (
            by_asset_class.get(pos.asset_class, 0.0) + metrics.current_value
        )
        by_account[pos.account] = (
            by_account.get(pos.account, 0.0) + metrics.current_value
        )

        values_by_ticker.append((pos.ticker, metrics.current_value))

    total_pnl_abs = total_value - total_cost
    total_pnl_pct = (total_pnl_abs / total_cost) if total_cost > 0 else 0.0

    # 集中度：top 5 按 current_value 排序
    values_by_ticker.sort(key=lambda x: x[1], reverse=True)
    top5_sum = sum(v for _, v in values_by_ticker[:5])
    concentration_top5_pct = (top5_sum / total_value) if total_value > 0 else 0.0

    return PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl_abs=round(total_pnl_abs, 2),
        total_pnl_pct=round(total_pnl_pct, 4),
        today_pnl=round(total_today_pnl, 2),
        positions_count=len(positions),
        by_industry={k: round(v, 2) for k, v in by_industry.items()},
        by_sector={k: round(v, 2) for k, v in by_sector.items()},
        by_asset_class={k: round(v, 2) for k, v in by_asset_class.items()},
        by_account={k: round(v, 2) for k, v in by_account.items()},
        concentration_top5_pct=round(concentration_top5_pct, 4),
    )


# ── 2.3 XIRR ────────────────────────────────────────────────────────────────


def _extract_cashflows(
    transactions: list[Transaction],
    current_value: float,
    as_of: date,
) -> tuple[list[float], list[date]]:
    """从 transactions 提取 (cashflow, date) 列表，用于 XIRR 计算。

    现金流规则（钱的方向，以"我"为参考）:
      - buy:      -(price * quantity + fees)    # 钱出去（本金 + 手续费）
      - sell:     +(price * quantity - fees)    # 钱回来（减手续费）
      - dividend: +(price * quantity)            # 每股分红 × 持股数（price 字段做"每股分红"）
      - split / merge / rights:  skip           # 不影响现金流
    最后追加 (current_value, as_of) 作为终值正现金流。

    返回:
      (cashflows, dates) —— 长度相同；零额会自动剔除（避免 log-scale NPV 失稳）。
    """
    cashflows: list[float] = []
    dates: list[date] = []
    for tx in transactions:
        action = tx.action
        if action == "buy":
            amount = -(tx.price * tx.quantity + tx.fees)
        elif action == "sell":
            amount = tx.price * tx.quantity - tx.fees
        elif action == "dividend":
            amount = tx.price * tx.quantity  # 每股分红 × 持股
        else:
            # split / merge / rights：不影响现金流
            continue
        d = _parse_date(tx.date)
        if d is None:
            continue
        if amount == 0.0:
            continue
        cashflows.append(amount)
        dates.append(d)

    # 终值：当前持仓市值（正现金流）
    if current_value != 0.0:
        cashflows.append(float(current_value))
        dates.append(as_of)

    return cashflows, dates


def compute_xirr(
    transactions: list[Transaction],
    current_value: float,
    as_of: date | None = None,
) -> float:
    """XIRR: 不规则日期现金流的内部收益率。

    算法:
      NPV(r) = Σ cf_i / (1+r)^((t_i - t_0).days / 365) + current_value / (1+r)^((as_of - t_0).days / 365)
      求 NPV(r) = 0 的 r（scipy.optimize.brentq）

    参数:
      transactions:  交易流水列表（可含 buy / sell / dividend / split 等）
      current_value: 当前组合市值（元）
      as_of:         计算截止日期；None → 今天

    返回:
      年化 IRR（小数，0.15 = +15%）；失败/发散 → 返回 0.0
      （UI 层显示 "N/A"）
    """
    if as_of is None:
        as_of = _today()

    cashflows, dates = _extract_cashflows(transactions, current_value, as_of)
    if len(cashflows) < 2:
        # 至少需要一笔投资 + 一笔终值
        return 0.0

    # 按日期排序，保证 (1+r)^years 非负
    paired = sorted(zip(dates, cashflows), key=lambda x: x[0])
    sorted_dates = [d for d, _ in paired]
    sorted_cf = [c for _, c in paired]

    # t0 用最早一笔现金流（通常为买入）
    t0 = sorted_dates[0]
    years = np.array(
        [(d - t0).days / 365.0 for d in sorted_dates], dtype=float
    )
    cf = np.array(sorted_cf, dtype=float)

    def npv(rate: float) -> float:
        # 保护 (1+rate) > 0 避免负底数 + 分数指数发散
        base = 1.0 + rate
        if base <= 0:
            return float("inf") if rate > 0 else float("-inf")
        return float(np.sum(cf / np.power(base, years)))

    try:
        return float(brentq(npv, XIRR_LO, XIRR_HI, xtol=XIRR_TOL, maxiter=XIRR_MAX_ITER))
    except (ValueError, RuntimeError):
        # 无法找到根（无符号变化或数值发散）：粗网格 bisection
        lo, hi = -0.9, 5.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            v = npv(mid)
            if v > 0:
                lo = mid
            else:
                hi = mid
        mid = (lo + hi) / 2.0
        # sanity check：若 mid 仍 NaN/Inf 则 fallback 到 0.0
        if not np.isfinite(mid):
            return 0.0
        return mid


# ── 2.4 最大回撤 ─────────────────────────────────────────────────────────────


def compute_max_drawdown(
    equity_curve: list[tuple[date, float]],
) -> float:
    """最大回撤 = max((peak - trough) / peak)，返回正数小数（0.25 = 25% 回撤）。

    算法: 滚动 max + 当前值的最大跌幅。
      - 遍历 equity_curve
      - 维护 running_max（截至当前位置的最高点）
      - drawdown = (running_max - current) / running_max
      - 返回 max(drawdown) 的绝对值（正数）

    边界:
      - equity_curve < 2 个点 → 返回 0.0（无足够数据）
      - 全部值 <= 0 → 返回 0.0
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0][1]
    if peak <= 0:
        peak = 0.0
    max_dd = 0.0
    for _, v in equity_curve:
        if v > peak:
            peak = v
        if peak <= 0:
            continue
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 6)


# ── 2.5 年化 Sharpe ─────────────────────────────────────────────────────────


def compute_sharpe(
    daily_returns: list[float],  # 每个元素 = (today_value / yesterday_value) - 1
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,  # 年化无风险利率（2.5%）
) -> float:
    """年化 Sharpe Ratio = (mean(daily) - daily_rf) / std(daily) * sqrt(252)

    参数:
      daily_returns:   简单日收益率序列（不是 log return）
      risk_free_rate:  年化无风险利率（默认 0.025）

    边界:
      - len(daily_returns) < 2 → 0.0（无足够统计意义）
      - std(daily) == 0 → 0.0（避免除零；常量收益序列无信息含量）
      - daily_rf = risk_free_rate / 252
    """
    if len(daily_returns) < 2:
        return 0.0

    arr = np.asarray(daily_returns, dtype=float)
    mean = float(np.mean(arr))
    # 样本标准差（ddof=1）—— 金融惯例（基于样本而非总体）
    std = float(np.std(arr, ddof=1))
    if std == 0.0 or not np.isfinite(std):
        return 0.0

    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    sharpe = (mean - daily_rf) / std * np.sqrt(TRADING_DAYS_PER_YEAR)
    if not np.isfinite(sharpe):
        return 0.0
    return round(float(sharpe), 4)


# ── 2.6 Brinson 业绩归因 ─────────────────────────────────────────────────────


def compute_brinson_attribution(
    positions: list[Position],
    benchmark_returns: dict[str, float],  # ticker → period return (0.05 = +5%)
) -> dict:
    """简化版 Brinson 归因：拆"选股贡献"和"行业贡献"。

    MVP 实现（不依赖行业基准权重表）:
      - portfolio_return = Σ(weight_p × return_p)
      - benchmark_return = Σ(weight_b × return_b)  for benchmark constituents
      - selection_effect = Σ weight_p × (return_p - return_b_for_same_ticker)
      - allocation_effect = Σ (weight_p - weight_b) × return_b
      - total_effect = selection + allocation

    注: MVP 简化为单一基准（沪深 300），不做行业分组；
    return_p 默认 0（因为函数签名只接 positions + benchmark_returns，无当前价）。
    投资者实际"对手"组合按**等权**简化：weight_b = 1/N。

    返回:
      {
        "portfolio_return":   float,
        "benchmark_return":   float,
        "selection_effect":   float,   # 选股贡献
        "allocation_effect":  float,   # 行业（基准权重）贡献
        "total_effect":       float,
      }
    """
    if not positions:
        raise ValueError("positions must be non-empty for Brinson attribution")

    # 权重按"当前市值"（用 cost_basis 近似，MVP 简化）
    total_value = sum(p.quantity * p.cost_basis for p in positions)
    if total_value <= 0:
        raise ValueError("positions have zero total value")

    n = len(positions)
    w_b = 1.0 / n  # 等权基准（MVP 简化）

    selection = 0.0
    allocation = 0.0
    portfolio_return = 0.0
    benchmark_return = 0.0

    for p in positions:
        w_p = (p.quantity * p.cost_basis) / total_value
        r_p = 0.0  # MVP：无可用当前价 → 默认 0
        r_b = float(benchmark_returns.get(p.ticker, 0.0))

        portfolio_return += w_p * r_p
        benchmark_return += w_p * r_b  # 注: 严格 Brinson 是 weight_b * r_b，这里用 weight_p 近似

        # 选股贡献：(选股实际收益 - 该股基准收益) × 该股权重
        selection += w_p * (r_p - r_b)
        # 行业（基准权重）贡献：(实际权重 - 基准权重) × 基准收益
        allocation += (w_p - w_b) * r_b

    return {
        "portfolio_return": round(portfolio_return, 6),
        "benchmark_return": round(benchmark_return, 6),
        "selection_effect": round(selection, 6),
        "allocation_effect": round(allocation, 6),
        "total_effect": round(selection + allocation, 6),
    }


# ── 2.7 权益曲线（MVP 占位） ─────────────────────────────────────────────────


def compute_equity_curve(
    positions: list[Position],
    transactions: list[Transaction],
    current_prices: dict[str, float],
    days: int = 30,
) -> list[tuple[date, float]]:
    """重建过去 N 天的组合权益曲线（用于 Sharpe / MaxDrawdown 喂数据）。

    MVP 占位实现: 因为重建历史 K 线需要新数据源（东财 push2his / sina HTTP），
    超出 v0.5.0 P0 范围。这里返回单点曲线 [(today, total_value)]，UI 层
    不调用此函数（避免显示"完美"的曲线欺骗用户）。
    """
    total = 0.0
    for p in positions:
        price = float(current_prices.get(p.ticker, p.cost_basis))
        total += price * p.quantity
    _ = (positions, transactions, days)  # 占位参数，未来 P2 历史 K 线实装时启用
    return [(_today(), round(total, 2))]


# ── 2.8 调仓推送 ────────────────────────────────────────────────────────────


def get_rebalance_signals(lookback_days: int = 7) -> list[dict]:
    """调仓推送：diff 最近 7 天的 Bull/Bear 报告，找出 signal 变化。

    数据源: backend.core.history_store.HistoryStore（已有）。

    返回:
      [{ticker, old_signal, new_signal, detected_at, analysis_ids: [old_id, new_id]}, ...]

    实现:
      1. history_store.list_all(limit=200) → 最近 200 条 history
      2. group by ticker → dict[ticker, list[entry]]（按 created_at 升序）
      3. 每个 ticker 取最近 2 条，diff signal
      4. 如果不同 + 最新的 created_at 在 lookback_days 内 → 加入结果
      5. 返回 list[dict]

    注意: 不要 import a_stock / 任何 LLM / 任何 IO，只读 history_store
    （它本身是 IO 抽象层）。
    """
    # 延迟导入避免循环依赖 + 测试隔离方便
    from backend.core.history_store import HistoryStore

    store = HistoryStore.get_instance()
    try:
        entries, _total = store.list_all(limit=200)
    except Exception:
        # history 不可用（极端情况）：返回空
        return []

    # 过滤掉未完成 / 错误状态 + 没信号的空 entry
    valid_entries = [
        e for e in entries
        if e.status == "completed" and e.signal
    ]

    # group by ticker
    by_ticker: dict[str, list] = {}
    for e in valid_entries:
        by_ticker.setdefault(e.ticker, []).append(e)

    results: list[dict] = []
    cutoff = _today().toordinal() - lookback_days  # 粗略窗口（按创建日）

    for ticker, items in by_ticker.items():
        # 按 created_at 升序（list_all 已按降序 → reverse）
        items.sort(key=lambda x: x.created_at)
        if len(items) < 2:
            continue
        old, new = items[-2], items[-1]
        if old.signal == new.signal:
            continue
        # 检查"最新信号"在 lookback_days 窗口内
        # created_at 是 Unix 时间戳，需要转换
        try:
            new_date = datetime.fromtimestamp(new.created_at).date()
        except (OSError, ValueError, OverflowError):
            continue
        if new_date.toordinal() < cutoff:
            continue

        results.append({
            "ticker": ticker,
            "old_signal": old.signal,
            "new_signal": new.signal,
            "detected_at": new_date.isoformat(),
            "analysis_ids": [old.analysis_id, new.analysis_id],
        })

    return results


# ── 2.9 年化收益工具 ────────────────────────────────────────────────────────


def compute_annual_return(start_value: float, end_value: float, days: int) -> float:
    """年化收益 = (end / start) ^ (365 / days) - 1

    用于 portfolio_panel.py 显示"如果等效成整年的收益率"。

    边界:
      - start_value <= 0 → 0.0（无法计算）
      - days <= 0 → 0.0（避免除零）
    """
    if start_value <= 0 or days <= 0:
        return 0.0
    ratio = end_value / start_value
    if ratio <= 0:
        return 0.0
    return ratio ** (365.0 / days) - 1.0


# ── 废弃 API（仅保留兼容旧版 portfolio_panel.py，将在 Round 3-4 移除）────────


def group_by_sector(
    positions: list[Position],
    current_prices: dict[str, float],
) -> dict[str, float]:
    """[已废弃] 板块归因——新版本请改用 compute_portfolio_summary + get_sector_fn 回调。

    本函数保留是为了不破坏现有 web/components/portfolio_panel.py（Round 3-4
    会更新该调用方）；新代码**不要**直接调用本函数。

    实现: 尝试调 a_stock.get_concept_blocks(ticker)；IO 失败则回退到 {"其他": total}。
    """
    try:
        from tradingagents.dataflows.a_stock import get_concept_blocks
    except Exception:
        return {
            "其他": sum(
                current_prices.get(p.ticker, p.cost_basis) * p.quantity
                for p in positions
            )
        }

    out: dict[str, float] = {}
    fallback = 0.0
    for pos in positions:
        try:
            raw = get_concept_blocks(pos.ticker)
        except Exception:
            raw = ""
        sectors = _concept_block_to_sectors(raw)
        value = current_prices.get(pos.ticker, pos.cost_basis) * pos.quantity
        if not sectors:
            fallback += value
            continue
        share = value / len(sectors)
        for s in sectors:
            out[s] = out.get(s, 0.0) + share
    if fallback and not out:
        out["其他"] = fallback
    return {k: round(v, 2) for k, v in out.items()}


def _concept_block_to_sectors(raw: str) -> list[str]:
    """[已废弃] 解析 get_concept_blocks 返回的 markdown → sector 名列表。"""
    if not raw:
        return []
    sectors: list[str] = []
    in_industry = False
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_industry = s[3:] == "行业"
            continue
        if in_industry and s and not s.startswith("#"):
            name = s.split(":")[0].split("(")[0].strip()
            if name and name not in sectors:
                sectors.append(name)
        if s.lower().startswith("concept tags:"):
            tag_blob = s.split(":", 1)[1].strip() if ":" in s else ""
            for tag in tag_blob.split("/"):
                tag = tag.strip()
                if tag and tag not in sectors:
                    sectors.append(tag)
    return sectors


__all__ = [
    # dataclass
    "PositionMetrics",
    "PortfolioSummary",
    # 单一职责函数
    "compute_position_metrics",
    "compute_portfolio_summary",
    "compute_xirr",
    "compute_max_drawdown",
    "compute_sharpe",
    "compute_brinson_attribution",
    "compute_equity_curve",
    "get_rebalance_signals",
    "compute_annual_return",
    # 内部 helper（公开便于测试）
    "_extract_cashflows",
    # 废弃（保留兼容老版 portfolio_panel.py）
    "group_by_sector",
]
