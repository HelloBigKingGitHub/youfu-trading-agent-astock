"""Portfolio store — positions, transactions, alerts on local JSON files.

All portfolio data lives under ~/.tradingagents/portfolio/:
  - positions.json    list of Position dicts
  - transactions.json list of Transaction dicts
  - alerts.json       list of AlertRule dicts
  - audit.log         append-only newline-delimited log for import/export ops

Style mirrors backend/core/history_store.py: dataclass + to_dict/from_dict,
singleton with double-checked lock, JSON files written via JSON files.

Thread safety: PortfolioStore holds a re-entrant lock guarding all read/write
operations. All public methods acquire the lock before touching disk.
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

from tradingagents.dataflows.a_stock import _normalize_ticker  # noqa: E402

PORTFOLIO_DIR: Path = Path.home() / ".tradingagents" / "portfolio"
POSITIONS_FILE = "positions.json"
TRANSACTIONS_FILE = "transactions.json"
ALERTS_FILE = "alerts.json"
AUDIT_FILE = "audit.log"

VALID_TRANSACTION_ACTIONS: tuple[str, ...] = (
    "buy",
    "sell",
    "dividend",
    "split",
    "merge",
    "rights",
)
VALID_ALERT_RULE_TYPES: tuple[str, ...] = (
    "price_above",
    "price_below",
    "pct_change",
    "pnl_pct",
    "take_profit",
    "stop_loss",
    "trailing_stop",
)
VALID_ASSET_CLASSES: tuple[str, ...] = ("stock", "bond", "overseas", "cash")


@dataclass
class Position:
    """A single A-stock position (one ticker per account)."""

    position_id: str
    ticker: str
    name: str
    cost_basis: float
    quantity: int
    first_buy_date: str
    last_trade_date: str
    account: str = "default"
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
            position_id=d.get("position_id", _new_id()),
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
    """A single buy/sell/dividend/split event tied to a position."""

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
            tx_id=d.get("tx_id", _new_id()),
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
    """A price / pnl alert tied to a ticker.

    rule_type meanings:
      - price_above: trigger when current price >= threshold
      - price_below: trigger when current price <= threshold
      - pct_change:  trigger when |today_pct_change| >= threshold (threshold in %)
      - pnl_pct:     trigger when current pnl_pct reaches/exceeds threshold (signed %)
      - take_profit: trigger when current price >= cost_basis * (1 + threshold/100)
      - stop_loss:   trigger when current price <= cost_basis * (1 - threshold/100)
      - trailing_stop: v1 stub — same semantics as stop_loss until P3 lands
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
        return cls(
            rule_id=d.get("rule_id", _new_id()),
            ticker=d.get("ticker", ""),
            rule_type=d.get("rule_type", "price_above"),
            threshold=float(d.get("threshold", 0.0)),
            enabled=bool(d.get("enabled", True)),
            note=d.get("note", ""),
            created_at=float(d.get("created_at", time.time())),
            last_triggered_at=d.get("last_triggered_at"),
            last_triggered_price=(
                float(d["last_triggered_price"])
                if d.get("last_triggered_price") is not None
                else None
            ),
            trigger_count=int(d.get("trigger_count", 0)),
        )


def _new_id() -> str:
    """Generate a short UUID, matching history_store's 12-hex convention."""
    return uuid.uuid4().hex[:12]


