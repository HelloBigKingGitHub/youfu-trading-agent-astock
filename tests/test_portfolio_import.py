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


# ── Spec 3.4: detect_format edge cases ─────────────────────────────


class TestDetectFormatEdgeCases:

    def test_returns_none_when_fewer_than_three_matches(self, tmp_path):
        """Score threshold is 0.6; only one alias match scores 1/5 → None."""
        # "代码" matches code alias in three formats but no other field.
        csv = "代码,foo,bar,baz\n600595,X,10,100,2026-01-01\n"
        path = _write(tmp_path / "sparse.csv", csv)
        assert detect_format(path) is None

    def test_score_at_threshold_accepted(self, tmp_path):
        """3/5 canonical fields matched (>= 0.6) should resolve to a format."""
        # 证券代码 + 证券名称 + 建仓日期 → matches eastmoney: code, name, date (3/5).
        csv = "证券代码,证券名称,foo,bar,建仓日期\n600595,X,Y,Z,2026-01-01\n"
        path = _write(tmp_path / "partial.csv", csv)
        assert detect_format(path) == "eastmoney"

    def test_header_with_only_blank_lines_returns_none(self, tmp_path):
        csv = "\n\n\n"
        path = _write(tmp_path / "blank.csv", csv)
        assert detect_format(path) is None


# ── Spec 3.4: parse_csv edge cases ──────────────────────────────────


class TestParseCSVEdgeCases:

    def test_missing_code_column_returns_empty(self, tmp_path):
        """If header has no alias matching the format's code field, parse_csv
        silently returns [] (cannot map required field)."""
        csv = "foo,bar,baz\n1,2,3\n"
        path = _write(tmp_path / "no_code.csv", csv)
        rows = parse_csv(path, "eastmoney")
        assert rows == []

    def test_drops_rows_with_negative_cost(self, tmp_path):
        csv = "代码,名称,cost,qty,date\n300750,X,-1.0,100,2026-01-01\n"
        path = _write(tmp_path / "neg.csv", csv)
        rows = parse_csv(path, "generic")
        assert rows == []

    def test_drops_rows_with_unparseable_date(self, tmp_path):
        csv = "代码,名称,cost,qty,date\n300750,X,1.0,100,not-a-date\n"
        path = _write(tmp_path / "bad_date.csv", csv)
        rows = parse_csv(path, "generic")
        assert rows == []

    def test_empty_data_rows_returns_empty_list(self, tmp_path):
        csv = "代码,名称,cost,qty,date\n"
        path = _write(tmp_path / "no_rows.csv", csv)
        rows = parse_csv(path, "generic")
        assert rows == []


# ── Spec 3.4: preview_import bucketing ──────────────────────────────


class TestPreviewImportBucketing:

    def test_empty_parsed_returns_all_empty_buckets(self, store):
        out = preview_import([], store.list_positions())
        assert out == {"new": [], "conflicts": [], "invalid": []}

    def test_zero_cost_goes_to_invalid_bucket(self, store):
        parsed = [ImportRow("600595", "X", 0.0, 100, "2026-01-01")]
        out = preview_import(parsed, [])
        assert out["new"] == []
        assert out["conflicts"] == []
        assert len(out["invalid"]) == 1
        assert out["invalid"][0]["row"].ticker == "600595"

    def test_zero_quantity_goes_to_invalid_bucket(self, store):
        parsed = [ImportRow("600595", "X", 10.0, 0, "2026-01-01")]
        out = preview_import(parsed, [])
        assert out["new"] == []
        assert out["conflicts"] == []
        assert len(out["invalid"]) == 1

    def test_missing_ticker_goes_to_invalid_bucket(self, store):
        parsed = [ImportRow("", "X", 10.0, 100, "2026-01-01")]
        out = preview_import(parsed, [])
        assert len(out["invalid"]) == 1


# ── Spec 3.4: apply_import date merge logic ─────────────────────────


class TestApplyImportDates:

    def test_overwrite_advances_last_trade_date_to_max(self, store):
        """Overwrite strategy picks max(existing.last_trade_date, parsed.date)."""
        # Existing position: last_trade_date = 2026-03-01 (set by store on creation).
        store.add_position("600595", "X", 10.0, 100, "2026-01-01")
        # Manually push last_trade_date forward via update.
        pos = store.list_positions()[0]
        store.update_position(pos.position_id, last_trade_date="2026-03-01")
        # Import with an even later date → overwrite should take max.
        parsed = [ImportRow("600595", "Y", 12.0, 200, "2026-06-01")]
        preview = preview_import(parsed, store.list_positions())
        apply_import(preview, resolution_strategy="overwrite", store=store)
        pos_after = store.get_position(pos.position_id)
        assert pos_after.last_trade_date == "2026-06-01"
        assert pos_after.cost_basis == 12.0
        assert pos_after.quantity == 200

    def test_overwrite_keeps_earlier_last_trade_date(self, store):
        """When parsed.date < existing.last_trade_date, overwrite keeps the later."""
        store.add_position("600595", "X", 10.0, 100, "2026-06-01")
        pos = store.list_positions()[0]
        # existing.last_trade_date is 2026-06-01 (from creation)
        parsed = [ImportRow("600595", "Y", 12.0, 200, "2026-01-01")]
        preview = preview_import(parsed, store.list_positions())
        apply_import(preview, resolution_strategy="overwrite", store=store)
        pos_after = store.get_position(pos.position_id)
        assert pos_after.last_trade_date == "2026-06-01"

    def test_apply_with_empty_preview_still_audits(self, store):
        """Even when nothing is applied, apply_import writes an audit line."""
        apply_import(
            {"new": [], "conflicts": [], "invalid": []},
            resolution_strategy="skip",
            store=store,
            file_path="/tmp/empty.csv",
        )
        log = store._path("audit.log").read_text(encoding="utf-8")
        assert "apply_import" in log
        assert "/tmp/empty.csv" in log
        assert "applied=0" in log


# ── Spec 3.4: export_csv computed columns ───────────────────────────


class TestExportCSVEdgeCases:

    def test_zero_cost_basis_yields_zero_pnl_pct(self, store, export_dir):
        """cost_basis == 0 → pnl_pct is 0.0% (avoid ZeroDivisionError)."""
        # add_position allows quantity >= 0; cost_basis can be 0.
        pos = store.add_position("600595", "X", 0.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir, current_prices={"600595": 5.0})
        text = out.read_text(encoding="utf-8-sig")
        # 0% pnl formatted as +0.00%
        assert "+0.00%" in text

    def test_missing_price_falls_back_to_cost_basis(self, store, export_dir):
        """When ticker absent from current_prices, price defaults to cost_basis."""
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        # No current_prices dict at all.
        out = export_csv([pos], output_dir=export_dir)
        text = out.read_text(encoding="utf-8-sig")
        # cost_basis → price, so pnl = 0 and pnl% = +0.00%
        assert "+0.00%" in text

    def test_output_filename_has_timestamp(self, store, export_dir):
        """Export file name contains YYYYMMDD_HHMMSS timestamp."""
        import re

        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir)
        assert re.search(r"positions_\d{8}_\d{6}\.csv$", out.name)

    def test_export_with_no_transactions_omits_tx_count_column(
        self, store, export_dir
    ):
        pos = store.add_position("600595", "X", 10.0, 100, "2026-01-15")
        out = export_csv([pos], output_dir=export_dir)
        text = out.read_text(encoding="utf-8-sig")
        assert "交易笔数" not in text