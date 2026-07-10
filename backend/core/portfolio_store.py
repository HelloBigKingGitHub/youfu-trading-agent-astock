"""Portfolio store — JSON file persistence for positions, transactions, alerts, accounts.

仿 backend/core/history_store.py 风格：dataclass + 单例 + 线程锁 + JSON 文件。
所有 4 个实体存 ~/.tradingagents/portfolio/，audit.log 追加。

设计要点：
  * 单例：双检锁 + 类级 RLock + 实例级 RLock（兼容 `get_instance()` 与 `PortfolioStore()` 两种构造）
  * 原子写：tmp 文件 + replace，避免半写状态
  * 防御性：a_stock 不可用时 `_normalize_ticker` 退化为恒等映射
  * 账户引用：Position.account 引用 Account.name，外键缺失时拒绝写入
  * 幂等启动：`ensure_default_account()` 在 __init__ 中自动调用
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 模块级路径常量 —— 同时导出 `PORTFOLIO_DIR`（测试 fixture monkeypatch 用）
# 和内部 `_PORTFOLIO_DIR`（spec 用名），两者指向同一 Path。
_PORTFOLIO_DIR: Path = Path.home() / ".tradingagents" / "portfolio"
PORTFOLIO_DIR: Path = _PORTFOLIO_DIR

POSITIONS_FILE = "positions.json"
TRANSACTIONS_FILE = "transactions.json"
ALERTS_FILE = "alerts.json"
ACCOUNTS_FILE = "accounts.json"  # v0.5.0 新增
AUDIT_FILE = "audit.log"

# 合法值集合（使用 set 而非 tuple，便于 O(1) `in` 检查）
VALID_TRANSACTION_ACTIONS: frozenset[str] = frozenset(
    {"buy", "sell", "dividend", "split", "merge", "rights"}
)
VALID_ALERT_RULE_TYPES: frozenset[str] = frozenset(
    {
        "price_above",
        "price_below",
        "pct_change",
        "pnl_pct",
        "take_profit",
        "stop_loss",
        "trailing_stop",
    }
)
VALID_ASSET_CLASSES: frozenset[str] = frozenset(
    {"stock", "bond", "overseas", "cash", "fund"}
)


# ── Defensive _normalize_ticker import ────────────────────────────────────
# a_stock 在某些精简环境（仅跑 backend 测试时）可能不可用。
# 退化为恒等映射：原 ticker 透传，不抛 ImportError。
try:
    from tradingagents.dataflows.a_stock import _normalize_ticker as _normalize_ticker  # type: ignore[attr-defined]  # noqa: E402
except (ImportError, AttributeError):
    def _normalize_ticker(ticker: str) -> str:  # type: ignore[no-redef]
        """退化实现：去掉首尾空白，其它保持原样。"""
        return (ticker or "").strip()


def _new_id() -> str:
    """生成 12-hex id，与 history_store 的 analysis_id 风格保持一致。"""
    return uuid.uuid4().hex[:12]


# ── Dataclasses ───────────────────────────────────────────────────────────


@dataclass
class Position:
    """A 股单条持仓（同一 ticker + account 唯一）。"""

    position_id: str
    ticker: str
    name: str
    cost_basis: float
    quantity: int
    first_buy_date: str
    last_trade_date: str
    account: str  # 引用 Account.name（外键）
    asset_class: str = "stock"
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "ticker": self.ticker,
            "name": self.name,
            "cost_basis": self.cost_basis,
            "quantity": self.quantity,
            "first_buy_date": self.first_buy_date,
            "last_trade_date": self.last_trade_date,
            "account": self.account,
            "asset_class": self.asset_class,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Position":
        return cls(
            position_id=d.get("position_id") or _new_id(),
            ticker=d.get("ticker", ""),
            name=d.get("name", ""),
            cost_basis=float(d.get("cost_basis", 0.0)),
            quantity=int(d.get("quantity", 0)),
            first_buy_date=d.get("first_buy_date", ""),
            last_trade_date=d.get("last_trade_date", ""),
            account=d.get("account", "default"),
            asset_class=d.get("asset_class", "stock"),
            notes=d.get("notes", ""),
            created_at=float(d.get("created_at", time.time())),
        )


@dataclass
class Transaction:
    """单条交易流水（买入 / 卖出 / 分红 / 送股 / 并股 / 配股）。"""

    tx_id: str
    position_id: str
    ticker: str
    date: str
    action: str  # one of VALID_TRANSACTION_ACTIONS
    price: float
    quantity: int
    fees: float = 0.0
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "position_id": self.position_id,
            "ticker": self.ticker,
            "date": self.date,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "fees": self.fees,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transaction":
        return cls(
            tx_id=d.get("tx_id") or _new_id(),
            position_id=d.get("position_id", ""),
            ticker=d.get("ticker", ""),
            date=d.get("date", ""),
            action=d.get("action", "buy"),
            price=float(d.get("price", 0.0)),
            quantity=int(d.get("quantity", 0)),
            fees=float(d.get("fees", 0.0)),
            notes=d.get("notes", ""),
            created_at=float(d.get("created_at", time.time())),
        )


@dataclass
class AlertRule:
    """价格 / 盈亏预警规则。

    rule_type 取值（见 VALID_ALERT_RULE_TYPES）：
      - price_above:    现价 >= threshold 触发
      - price_below:    现价 <= threshold 触发
      - pct_change:     |当日涨跌幅%| >= threshold 触发
      - pnl_pct:        当前盈亏% >= threshold 触发（有符号）
      - take_profit:    现价 >= 成本 * (1 + threshold/100)
      - stop_loss:      现价 <= 成本 * (1 - threshold/100)
      - trailing_stop:  v1 stub —— 语义同 stop_loss，P3 实现真实 trailing
    """

    rule_id: str
    ticker: str
    rule_type: str
    threshold: float
    enabled: bool = True
    note: str = ""
    created_at: float = field(default_factory=time.time)
    last_triggered_at: float | None = None
    last_triggered_price: float | None = None
    trigger_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "ticker": self.ticker,
            "rule_type": self.rule_type,
            "threshold": self.threshold,
            "enabled": self.enabled,
            "note": self.note,
            "created_at": self.created_at,
            "last_triggered_at": self.last_triggered_at,
            "last_triggered_price": self.last_triggered_price,
            "trigger_count": self.trigger_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AlertRule":
        last_price = d.get("last_triggered_price")
        return cls(
            rule_id=d.get("rule_id") or _new_id(),
            ticker=d.get("ticker", ""),
            rule_type=d.get("rule_type", "price_above"),
            threshold=float(d.get("threshold", 0.0)),
            enabled=bool(d.get("enabled", True)),
            note=d.get("note", ""),
            created_at=float(d.get("created_at", time.time())),
            last_triggered_at=d.get("last_triggered_at"),
            last_triggered_price=float(last_price) if last_price is not None else None,
            trigger_count=int(d.get("trigger_count", 0)),
        )


@dataclass
class Account:
    """账户实体（v0.5.0 增量）。

    - `name` 全局唯一（UI 显示名，中文友好）
    - `is_default=True` 同一时刻全局最多 1 个，由 set_default_account 强制
    - `asset_class` 是账户级默认，Position.asset_class=None 时继承该值
    """

    account_id: str
    name: str  # 唯一键
    broker: str = ""
    account_number_tail: str = ""
    asset_class: str = "stock"  # 账户级默认资产类别
    notes: str = ""
    is_default: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "broker": self.broker,
            "account_number_tail": self.account_number_tail,
            "asset_class": self.asset_class,
            "notes": self.notes,
            "is_default": self.is_default,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Account":
        return cls(
            account_id=d.get("account_id") or _new_id(),
            name=d.get("name", ""),
            broker=d.get("broker", ""),
            account_number_tail=d.get("account_number_tail", ""),
            asset_class=d.get("asset_class", "stock"),
            notes=d.get("notes", ""),
            is_default=bool(d.get("is_default", False)),
            created_at=float(d.get("created_at", time.time())),
        )


# ── Store ─────────────────────────────────────────────────────────────────


class PortfolioStore:
    """线程安全的单例组合存储。

    所有 CRUD 方法在内部加 RLock；RLock 允许同一线程重入（add_* 内部调
    _audit 时 lock 不会死锁）。`get_instance()` 是访问单例的推荐入口；
    测试可以通过 `PortfolioStore()` 显式构造（不走单例缓存），但需要
    自行管理生命周期。
    """

    _instance: "PortfolioStore | None" = None
    _lock = __import__("threading").Lock()  # class-level 守卫

    def __init__(self) -> None:
        # 实例级 RLock：spec 称之为 `_lock_path`，但为兼容已存在的测试
        # 同时保留 `_rlock` 别名（同一把锁）。
        self._rlock = __import__("threading").RLock()
        self._lock_path = self._rlock  # spec 命名（同一对象）
        # 内部缓存：filename -> list[dict]。避免每次 list_* 都读盘。
        # 单进程内一致即可；多进程不在本模块的处理范围（Streamlit + CLI 串行）。
        self._cache: dict[str, list[dict[str, Any]]] = {}
        # 启动时幂等建账户：避免 UI 首次进入时找不到 default 账户
        self.ensure_default_account()

    @classmethod
    def get_instance(cls) -> "PortfolioStore":
        """双检锁获取单例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Position CRUD ──────────────────────────────────────────────────────

    def add_position(
        self,
        ticker: str,
        name: str,
        cost_basis: float,
        quantity: int,
        first_buy_date: str,
        account: str = "default",
        asset_class: str | None = None,
        notes: str = "",
    ) -> Position:
        # 1. 校验 account 存在
        acc = self.get_account_by_name(account)
        if acc is None:
            raise ValueError(
                f"账户 '{account}' 不存在，请先在 Tab 7 账户管理创建"
            )
        # 2. asset_class：None → 继承账户；显式传值则校验合法性
        if asset_class is None:
            asset_class = acc.asset_class
        if asset_class not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {sorted(VALID_ASSET_CLASSES)}, "
                f"got {asset_class!r}"
            )
        if quantity < 0:
            raise ValueError(f"quantity must be >= 0, got {quantity}")

        norm_ticker = _normalize_ticker(ticker)
        with self._rlock:
            pos = Position(
                position_id=_new_id(),
                ticker=norm_ticker,
                name=name,
                cost_basis=float(cost_basis),
                quantity=int(quantity),
                first_buy_date=first_buy_date,
                last_trade_date=first_buy_date,
                account=account,
                asset_class=asset_class,
                notes=notes,
            )
            data = self._read(POSITIONS_FILE)
            data.append(pos.to_dict())
            self._write(POSITIONS_FILE, data)
            self._audit(
                f"add_position id={pos.position_id} ticker={pos.ticker} "
                f"qty={pos.quantity} cost={pos.cost_basis} account={pos.account}"
            )
            return pos

    def update_position(self, position_id: str, **fields: Any) -> Position:
        # spec 明确禁止：position_id / ticker 不可改
        if "position_id" in fields:
            raise ValueError("position_id is immutable")
        if "ticker" in fields:
            raise ValueError("ticker is immutable; create a new position instead")

        # 合法可改字段
        allowed = {
            "name",
            "cost_basis",
            "quantity",
            "first_buy_date",
            "last_trade_date",
            "account",
            "asset_class",
            "notes",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown position fields: {sorted(unknown)}")

        if "asset_class" in fields and fields["asset_class"] not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {sorted(VALID_ASSET_CLASSES)}, "
                f"got {fields['asset_class']!r}"
            )
        if "account" in fields:
            # 改 account 时必须指向已存在账户
            if self.get_account_by_name(fields["account"]) is None:
                raise ValueError(
                    f"账户 '{fields['account']}' 不存在，请先在 Tab 7 账户管理创建"
                )

        with self._rlock:
            data = self._read(POSITIONS_FILE)
            for i, d in enumerate(data):
                if d.get("position_id") == position_id:
                    for k, v in fields.items():
                        data[i][k] = v
                    self._write(POSITIONS_FILE, data)
                    self._audit(
                        f"update_position id={position_id} fields={sorted(fields)}"
                    )
                    return Position.from_dict(data[i])
            raise KeyError(f"position_id {position_id!r} not found")

    def delete_position(self, position_id: str) -> None:
        with self._rlock:
            data = self._read(POSITIONS_FILE)
            new_data = [d for d in data if d.get("position_id") != position_id]
            if len(new_data) == len(data):
                return  # silent no-op
            self._write(POSITIONS_FILE, new_data)
            # 级联删除：避免悬挂流水
            tx_data = self._read(TRANSACTIONS_FILE)
            tx_new = [d for d in tx_data if d.get("position_id") != position_id]
            if len(tx_new) != len(tx_data):
                self._write(TRANSACTIONS_FILE, tx_new)
            self._audit(
                f"delete_position id={position_id} "
                f"removed_tx={len(tx_data) - len(tx_new)}"
            )

    def get_position(self, position_id: str) -> Position | None:
        with self._rlock:
            for d in self._read(POSITIONS_FILE):
                if d.get("position_id") == position_id:
                    return Position.from_dict(d)
            return None

    def list_positions(
        self,
        account: str | None = None,
        asset_class: str | None = None,
    ) -> list[Position]:
        """列出所有持仓，可选按 account / asset_class 过滤（AND 关系）。"""
        with self._rlock:
            data = self._read(POSITIONS_FILE)
        out: list[Position] = []
        for d in data:
            if account is not None and d.get("account", "default") != account:
                continue
            if asset_class is not None and d.get("asset_class", "stock") != asset_class:
                continue
            out.append(Position.from_dict(d))
        out.sort(key=lambda p: p.ticker)
        return out

    # ── Transaction CRUD ──────────────────────────────────────────────────

    def add_transaction(
        self,
        position_id: str,
        date: str,
        action: str,
        price: float,
        quantity: int,
        fees: float = 0.0,
        notes: str = "",
    ) -> Transaction:
        if action not in VALID_TRANSACTION_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(VALID_TRANSACTION_ACTIONS)}, "
                f"got {action!r}"
            )
        with self._rlock:
            data_pos = self._read(POSITIONS_FILE)
            position = next(
                (p for p in data_pos if p.get("position_id") == position_id),
                None,
            )
            if position is None:
                raise KeyError(f"position_id {position_id!r} not found")
            ticker = position["ticker"]

            tx = Transaction(
                tx_id=_new_id(),
                position_id=position_id,
                ticker=ticker,
                date=date,
                action=action,
                price=float(price),
                quantity=int(quantity),
                fees=float(fees),
                notes=notes,
            )
            tx_data = self._read(TRANSACTIONS_FILE)
            tx_data.append(tx.to_dict())
            self._write(TRANSACTIONS_FILE, tx_data)

            # 反向更新持仓的 last_trade_date / quantity
            for i, p in enumerate(data_pos):
                if p.get("position_id") == position_id:
                    if date > p.get("last_trade_date", ""):
                        data_pos[i]["last_trade_date"] = date
                    if action == "buy":
                        data_pos[i]["quantity"] = int(p.get("quantity", 0)) + int(quantity)
                    elif action == "sell":
                        new_qty = int(p.get("quantity", 0)) - int(quantity)
                        if new_qty < 0:
                            raise ValueError(
                                f"sell quantity {quantity} exceeds held quantity "
                                f"{p.get('quantity', 0)} for position {position_id}"
                            )
                        data_pos[i]["quantity"] = new_qty
                    break
            self._write(POSITIONS_FILE, data_pos)
            self._audit(
                f"add_transaction id={tx.tx_id} position_id={position_id} "
                f"action={action} qty={tx.quantity} price={tx.price}"
            )
            return tx

    def list_transactions(
        self,
        ticker: str | None = None,
        since: str | None = None,
    ) -> list[Transaction]:
        with self._rlock:
            data = self._read(TRANSACTIONS_FILE)
        norm = _normalize_ticker(ticker) if ticker is not None else None
        out: list[Transaction] = []
        for d in data:
            if norm is not None and d.get("ticker") != norm:
                continue
            if since is not None and d.get("date", "") < since:
                continue
            out.append(Transaction.from_dict(d))
        out.sort(key=lambda t: t.date, reverse=True)
        return out

    # ── AlertRule CRUD ────────────────────────────────────────────────────

    def add_alert(
        self,
        ticker: str,
        rule_type: str,
        threshold: float,
        note: str = "",
        enabled: bool = True,
    ) -> AlertRule:
        if rule_type not in VALID_ALERT_RULE_TYPES:
            raise ValueError(
                f"rule_type must be one of {sorted(VALID_ALERT_RULE_TYPES)}, "
                f"got {rule_type!r}"
            )
        # threshold 允许任意非零值 —— pnl_pct 用负数表示亏损阈值
        # （spec 写的是 > 0，但现有 pnl_pct 测试用 threshold=-10 触发亏损）
        if threshold == 0:
            raise ValueError(f"threshold must be non-zero, got {threshold}")
        norm_ticker = _normalize_ticker(ticker)
        with self._rlock:
            rule = AlertRule(
                rule_id=_new_id(),
                ticker=norm_ticker,
                rule_type=rule_type,
                threshold=float(threshold),
                enabled=enabled,
                note=note,
            )
            data = self._read(ALERTS_FILE)
            data.append(rule.to_dict())
            self._write(ALERTS_FILE, data)
            self._audit(
                f"add_alert id={rule.rule_id} ticker={rule.ticker} "
                f"type={rule.rule_type} threshold={rule.threshold}"
            )
            return rule

    def update_alert(self, rule_id: str, **fields: Any) -> AlertRule:
        allowed = {
            "ticker",
            "rule_type",
            "threshold",
            "enabled",
            "note",
            "last_triggered_at",
            "last_triggered_price",
            "trigger_count",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown alert fields: {sorted(unknown)}")
        if "rule_type" in fields and fields["rule_type"] not in VALID_ALERT_RULE_TYPES:
            raise ValueError(
                f"rule_type must be one of {sorted(VALID_ALERT_RULE_TYPES)}, "
                f"got {fields['rule_type']!r}"
            )
        if "threshold" in fields and float(fields["threshold"]) == 0:
            raise ValueError(f"threshold must be non-zero, got {fields['threshold']}")
        if "ticker" in fields:
            fields["ticker"] = _normalize_ticker(fields["ticker"])

        with self._rlock:
            data = self._read(ALERTS_FILE)
            for i, d in enumerate(data):
                if d.get("rule_id") == rule_id:
                    for k, v in fields.items():
                        data[i][k] = v
                    self._write(ALERTS_FILE, data)
                    self._audit(
                        f"update_alert id={rule_id} fields={sorted(fields)}"
                    )
                    return AlertRule.from_dict(data[i])
            raise KeyError(f"rule_id {rule_id!r} not found")

    def delete_alert(self, rule_id: str) -> None:
        with self._rlock:
            data = self._read(ALERTS_FILE)
            new_data = [d for d in data if d.get("rule_id") != rule_id]
            if len(new_data) == len(data):
                return  # silent no-op
            self._write(ALERTS_FILE, new_data)
            self._audit(f"delete_alert id={rule_id}")

    def list_alerts(
        self,
        ticker: str | None = None,
        enabled_only: bool = False,
    ) -> list[AlertRule]:
        with self._rlock:
            data = self._read(ALERTS_FILE)
        norm = _normalize_ticker(ticker) if ticker is not None else None
        out: list[AlertRule] = []
        for d in data:
            if norm is not None and d.get("ticker") != norm:
                continue
            if enabled_only and not d.get("enabled", True):
                continue
            out.append(AlertRule.from_dict(d))
        out.sort(key=lambda r: (r.ticker, r.created_at))
        return out

    def record_trigger(self, rule_id: str, price: float, now: float | None = None) -> None:
        """Stamp last_triggered_at + last_triggered_price, bump trigger_count.

        `now` 默认为 wall-clock time，但允许 `evaluate_alerts` 注入确定性时间
        以便测试 mock 时钟。Raises KeyError if rule_id not found.
        """
        ts = now if now is not None else time.time()
        with self._rlock:
            data = self._read(ALERTS_FILE)
            for i, d in enumerate(data):
                if d.get("rule_id") == rule_id:
                    data[i]["last_triggered_at"] = ts
                    data[i]["last_triggered_price"] = float(price)
                    data[i]["trigger_count"] = int(d.get("trigger_count", 0)) + 1
                    self._write(ALERTS_FILE, data)
                    self._audit(
                        f"record_trigger id={rule_id} price={price} "
                        f"count={data[i]['trigger_count']}"
                    )
                    return
            raise KeyError(f"rule_id {rule_id!r} not found")

    # ── Account CRUD (v0.5.0 增量) ────────────────────────────────────────

    def add_account(
        self,
        name: str,
        broker: str = "",
        account_number_tail: str = "",
        asset_class: str = "stock",
        notes: str = "",
        is_default: bool = False,
    ) -> Account:
        """新增账户。name 必须唯一；is_default=True 会让其它账户让位。"""
        name = (name or "").strip()
        if not name:
            raise ValueError("账户名不能为空")
        if asset_class not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {sorted(VALID_ASSET_CLASSES)}, "
                f"got {asset_class!r}"
            )
        with self._rlock:
            if self.get_account_by_name(name) is not None:
                raise ValueError(f"账户名 '{name}' 已存在")
            # is_default 副作用：先把所有账户置 False
            if is_default:
                data = self._read(ACCOUNTS_FILE)
                for d in data:
                    d["is_default"] = False
                self._write(ACCOUNTS_FILE, data)
            acc = Account(
                account_id=_new_id(),
                name=name,
                broker=broker,
                account_number_tail=account_number_tail,
                asset_class=asset_class,
                notes=notes,
                is_default=is_default,
            )
            data = self._read(ACCOUNTS_FILE)
            data.append(acc.to_dict())
            self._write(ACCOUNTS_FILE, data)
            self._audit(
                f"add_account id={acc.account_id} name={acc.name} "
                f"is_default={acc.is_default}"
            )
            return acc

    def update_account(self, account_id: str, **fields: Any) -> Account:
        """更新账户字段。name 改字符串值即可（持仓以字符串引用，不级联）。"""
        if "account_id" in fields:
            raise ValueError("account_id is immutable")
        allowed = {
            "name",
            "broker",
            "account_number_tail",
            "asset_class",
            "notes",
            "is_default",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown account fields: {sorted(unknown)}")
        if "asset_class" in fields and fields["asset_class"] not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {sorted(VALID_ASSET_CLASSES)}, "
                f"got {fields['asset_class']!r}"
            )
        with self._rlock:
            data = self._read(ACCOUNTS_FILE)
            target_idx: int | None = None
            target: dict[str, Any] | None = None
            for i, d in enumerate(data):
                if d.get("account_id") == account_id:
                    target_idx = i
                    target = d
                    break
            if target is None:
                raise KeyError(f"account_id {account_id!r} not found")
            # name 冲突检查
            if "name" in fields:
                new_name = (fields["name"] or "").strip()
                if not new_name:
                    raise ValueError("账户名不能为空")
                for j, d in enumerate(data):
                    if j != target_idx and d.get("name") == new_name:
                        raise ValueError(f"账户名 '{new_name}' 已存在")
                fields["name"] = new_name
            # is_default 副作用
            if fields.get("is_default") is True:
                for d in data:
                    d["is_default"] = False
            for k, v in fields.items():
                target[k] = v
            self._write(ACCOUNTS_FILE, data)
            self._audit(
                f"update_account id={account_id} fields={sorted(fields)}"
            )
            return Account.from_dict(target)

    def delete_account(self, account_id: str) -> None:
        """删除账户。下有持仓则阻断；删后不自动重建 default。"""
        with self._rlock:
            data = self._read(ACCOUNTS_FILE)
            target = next(
                (d for d in data if d.get("account_id") == account_id), None
            )
            if target is None:
                return  # silent no-op
            name = target.get("name", "")
            # 引用阻断：账户下还有持仓 → 拒绝删除
            held = self.list_positions(account=name)
            if held:
                raise ValueError(
                    f"账户 '{name}' 下还有 {len(held)} 只持仓，请先迁移或删除"
                )
            data = [d for d in data if d.get("account_id") != account_id]
            self._write(ACCOUNTS_FILE, data)
            self._audit(f"delete_account id={account_id} name={name}")

    def get_account(self, account_id: str) -> Account | None:
        with self._rlock:
            for d in self._read(ACCOUNTS_FILE):
                if d.get("account_id") == account_id:
                    return Account.from_dict(d)
            return None

    def get_account_by_name(self, name: str) -> Account | None:
        if not name:
            return None
        with self._rlock:
            for d in self._read(ACCOUNTS_FILE):
                if d.get("name") == name:
                    return Account.from_dict(d)
            return None

    def list_accounts(self) -> list[Account]:
        with self._rlock:
            data = self._read(ACCOUNTS_FILE)
        out = [Account.from_dict(d) for d in data]
        # 默认账户置顶，其余按 created_at 升序
        out.sort(
            key=lambda a: (not a.is_default, a.created_at, a.name)
        )
        return out

    def set_default_account(self, account_id: str) -> None:
        """强制将指定账户设为 default，其它账户自动让位。

        至少保留 1 个 default：旧 default 自动变 False，新 default 变 True。
        不存在 → raise ValueError。
        """
        with self._rlock:
            data = self._read(ACCOUNTS_FILE)
            target = next(
                (d for d in data if d.get("account_id") == account_id), None
            )
            if target is None:
                raise ValueError(f"account_id {account_id!r} 不存在")
            for d in data:
                d["is_default"] = False
            target["is_default"] = True
            self._write(ACCOUNTS_FILE, data)
            self._audit(
                f"set_default_account id={account_id} name={target.get('name')}"
            )

    def ensure_default_account(self) -> Account:
        """幂等启动逻辑。

        1. accounts.json 不存在/为空 → 创建默认账户
        2. 已存在 default → no-op 并返回它
        3. 没有任何 default（被删光）→ 把**最早创建**的账户置为 default
           （不新建，避免账户列表无限增长）
        """
        with self._rlock:
            data = self._read(ACCOUNTS_FILE)
            if not data:
                # 全新环境：建一个自动 default
                acc = Account(
                    account_id=_new_id(),
                    name="default",
                    broker="",
                    account_number_tail="",
                    asset_class="stock",
                    notes="自动创建",
                    is_default=True,
                )
                data.append(acc.to_dict())
                self._write(ACCOUNTS_FILE, data)
                self._audit(f"ensure_default_account created id={acc.account_id}")
                return acc
            # 找一个 default
            for d in data:
                if d.get("is_default"):
                    return Account.from_dict(d)
            # 没有 default → 把最早创建的设为 default
            earliest = min(data, key=lambda d: float(d.get("created_at", 0.0)))
            earliest["is_default"] = True
            self._write(ACCOUNTS_FILE, data)
            self._audit(
                f"ensure_default_account promoted id={earliest.get('account_id')} "
                f"name={earliest.get('name')}"
            )
            return Account.from_dict(earliest)

    # ── Internal IO ───────────────────────────────────────────────────────

    def _path(self, filename: str) -> Path:
        # 通过模块名（而不是直接用 _PORTFOLIO_DIR）解析路径，让测试
        # `monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)`
        # 能够生效 —— 这是测试 fixture 隔离的契约。
        return PORTFOLIO_DIR / filename

    def _read(self, filename: str) -> list[dict[str, Any]]:
        # 命中缓存直接返回
        if filename in self._cache:
            return self._cache[filename]
        path = self._path(filename)
        if not path.exists():
            self._cache[filename] = []
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            self._cache[filename] = []
            return []
        if not raw.strip():
            self._cache[filename] = []
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._cache[filename] = []
            return []
        if not isinstance(data, list):
            self._cache[filename] = []
            return []
        self._cache[filename] = data
        return data

    def _write(self, filename: str, data: list[dict[str, Any]]) -> None:
        # 先更新缓存，保证后续 _read 看到新值
        self._cache[filename] = data
        try:
            PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
            path = self._path(filename)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)  # 原子替换
        except OSError:
            pass  # Non-critical —— 与 history_store 同样的容忍度

    def _audit(self, msg: str) -> None:
        """追加一行到 audit.log。best-effort，永不抛异常。"""
        try:
            PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            with open(self._path(AUDIT_FILE), "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except OSError:
            pass


def get_portfolio_store() -> PortfolioStore:
    """模块级便捷访问：返回单例 PortfolioStore。"""
    return PortfolioStore.get_instance()
