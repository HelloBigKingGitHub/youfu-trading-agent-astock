"""Tests for backend.core.portfolio_store."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.core.portfolio_store import (
    AUDIT_FILE,
    PORTFOLIO_DIR,
    POSITIONS_FILE,
    TRANSACTIONS_FILE,
    ALERTS_FILE,
    AlertRule,
    PortfolioStore,
    Position,
    Transaction,
    VALID_ALERT_RULE_TYPES,
    VALID_ASSET_CLASSES,
    VALID_TRANSACTION_ACTIONS,
    get_portfolio_store,
)


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_portfolio(tmp_path, monkeypatch):
    """Redirect PORTFOLIO_DIR to tmp_path; reset singleton + lock state."""
    monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
    # Each test gets its own singleton so prior tests don't leak data.
    monkeypatch.setattr("backend.core.portfolio_store.PortfolioStore._instance", None)
    return tmp_path


@pytest.fixture
def store(tmp_portfolio):
    return PortfolioStore()


# ── Singleton / init ────────────────────────────────────────────────


class TestStoreInit:

    def test_singleton_returns_same_instance(self, store, tmp_portfolio):
        """get_instance() returns one object across calls."""
        a = PortfolioStore.get_instance()
        b = PortfolioStore.get_instance()
        assert a is b

    def test_get_portfolio_store_helper(self, store, tmp_portfolio):
        """get_portfolio_store() matches get_instance()."""
        assert get_portfolio_store() is PortfolioStore.get_instance()

    def test_writes_files_under_tmp_path(self, store, tmp_portfolio):
        """After adding a position, positions.json appears under tmp_path."""
        store.add_position("600595", "中航电子", 10.0, 100, "2026-01-15")
        assert (tmp_portfolio / POSITIONS_FILE).exists()
        assert (tmp_portfolio / AUDIT_FILE).exists()


# ── Position CRUD ───────────────────────────────────────────────────


class TestPositionCRUD:

    def test_add_returns_position_with_id(self, store):
        pos = store.add_position(
            ticker="600595", name="中航电子", cost_basis=10.0,
            quantity=100, first_buy_date="2026-01-15",
        )
        assert isinstance(pos, Position)
        assert pos.position_id and len(pos.position_id) == 12
        assert pos.ticker == "600595"
        assert pos.cost_basis == 10.0
        assert pos.quantity == 100
        assert pos.first_buy_date == "2026-01-15"
        assert pos.last_trade_date == "2026-01-15"
        assert pos.account == "default"
        assert pos.asset_class == "stock"

    def test_add_normalizes_ticker(self, store):
        pos = store.add_position(
            ticker="SH600595", name="X", cost_basis=1.0,
            quantity=1, first_buy_date="2026-01-01",
        )
        assert pos.ticker == "600595"

    def test_add_validates_asset_class(self, store):
        with pytest.raises(ValueError, match="asset_class"):
            store.add_position(
                ticker="600595", name="X", cost_basis=1.0, quantity=1,
                first_buy_date="2026-01-01", asset_class="crypto",
            )

    def test_add_validates_quantity(self, store):
        with pytest.raises(ValueError, match="quantity"):
            store.add_position(
                ticker="600595", name="X", cost_basis=1.0,
                quantity=-1, first_buy_date="2026-01-01",
            )

    def test_update_position_changes_fields(self, store):
        pos = store.add_position(
            ticker="600595", name="A", cost_basis=10.0,
            quantity=100, first_buy_date="2026-01-15",
        )
        updated = store.update_position(pos.position_id, cost_basis=11.5, quantity=150)
        assert updated.cost_basis == 11.5
        assert updated.quantity == 150
        assert store.get_position(pos.position_id).cost_basis == 11.5

    def test_update_position_rejects_unknown_field(self, store):
        pos = store.add_position(
            ticker="600595", name="A", cost_basis=10.0,
            quantity=100, first_buy_date="2026-01-15",
        )
        with pytest.raises(ValueError, match="unknown"):
            store.update_position(pos.position_id, hacker_field=True)

    def test_update_position_raises_for_missing_id(self, store):
        with pytest.raises(KeyError, match="not found"):
            store.update_position("deadbeefdead", cost_basis=1.0)

    def test_delete_position_removes_it(self, store):
        pos = store.add_position(
            ticker="600595", name="A", cost_basis=10.0,
            quantity=100, first_buy_date="2026-01-15",
        )
        store.delete_position(pos.position_id)
        assert store.get_position(pos.position_id) is None
        assert all(p.position_id != pos.position_id for p in store.list_positions())

    def test_delete_position_also_cascades_transactions(self, store):
        pos = store.add_position(
            ticker="600595", name="A", cost_basis=10.0,
            quantity=100, first_buy_date="2026-01-15",
        )
        store.add_transaction(
            position_id=pos.position_id, date="2026-02-01",
            action="buy", price=10.0, quantity=50,
        )
        store.delete_position(pos.position_id)
        assert all(tx.position_id != pos.position_id for tx in store.list_transactions())

    def test_delete_missing_position_is_silent_noop(self, store):
        store.delete_position("nonexistent_id")  # should not raise

    def test_get_position_returns_none_for_missing(self, store):
        assert store.get_position("missing") is None

    def test_list_positions_filters_by_account(self, store):
        store.add_position("600595", "A", 10.0, 100, "2026-01-01", account="main")
        store.add_position("000001", "B", 5.0, 200, "2026-01-01", account="other")
        main = store.list_positions(account="main")
        assert len(main) == 1
        assert main[0].ticker == "600595"

    def test_list_positions_sorted_by_ticker(self, store):
        store.add_position("000002", "A", 1.0, 1, "2026-01-01")
        store.add_position("600001", "B", 1.0, 1, "2026-01-01")
        store.add_position("300001", "C", 1.0, 1, "2026-01-01")
        tickers = [p.ticker for p in store.list_positions()]
        assert tickers == sorted(tickers)


# ── Transaction CRUD ────────────────────────────────────────────────


class TestTransactionCRUD:

    def _add_position(self, store, ticker="600595", qty=100, cost=10.0):
        return store.add_position(
            ticker=ticker, name="A", cost_basis=cost,
            quantity=qty, first_buy_date="2026-01-15",
        )

    def test_add_transaction_returns_with_id(self, store):
        pos = self._add_position(store)
        tx = store.add_transaction(
            position_id=pos.position_id, date="2026-02-01",
            action="buy", price=11.0, quantity=50, fees=5.0, notes="加仓",
        )
        assert isinstance(tx, Transaction)
        assert tx.tx_id and len(tx.tx_id) == 12
        assert tx.action == "buy"
        assert tx.fees == 5.0

    def test_add_transaction_validates_action(self, store):
        pos = self._add_position(store)
        with pytest.raises(ValueError, match="action"):
            store.add_transaction(
                position_id=pos.position_id, date="2026-02-01",
                action="unknown", price=10.0, quantity=1,
            )

    def test_add_transaction_rejects_unknown_position(self, store):
        with pytest.raises(KeyError, match="not found"):
            store.add_transaction(
                position_id="missing", date="2026-02-01",
                action="buy", price=10.0, quantity=1,
            )

    def test_add_buy_increments_quantity(self, store):
        pos = self._add_position(store, qty=100)
        store.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50)
        assert store.get_position(pos.position_id).quantity == 150

    def test_add_sell_decrements_quantity(self, store):
        pos = self._add_position(store, qty=100)
        store.add_transaction(pos.position_id, "2026-02-01", "sell", 12.0, 30)
        assert store.get_position(pos.position_id).quantity == 70

    def test_add_sell_validates_quantity(self, store):
        pos = self._add_position(store, qty=100)
        with pytest.raises(ValueError, match="exceeds"):
            store.add_transaction(pos.position_id, "2026-02-01", "sell", 12.0, 200)

    def test_add_transaction_updates_last_trade_date(self, store):
        pos = self._add_position(store)
        store.add_transaction(pos.position_id, "2026-03-01", "buy", 11.0, 50)
        assert store.get_position(pos.position_id).last_trade_date == "2026-03-01"

    def test_list_transactions_filters_by_ticker(self, store):
        p1 = self._add_position(store, ticker="600595")
        p2 = self._add_position(store, ticker="000001")
        store.add_transaction(p1.position_id, "2026-02-01", "buy", 10.0, 1)
        store.add_transaction(p2.position_id, "2026-02-02", "buy", 5.0, 1)
        out = store.list_transactions(ticker="600595")
        assert len(out) == 1
        assert out[0].ticker == "600595"

    def test_list_transactions_filters_by_since(self, store):
        pos = self._add_position(store)
        store.add_transaction(pos.position_id, "2026-01-01", "buy", 10.0, 1)
        store.add_transaction(pos.position_id, "2026-06-01", "buy", 10.0, 1)
        out = store.list_transactions(since="2026-03-01")
        assert len(out) == 1
        assert out[0].date == "2026-06-01"

    def test_list_transactions_sorted_desc(self, store):
        pos = self._add_position(store)
        store.add_transaction(pos.position_id, "2026-01-01", "buy", 10.0, 1)
        store.add_transaction(pos.position_id, "2026-03-01", "buy", 10.0, 1)
        dates = [t.date for t in store.list_transactions()]
        assert dates == sorted(dates, reverse=True)


# ── AlertRule CRUD ──────────────────────────────────────────────────


class TestAlertCRUD:

    def test_add_alert_returns_rule(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        assert isinstance(rule, AlertRule)
        assert rule.ticker == "600595"
        assert rule.threshold == 12.0
        assert rule.enabled is True
        assert rule.trigger_count == 0

    def test_add_alert_normalizes_ticker(self, store):
        rule = store.add_alert(ticker="SH600595", rule_type="price_above", threshold=1.0)
        assert rule.ticker == "600595"

    def test_add_alert_validates_rule_type(self, store):
        with pytest.raises(ValueError, match="rule_type"):
            store.add_alert(ticker="600595", rule_type="unknown", threshold=1.0)

    def test_update_alert_changes_fields(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        updated = store.update_alert(rule.rule_id, threshold=15.0, enabled=False)
        assert updated.threshold == 15.0
        assert updated.enabled is False

    def test_update_alert_rejects_unknown_field(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        with pytest.raises(ValueError, match="unknown"):
            store.update_alert(rule.rule_id, bad_field=True)

    def test_update_alert_raises_for_missing_id(self, store):
        with pytest.raises(KeyError, match="not found"):
            store.update_alert("deadbeefdead", threshold=1.0)

    def test_delete_alert_removes(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        store.delete_alert(rule.rule_id)
        assert all(r.rule_id != rule.rule_id for r in store.list_alerts())

    def test_delete_alert_silent_noop_for_missing(self, store):
        store.delete_alert("missing_id")  # no raise

    def test_list_alerts_filters_by_ticker(self, store):
        store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        store.add_alert(ticker="000001", rule_type="price_below", threshold=5.0)
        out = store.list_alerts(ticker="600595")
        assert len(out) == 1 and out[0].ticker == "600595"

    def test_list_alerts_filters_enabled_only(self, store):
        store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0, enabled=True)
        store.add_alert(ticker="000001", rule_type="price_above", threshold=5.0, enabled=False)
        enabled = store.list_alerts(enabled_only=True)
        assert all(r.enabled for r in enabled)
        assert len(enabled) == 1

    def test_record_trigger_increments_count(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        store.record_trigger(rule.rule_id, 12.5)
        refreshed = store.list_alerts(ticker="600595")[0]
        assert refreshed.trigger_count == 1
        assert refreshed.last_triggered_price == 12.5
        assert refreshed.last_triggered_at is not None

    def test_record_trigger_multiple_times(self, store):
        rule = store.add_alert(ticker="600595", rule_type="price_above", threshold=12.0)
        store.record_trigger(rule.rule_id, 12.5)
        store.record_trigger(rule.rule_id, 13.0)
        refreshed = store.list_alerts(ticker="600595")[0]
        assert refreshed.trigger_count == 2
        assert refreshed.last_triggered_price == 13.0

    def test_record_trigger_raises_for_missing(self, store):
        with pytest.raises(KeyError, match="not found"):
            store.record_trigger("missing_id", 12.0)


# ── Persistence round-trip ──────────────────────────────────────────


class TestPersistence:

    def test_round_trip_positions(self, tmp_portfolio):
        s1 = PortfolioStore()
        pos = s1.add_position("600595", "中航电子", 10.0, 100, "2026-01-15")
        # Recreate singleton pointing at same dir → data must survive.
        s2 = PortfolioStore()
        got = s2.get_position(pos.position_id)
        assert got is not None
        assert got.ticker == "600595"
        assert got.cost_basis == 10.0
        assert got.quantity == 100

    def test_round_trip_transactions(self, tmp_portfolio):
        s1 = PortfolioStore()
        pos = s1.add_position("600595", "A", 10.0, 100, "2026-01-15")
        s1.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50)
        s2 = PortfolioStore()
        out = s2.list_transactions(ticker="600595")
        assert len(out) == 1
        assert out[0].price == 11.0
        assert out[0].quantity == 50

    def test_round_trip_alerts(self, tmp_portfolio):
        s1 = PortfolioStore()
        rule = s1.add_alert("600595", "price_above", 12.0)
        s2 = PortfolioStore()
        out = s2.list_alerts(ticker="600595")
        assert len(out) == 1
        assert out[0].rule_id == rule.rule_id
        assert out[0].threshold == 12.0

    def test_atomic_write_does_not_leave_tmp_file(self, store, tmp_portfolio):
        """After a write, no .tmp file should remain."""
        store.add_position("600595", "A", 10.0, 100, "2026-01-15")
        tmp_files = list(tmp_portfolio.glob("*.tmp"))
        assert tmp_files == []


# ── Thread safety ───────────────────────────────────────────────────


class TestThreadSafety:

    def test_concurrent_add_positions(self, store):
        """100 threads each add a position → 100 entries written cleanly."""

        def add_one(i: int) -> None:
            store.add_position(
                ticker=f"60059{i % 10}",
                name=f"P{i}",
                cost_basis=10.0,
                quantity=10,
                first_buy_date="2026-01-15",
            )

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(add_one, range(100)))
        assert len(store.list_positions()) == 100

    def test_concurrent_update_same_position(self, store):
        pos = store.add_position("600595", "A", 10.0, 100, "2026-01-15")

        def bump(i: int) -> None:
            store.update_position(pos.position_id, quantity=100 + i)

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(bump, range(50)))
        # Final quantity is one of the increments; no half-written state.
        final = store.get_position(pos.position_id)
        assert final.quantity in range(100, 150)


# ── Audit log ───────────────────────────────────────────────────────


class TestAuditLog:

    def test_add_position_writes_audit(self, store, tmp_portfolio):
        store.add_position("600595", "A", 10.0, 100, "2026-01-15")
        log = (tmp_portfolio / AUDIT_FILE).read_text(encoding="utf-8")
        assert "add_position" in log
        assert "600595" in log

    def test_add_transaction_writes_audit(self, store, tmp_portfolio):
        pos = store.add_position("600595", "A", 10.0, 100, "2026-01-15")
        store.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50)
        log = (tmp_portfolio / AUDIT_FILE).read_text(encoding="utf-8")
        assert "add_transaction" in log

    def test_add_alert_writes_audit(self, store, tmp_portfolio):
        store.add_alert("600595", "price_above", 12.0)
        log = (tmp_portfolio / AUDIT_FILE).read_text(encoding="utf-8")
        assert "add_alert" in log

    def test_record_trigger_writes_audit(self, store, tmp_portfolio):
        rule = store.add_alert("600595", "price_above", 12.0)
        store.record_trigger(rule.rule_id, 12.5)
        log = (tmp_portfolio / AUDIT_FILE).read_text(encoding="utf-8")
        assert "record_trigger" in log
        assert "count=1" in log

    def test_audit_includes_timestamp(self, store, tmp_portfolio):
        store.add_position("600595", "A", 10.0, 100, "2026-01-15")
        log = (tmp_portfolio / AUDIT_FILE).read_text(encoding="utf-8")
        # ISO-ish prefix like [2026-01-15T...]
        assert log.startswith("[20")


# ── Validators / dataclass round-trip ────────────────────────────────


class TestDataclassHelpers:

    def test_position_round_trip(self):
        p = Position(
            position_id="abc123", ticker="600595", name="X",
            cost_basis=10.0, quantity=100, first_buy_date="2026-01-15",
            last_trade_date="2026-02-01", account="main", asset_class="stock",
            notes="n", created_at=1.0,
        )
        d = p.to_dict()
        p2 = Position.from_dict(d)
        assert p2 == p

    def test_transaction_round_trip(self):
        t = Transaction(
            tx_id="tx1", position_id="p1", ticker="600595",
            date="2026-02-01", action="buy", price=11.0,
            quantity=50, fees=5.0, notes="ok", created_at=2.0,
        )
        d = t.to_dict()
        t2 = Transaction.from_dict(d)
        assert t2 == t

    def test_alert_round_trip_with_none_last_triggered(self):
        a = AlertRule(rule_id="r1", ticker="600595", rule_type="price_above", threshold=12.0)
        d = a.to_dict()
        assert d["last_triggered_at"] is None
        assert d["last_triggered_price"] is None
        a2 = AlertRule.from_dict(d)
        assert a2 == a

    def test_constants_present(self):
        """All exported validators are non-empty tuples."""
        assert "buy" in VALID_TRANSACTION_ACTIONS
        assert "price_above" in VALID_ALERT_RULE_TYPES
        assert "stock" in VALID_ASSET_CLASSES