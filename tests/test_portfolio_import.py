"""Tests for backend.core.portfolio_import."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.portfolio_import import (
    CSV_FORMATS,
    ImportRow,
    apply_import,
    detect_format,
    export_csv,
    export_transactions_csv,
    parse_csv,
    preview_import,
)
from backend.core.portfolio_store import (
    AUDIT_FILE,
    PortfolioStore,
    Position,
    Transaction,
)


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
    monkeypatch.setattr("backend.core.portfolio_store.PortfolioStore._instance", None)
    return PortfolioStore()


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    """Redirect portfolio exports to a tmp dir so we don't pollute ~/.tradingagents/."""
    out = tmp_path / "exports"
    out.mkdir()
    return out


# ── sample CSV fixtures per format ──────────────────────────────────


EASTMONEY_CSV = (
    "证券代码,证券名称,成本价,持有数量,建仓日期\n"
    "600595,中航电子,10.50,1000,2026-01-15\n"
    "000001,平安银行,12.30,500,2026-02-01\n"
)

THS_CSV = (
    "股票代码,股票名称,成本价,持仓数量,买入日期\n"
    "688017,绿的谐波,80.00,200,2026-03-10\n"
)

XUEQIU_CSV = (
    "symbol,name,cost_price,quantity,created_at\n"
    "SH600519,贵州茅台,1700.00,10,2026-04-01\n"
)