class PortfolioStore:
    """Thread-safe singleton portfolio store backed by JSON files.

    Holds positions, transactions, and alert rules. All public methods
    acquire the instance lock before reading/writing disk, so concurrent
    CRUD is safe from a single Streamlit session or FastAPI worker.
    """

    _instance: "PortfolioStore | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # Per-instance re-entrant lock — safe for nested calls within a single
        # method (e.g. add_transaction may later call _audit, which also locks).
        self._rlock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "PortfolioStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Position CRUD ────────────────────────────────────────────────────────

    def add_position(
        self,
        ticker: str,
        name: str,
        cost_basis: float,
        quantity: int,
        first_buy_date: str,
        account: str = "default",
        asset_class: str = "stock",
        notes: str = "",
    ) -> Position:
        if asset_class not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {VALID_ASSET_CLASSES}, got {asset_class!r}"
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
                f"qty={pos.quantity} cost={pos.cost_basis}"
            )
            return pos

    def update_position(self, position_id: str, **fields: Any) -> Position:
        allowed = {
            "name",
            "cost_basis",
            "quantity",
            "last_trade_date",
            "asset_class",
            "notes",
            "account",
            "first_buy_date",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown position fields: {sorted(unknown)}")
        if "asset_class" in fields and fields["asset_class"] not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"asset_class must be one of {VALID_ASSET_CLASSES}, "
                f"got {fields['asset_class']!r}"
            )
        if "ticker" in fields:
            fields["ticker"] = _normalize_ticker(fields["ticker"])

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
                return  # silent no-op for missing id
            self._write(POSITIONS_FILE, new_data)
            # Also delete tied transactions so we don't leave orphans.
            tx_data = self._read(TRANSACTIONS_FILE)
            tx_new = [d for d in tx_data if d.get("position_id") != position_id]
            self._write(TRANSACTIONS_FILE, tx_new)
            self._audit(
                f"delete_position id={position_id} "
                f"removed_tx={len(tx_data) - len(tx_new)}"
            )

    def get_position(self, position_id: str) -> Position | None:
        with self._rlock:
            data = self._read(POSITIONS_FILE)
            for d in data:
                if d.get("position_id") == position_id:
                    return Position.from_dict(d)
            return None

    def list_positions(self, account: str | None = None) -> list[Position]:
        with self._rlock:
            data = self._read(POSITIONS_FILE)
        out: list[Position] = []
        for d in data:
            if account is not None and d.get("account", "default") != account:
                continue
            out.append(Position.from_dict(d))
        out.sort(key=lambda p: p.ticker)
        return out

    # ── Transaction CRUD ─────────────────────────────────────────────────────

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
                f"action must be one of {VALID_TRANSACTION_ACTIONS}, got {action!r}"
            )
        with self._rlock:
            data_pos = self._read(POSITIONS_FILE)
            position = next(
                (
                    p
                    for p in data_pos
                    if p.get("position_id") == position_id
                ),
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

            # Update last_trade_date + quantity on the position.
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
        out: list[Transaction] = []
        for d in data:
            if ticker is not None:
                norm = _normalize_ticker(ticker)
                if d.get("ticker") != norm:
                    continue
            if since is not None and d.get("date", "") < since:
                continue
            out.append(Transaction.from_dict(d))
        out.sort(key=lambda t: t.date, reverse=True)
        return out

    # ── AlertRule CRUD ───────────────────────────────────────────────────────

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
                f"rule_type must be one of {VALID_ALERT_RULE_TYPES}, "
                f"got {rule_type!r}"
            )
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
                f"rule_type must be one of {VALID_ALERT_RULE_TYPES}, "
                f"got {fields['rule_type']!r}"
            )
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
        norm: str | None = _normalize_ticker(ticker) if ticker is not None else None
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

        `now` defaults to wall-clock time but may be passed by `evaluate_alerts`
        so tests can use a deterministic clock without monkeypatching time.time.
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

    # ── Internal IO ──────────────────────────────────────────────────────────

    def _path(self, filename: str) -> Path:
        return PORTFOLIO_DIR / filename

    def _read(self, filename: str) -> list[dict[str, Any]]:
        path = self._path(filename)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, filename: str, data: list[dict[str, Any]]) -> None:
        try:
            PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
            path = self._path(filename)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            pass  # Non-critical — same tolerance as history_store

    def _audit(self, msg: str) -> None:
        """Append a timestamped line to audit.log. Best-effort, never raises."""
        try:
            PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            with open(self._path(AUDIT_FILE), "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except OSError:
            pass


def get_portfolio_store() -> PortfolioStore:
    """Return module-level singleton PortfolioStore."""
    return PortfolioStore.get_instance()