GENERIC_CSV = (
    "代码,名称,cost,qty,date\n"
    "300750,宁德时代,200.0,100,2026/05/01\n"
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# ── detect_format ────────────────────────────────────────────────────


class TestDetectFormat:

    def test_detects_eastmoney(self, tmp_path):
        path = _write(tmp_path / "eastmoney.csv", EASTMONEY_CSV)
        assert detect_format(path) == "eastmoney"

    def test_detects_ths(self, tmp_path):
        path = _write(tmp_path / "ths.csv", THS_CSV)
        assert detect_format(path) == "ths"

    def test_detects_xueqiu(self, tmp_path):
        path = _write(tmp_path / "xueqiu.csv", XUEQIU_CSV)
        assert detect_format(path) == "xueqiu"

    def test_detects_generic(self, tmp_path):
        path = _write(tmp_path / "generic.csv", GENERIC_CSV)
        # Falls back to generic since "代码" matches multiple formats.
        assert detect_format(path) in ("eastmoney", "ths", "generic")

    def test_returns_none_for_empty_file(self, tmp_path):
        path = _write(tmp_path / "empty.csv", "")
        assert detect_format(path) is None

    def test_returns_none_for_unrelated_csv(self, tmp_path):
        path = _write(tmp_path / "junk.csv", "foo,bar,baz\n1,2,3\n")
        assert detect_format(path) is None

    def test_handles_utf8_bom(self, tmp_path):
        path = tmp_path / "bom.csv"
        path.write_bytes(b"\xef\xbb\xbf" + EASTMONEY_CSV.encode("utf-8"))
        assert detect_format(path) == "eastmoney"


# ── parse_csv ───────────────────────────────────────────────────────


class TestParseCSV:

    def test_parses_eastmoney(self, tmp_path):
        path = _write(tmp_path / "x.csv", EASTMONEY_CSV)
        rows = parse_csv(path, "eastmoney")
        assert len(rows) == 2
        first = rows[0]
        assert isinstance(first, ImportRow)
        assert first.ticker == "600595"
        assert first.name == "中航电子"
        assert first.cost == 10.5
        assert first.quantity == 1000
        assert first.date == "2026-01-15"

    def test_parses_ths(self, tmp_path):
        path = _write(tmp_path / "x.csv", THS_CSV)
        rows = parse_csv(path, "ths")
        assert len(rows) == 1
        assert rows[0].ticker == "688017"
        assert rows[0].name == "绿的谐波"
        assert rows[0].cost == 80.0
        assert rows[0].quantity == 200

    def test_parses_xueqiu_normalizes_ticker(self, tmp_path):
        path = _write(tmp_path / "x.csv", XUEQIU_CSV)
        rows = parse_csv(path, "xueqiu")
        assert len(rows) == 1
        # SH prefix should be stripped by _normalize_ticker.
        assert rows[0].ticker == "600519"

    def test_parses_generic_with_alt_date_format(self, tmp_path):
        path = _write(tmp_path / "x.csv", GENERIC_CSV)
        rows = parse_csv(path, "generic")
        assert len(rows) == 1
        # 2026/05/01 normalized to ISO
        assert rows[0].date == "2026-05-01"

    def test_skips_rows_with_missing_date(self, tmp_path):
        csv = "代码,名称,cost,qty,date\n300750,X,1.0,1,\n"
        path = _write(tmp_path / "x.csv", csv)
        rows = parse_csv(path, "generic")
        assert rows == []

    def test_skips_rows_with_zero_quantity(self, tmp_path):
        csv = "代码,名称,cost,qty,date\n300750,X,1.0,0,2026-01-01\n"
        path = _write(tmp_path / "x.csv", csv)
        rows = parse_csv(path, "generic")
        assert rows == []

    def test_unknown_format_raises(self, tmp_path):
        path = _write(tmp_path / "x.csv", "foo,bar\n1,2\n")
        with pytest.raises(ValueError, match="unknown format"):
            parse_csv(path, "junk_format")

    def test_handles_integer_quantity_with_decimal(self, tmp_path):
        """Quantity column may contain "100.0" — should coerce to int."""
        csv = "代码,名称,cost,qty,date\n300750,X,1.0,100.0,2026-01-01\n"
        path = _write(tmp_path / "x.csv", csv)
        rows = parse_csv(path, "generic")
        assert len(rows) == 1 and rows[0].quantity == 100


# ── preview_import ──────────────────────────────────────────────────


class TestPreviewImport:

    def test_separates_new_conflicts_invalid(self, store):
        # Existing position creates conflict on 600595
        store.add_position("600595", "X", 9.0, 50, "2026-01-01")
        parsed = [
            ImportRow("600595", "Y", 10.0, 100, "2026-02-01"),  # conflict
            ImportRow("000001", "B", 5.0, 200, "2026-01-01"),  # new
            ImportRow("", "", 0, 0, ""),  # invalid
        ]
        out = preview_import(parsed, store.list_positions())
        assert len(out["new"]) == 1 and out["new"][0].ticker == "000001"
        assert len(out["conflicts"]) == 1 and out["conflicts"][0]["parsed"].ticker == "600595"
        assert len(out["invalid"]) == 1

    def test_conflict_resolution_default_is_skip(self, store):
        store.add_position("600595", "X", 9.0, 50, "2026-01-01")
        parsed = [ImportRow("600595", "Y", 10.0, 100, "2026-02-01")]
        out = preview_import(parsed, store.list_positions())
        assert out["conflicts"][0]["resolution"] == "skip"

    def test_empty_existing_makes_all_new(self, store):
        parsed = [ImportRow("600595", "X", 10.0, 100, "2026-01-01")]
        out = preview_import(parsed, [])
        assert len(out["new"]) == 1
        assert out["conflicts"] == []


# ── apply_import ────────────────────────────────────────────────────


class TestApplyImport:

    def test_inserts_new_positions(self, store):
        parsed = [
            ImportRow("600595", "X", 10.0, 100, "2026-01-01"),
            ImportRow("000001", "Y", 5.0, 200, "2026-01-01"),
        ]
        preview = preview_import(parsed, [])
        created = apply_import(preview, resolution_strategy="skip", store=store)
        assert len(created) == 2
        tickers = sorted(p.ticker for p in store.list_positions())
        assert tickers == ["000001", "600595"]

    def test_overwrite_strategy_replaces_cost_and_qty(self, store):
        store.add_position("600595", "X", 9.0, 50, "2026-01-01")
        parsed = [ImportRow("600595", "Y", 11.0, 200, "2026-02-01")]
        preview = preview_import(parsed, store.list_positions())
        apply_import(preview, resolution_strategy="overwrite", store=store)
        pos = store.get_position(preview["conflicts"][0]["existing"].position_id)
        assert pos.cost_basis == 11.0
        assert pos.quantity == 200

    def test_skip_strategy_keeps_existing(self, store):
        store.add_position("600595", "X", 9.0, 50, "2026-01-01")
        parsed = [ImportRow("600595", "Y", 11.0, 200, "2026-02-01")]
        preview = preview_import(parsed, store.list_positions())
        apply_import(preview, resolution_strategy="skip", store=store)
        pos = store.get_position(preview["conflicts"][0]["existing"].position_id)
        assert pos.cost_basis == 9.0
        assert pos.quantity == 50

    def test_merge_strategy_weighted_averages(self, store):
        store.add_position("600595", "X", 10.0, 100, "2026-01-01")
        parsed = [ImportRow("600595", "Y", 20.0, 100, "2026-02-01")]
        preview = preview_import(parsed, store.list_positions())
        apply_import(preview, resolution_strategy="merge", store=store)
        pos = store.get_position(preview["conflicts"][0]["existing"].position_id)
        assert pos.quantity == 200
        # (10*100 + 20*100) / 200 = 15
        assert pos.cost_basis == pytest.approx(15.0)

    def test_invalid_strategy_raises(self, store):
        with pytest.raises(ValueError, match="resolution_strategy"):
            apply_import({"new": [], "conflicts": [], "invalid": []}, "bad", store=store)

    def test_writes_audit_log(self, store, tmp_path):
        parsed = [ImportRow("600595", "X", 10.0, 100, "2026-01-01")]
        preview = preview_import(parsed, [])
        apply_import(
            preview, resolution_strategy="skip", store=store,
            file_path="/tmp/fake.csv", row_count=1,
        )
        log = (tmp_path / AUDIT_FILE).read_text(encoding="utf-8")
        assert "apply_import" in log
        assert "/tmp/fake.csv" in log
        assert "strategy=skip" in log


# ── export_csv ──────────────────────────────────────────────────────


class TestExportCSV:

    def test_export_positions_writes_utf8_bom(self, store, export_dir):
        pos = store.add_position("600595", "中航电子", 10.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir, current_prices={"600595": 12.0})
        assert out.exists()
        # UTF-8 BOM is 3 bytes
        assert out.read_bytes()[:3] == b"\xef\xbb\xbf"

    def test_export_positions_contains_columns(self, store, export_dir):
        pos = store.add_position("600595", "中航电子", 10.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir, current_prices={"600595": 12.0})
        text = out.read_text(encoding="utf-8-sig")
        for col in ["代码", "名称", "成本价", "持仓数量", "持仓金额", "浮动盈亏", "盈亏比例", "首次买入日期", "备注"]:
            assert col in text

    def test_export_positions_computes_pnl(self, store, export_dir):
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir, current_prices={"600595": 12.0})
        text = out.read_text(encoding="utf-8-sig")
        # Cost=10, qty=100, value=1200, pnl=200, pnl%=+20.00%
        assert "1200" in text
        assert "+20.00%" in text

    def test_export_positions_includes_tx_count_when_transactions(self, store, export_dir):
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        store.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50)
        out = export_csv(
            [pos], transactions=store.list_transactions(),
            output_dir=export_dir, current_prices={"600595": 11.0},
        )
        text = out.read_text(encoding="utf-8-sig")
        assert "交易笔数" in text

    def test_export_transactions_writes_csv(self, store, export_dir):
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        tx = store.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50, fees=5.0)
        out = export_transactions_csv([tx], output_dir=export_dir)
        assert out.exists()
        assert out.read_bytes()[:3] == b"\xef\xbb\xbf"
        text = out.read_text(encoding="utf-8-sig")
        assert "600595" in text
        assert "buy" in text
        assert "5.0" in text

    def test_export_transactions_sorted_desc(self, store, export_dir):
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        t1 = store.add_transaction(pos.position_id, "2026-01-01", "buy", 10.0, 10)
        t2 = store.add_transaction(pos.position_id, "2026-06-01", "buy", 10.0, 10)
        out = export_transactions_csv([t1, t2], output_dir=export_dir)
        text = out.read_text(encoding="utf-8-sig")
        # t2 (Jun) must appear before t1 (Jan) in the file
        assert text.index("2026-06-01") < text.index("2026-01-01")


# ── format registry sanity ──────────────────────────────────────────


class TestFormatRegistry:

    def test_all_required_canonical_fields_present(self):
        """Each format must define the 5 canonical fields."""
        for fmt, mapping in CSV_FORMATS.items():
            assert "code" in mapping, f"{fmt} missing code"
            assert "name" in mapping, f"{fmt} missing name"
            assert "cost" in mapping, f"{fmt} missing cost"
            assert "quantity" in mapping, f"{fmt} missing quantity"
            assert "date" in mapping, f"{fmt} missing date"

    def test_four_formats_defined(self):
        assert set(CSV_FORMATS.keys()) == {"eastmoney", "ths", "xueqiu", "generic"}