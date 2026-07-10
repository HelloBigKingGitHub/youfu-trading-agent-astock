"""Tests for backend.core.portfolio_import (v0.5.0 MVP).

覆盖 4 种 CSV 格式（东财/同花顺/雪球/generic） + 解析/预览/导入/导出全流程。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.core.portfolio_import import (
    CSV_FORMATS,
    _normalize_date,
    _read_header,
    _resolve_columns,
    apply_import,
    detect_format,
    export_csv,
    export_transactions_csv,
    parse_csv,
    preview_import,
)
from backend.core.portfolio_store import (
    AUDIT_FILE,
    Account,
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
def tmp_csv(tmp_path):
    """提供 tmp_path + 一个 helper 来写 CSV。"""
    def _write(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path
    return _write


# ── 4 种格式的样本 CSV ────────────────────────────────────────────


EASTMONEY_CSV = (
    "证券代码,证券名称,成本价,持有数量,建仓日期\n"
    "600595,中航电子,10.50,1000,2026-01-15\n"
    "000001,平安银行,5.20,2000,2026-02-01\n"
)

THS_CSV = (
    "股票代码,股票名称,成本价,持仓数量,买入日期\n"
    "600519,贵州茅台,1800.00,100,2026-03-01\n"
)

XUEQIU_CSV = (
    "symbol,name,cost_price,quantity,created_at\n"
    "PDD,拼多多,80.00,50,2026-04-01\n"
)

GENERIC_CSV = (
    "ticker,name,cost,quantity,date\n"
    "AAPL,苹果,150.00,10,2026-05-01\n"
)


# ── 1. _normalize_date ──────────────────────────────────────────────


class TestNormalizeDate:
    """日期格式归一化（→ ISO 'YYYY-MM-DD'）。"""

    def test_slash_to_dash(self):
        assert _normalize_date("2026/01/15") == "2026-01-15"

    def test_dot_to_dash(self):
        assert _normalize_date("2026.01.15") == "2026-01-15"

    def test_passthrough_iso(self):
        assert _normalize_date("2026-01-15") == "2026-01-15"

    def test_chinese_to_iso(self):
        assert _normalize_date("2026年01月15日") == "2026-01-15"

    def test_empty_returns_empty(self):
        assert _normalize_date("") == ""

    def test_8digit_compact_to_iso(self):
        assert _normalize_date("20260115") == "2026-01-15"

    def test_chinese_zero_padding(self):
        """1月2日 → 01-02."""
        assert _normalize_date("2026年1月2日") == "2026-01-02"

    def test_unknown_format_passthrough(self):
        """无法识别的格式原样返回。"""
        assert _normalize_date("Jan 15, 2026") == "Jan 15, 2026"


# ── 2. _resolve_columns ─────────────────────────────────────────────


class TestResolveColumns:
    """把 mapping 中的 canonical → CSV 实际列名。"""

    def test_exact_string_match(self):
        """精确字符串 mapping → 直接命中。"""
        mapping = {"code": "证券代码", "name": "证券名称"}
        resolved = _resolve_columns(mapping, ["证券代码", "证券名称"])
        assert resolved == {"code": "证券代码", "name": "证券名称"}

    def test_list_candidates_first_match_wins(self):
        """list 候选 → 按顺序找第一个在 header 里的。"""
        mapping = {"code": ["ticker", "代码", "code"]}
        resolved = _resolve_columns(mapping, ["代码", "ticker"])
        # "ticker" 在 mapping 里是第一个候选，且在 header 里
        assert resolved == {"code": "ticker"}

    def test_missing_fields_omitted(self):
        """header 里没有的字段不出现在 resolved 里。"""
        mapping = {"code": "证券代码", "name": "证券名称"}
        resolved = _resolve_columns(mapping, ["证券代码"])
        assert resolved == {"code": "证券代码"}
        assert "name" not in resolved


# ── 3. detect_format ───────────────────────────────────────────────


class TestDetectFormat:
    """格式自动识别。"""

    def test_detect_eastmoney(self, tmp_csv):
        path = tmp_csv("eastmoney.csv", EASTMONEY_CSV)
        assert detect_format(path) == "eastmoney"

    def test_detect_ths(self, tmp_csv):
        path = tmp_csv("ths.csv", THS_CSV)
        assert detect_format(path) == "ths"

    def test_detect_xueqiu(self, tmp_csv):
        path = tmp_csv("xueqiu.csv", XUEQIU_CSV)
        assert detect_format(path) == "xueqiu"

    def test_detect_generic(self, tmp_csv):
        path = tmp_csv("generic.csv", GENERIC_CSV)
        assert detect_format(path) == "generic"

    def test_low_confidence_returns_none(self, tmp_csv):
        """header 只有 2 个匹配 → < 3 → None."""
        path = tmp_csv("low.csv", "ticker,name\nA,B\n")
        assert detect_format(path) is None

    def test_empty_file_returns_none(self, tmp_csv):
        path = tmp_csv("empty.csv", "")
        assert detect_format(path) is None

    def test_returns_one_of_known_formats(self, tmp_csv):
        """detect_format 返回值必须是 CSV_FORMATS 的 key 或 None。"""
        path = tmp_csv("em.csv", EASTMONEY_CSV)
        result = detect_format(path)
        assert result in list(CSV_FORMATS.keys())


# ── 4. parse_csv ───────────────────────────────────────────────────


class TestParseCsv:
    """4 种格式的 CSV 解析。"""

    def test_eastmoney_parse(self, tmp_csv):
        path = tmp_csv("em.csv", EASTMONEY_CSV)
        rows = parse_csv(path, "eastmoney")
        assert len(rows) == 2
        assert rows[0]["ticker"] == "600595"
        assert rows[0]["name"] == "中航电子"
        assert rows[0]["cost"] == 10.5
        assert rows[0]["quantity"] == 1000
        assert rows[0]["date"] == "2026-01-15"

    def test_ths_parse(self, tmp_csv):
        path = tmp_csv("ths.csv", THS_CSV)
        rows = parse_csv(path, "ths")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "600519"
        assert rows[0]["name"] == "贵州茅台"
        assert rows[0]["cost"] == 1800.0

    def test_xueqiu_parse(self, tmp_csv):
        path = tmp_csv("xq.csv", XUEQIU_CSV)
        rows = parse_csv(path, "xueqiu")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "PDD"
        assert rows[0]["name"] == "拼多多"
        assert rows[0]["cost"] == 80.0

    def test_generic_parse(self, tmp_csv):
        path = tmp_csv("gen.csv", GENERIC_CSV)
        rows = parse_csv(path, "generic")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["name"] == "苹果"

    def test_skip_negative_cost(self, tmp_csv):
        """cost<0 的行被跳过。"""
        csv = "证券代码,证券名称,成本价,持有数量,建仓日期\n600595,X,-10,100,2026-01-01\n000001,Y,5,100,2026-01-01\n"
        path = tmp_csv("neg.csv", csv)
        rows = parse_csv(path, "eastmoney")
        # 只剩 000001
        assert len(rows) == 1
        assert rows[0]["ticker"] == "000001"

    def test_skip_zero_quantity(self, tmp_csv):
        """quantity<=0 的行被跳过。"""
        csv = "证券代码,证券名称,成本价,持有数量,建仓日期\n600595,X,10,0,2026-01-01\n000001,Y,5,100,2026-01-01\n"
        path = tmp_csv("zero.csv", csv)
        rows = parse_csv(path, "eastmoney")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "000001"

    def test_skip_blank_rows(self, tmp_csv):
        """空白行被跳过。"""
        csv = "证券代码,证券名称,成本价,持有数量,建仓日期\n600595,X,10,100,2026-01-01\n\n000001,Y,5,100,2026-01-01\n"
        path = tmp_csv("blank.csv", csv)
        rows = parse_csv(path, "eastmoney")
        assert len(rows) == 2

    def test_invalid_format_raises(self, tmp_csv):
        """未知 format 抛 ValueError。"""
        path = tmp_csv("x.csv", EASTMONEY_CSV)
        with pytest.raises(ValueError, match="unknown format"):
            parse_csv(path, "nonexistent_format")

    def test_chinese_date_normalized(self, tmp_csv):
        """中文日期 '2026年01月15日' 被 _normalize_date 转 ISO."""
        csv = "证券代码,证券名称,成本价,持有数量,建仓日期\n600595,X,10,100,2026年01月15日\n"
        path = tmp_csv("chinese.csv", csv)
        rows = parse_csv(path, "eastmoney")
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-01-15"

    def test_returns_standard_format(self, tmp_csv):
        """所有 format 解析输出统一为 dict 5 个键。"""
        for fmt, csv in [
            ("eastmoney", EASTMONEY_CSV),
            ("ths", THS_CSV),
            ("xueqiu", XUEQIU_CSV),
            ("generic", GENERIC_CSV),
        ]:
            path = tmp_csv(f"{fmt}.csv", csv)
            rows = parse_csv(path, fmt)
            assert len(rows) >= 1
            for r in rows:
                assert set(r.keys()) == {"ticker", "name", "cost", "quantity", "date"}


# ── 5. preview_import ──────────────────────────────────────────────


class TestPreviewImport:
    """parsed 分类成 new / conflicts / invalid。"""

    def _pos(self, ticker: str) -> Position:
        return Position(
            position_id=f"id_{ticker}",
            ticker=ticker,
            name=f"existing-{ticker}",
            cost_basis=10.0,
            quantity=100,
            first_buy_date="2026-01-01",
            last_trade_date="2026-01-01",
            asset_class="stock",
            account="default",
        )

    def test_new_position(self):
        """parsed 项在 existing 中不存在 → new."""
        parsed = [{"ticker": "600595", "name": "X", "cost": 10.0, "quantity": 100, "date": "2026-01-01"}]
        preview = preview_import(parsed, [])
        assert len(preview["new"]) == 1
        assert preview["new"][0]["ticker"] == "600595"
        assert preview["conflicts"] == []
        assert preview["invalid"] == []

    def test_conflict_detected(self):
        """parsed 项 ticker 命中 existing → conflict。"""
        parsed = [{"ticker": "600595", "name": "X", "cost": 10.0, "quantity": 100, "date": "2026-01-01"}]
        existing = [self._pos("600595")]
        preview = preview_import(parsed, existing)
        assert preview["new"] == []
        assert len(preview["conflicts"]) == 1
        assert preview["conflicts"][0]["ticker"] == "600595"
        assert preview["conflicts"][0]["existing"] is existing[0]

    def test_invalid_row_in_preview(self):
        """cost<0 / qty<=0 / ticker 空 → invalid。"""
        parsed = [
            {"ticker": "", "name": "X", "cost": 10.0, "quantity": 100, "date": "2026-01-01"},
            {"ticker": "600595", "name": "X", "cost": -1.0, "quantity": 100, "date": "2026-01-01"},
            {"ticker": "000001", "name": "X", "cost": 10.0, "quantity": 0, "date": "2026-01-01"},
            {"ticker": "300001", "name": "X", "cost": 10.0, "quantity": 100, "date": "2026-01-01"},
        ]
        preview = preview_import(parsed, [])
        assert len(preview["new"]) == 1  # 300001
        assert len(preview["invalid"]) == 3  # 前 3 个


# ── 6. apply_import ────────────────────────────────────────────────


class TestApplyImport:
    """把 preview 应用到 store（overwrite / skip / merge）。"""

    def test_overwrite_deletes_existing(self, store):
        """overwrite 策略：先 delete existing 再 add parsed."""
        # 现有持仓 600595
        existing = store.add_position("600595", "old", 10.0, 100, "2026-01-01")
        # 解析一条同名
        preview = {
            "new": [],
            "conflicts": [{
                "parsed": {
                    "ticker": "600595", "name": "new",
                    "cost": 20.0, "quantity": 50, "date": "2026-03-01",
                },
                "existing": existing,
                "ticker": "600595",
            }],
            "invalid": [],
        }
        added = apply_import(store, preview, "overwrite")
        assert len(added) == 1
        assert added[0].ticker == "600595"
        assert added[0].cost_basis == 20.0
        # 验证 store 里只剩 1 条 600595（不是 2 条）
        all_600595 = store.list_positions(account="default")
        assert len([p for p in all_600595 if p.ticker == "600595"]) == 1

    def test_skip_keeps_existing(self, store):
        """skip 策略：conflicts 全部跳过，new 全部 add."""
        existing = store.add_position("600595", "old", 10.0, 100, "2026-01-01")
        preview = {
            "new": [{
                "ticker": "000001", "name": "new",
                "cost": 5.0, "quantity": 200, "date": "2026-03-01",
            }],
            "conflicts": [{
                "parsed": {
                    "ticker": "600595", "name": "X",
                    "cost": 99.0, "quantity": 99, "date": "2026-03-01",
                },
                "existing": existing,
                "ticker": "600595",
            }],
            "invalid": [],
        }
        added = apply_import(store, preview, "skip")
        assert len(added) == 1
        assert added[0].ticker == "000001"
        # 600595 仍是旧的 cost=10
        old = store.get_position(existing.position_id)
        assert old.cost_basis == 10.0

    def test_merge_raises_not_implemented(self, store):
        """merge 策略在 MVP 抛 NotImplementedError。"""
        preview = {"new": [], "conflicts": [], "invalid": []}
        with pytest.raises(NotImplementedError, match="merge"):
            apply_import(store, preview, "merge")

    def test_invalid_strategy_raises(self, store):
        """未知 strategy 抛 ValueError。"""
        preview = {"new": [], "conflicts": [], "invalid": []}
        with pytest.raises(ValueError, match="resolution_strategy"):
            apply_import(store, preview, "bogus_strategy")

    def test_audit_recorded(self, store, tmp_path):
        """apply_import 写一条 audit log。"""
        store.add_position("600595", "old", 10.0, 100, "2026-01-01")
        # 找 audit.log 实际位置
        from backend.core.portfolio_store import AUDIT_FILE, PORTFOLIO_DIR
        preview = {
            "new": [{
                "ticker": "000001", "name": "new",
                "cost": 5.0, "quantity": 200, "date": "2026-03-01",
            }],
            "conflicts": [],
            "invalid": [],
        }
        apply_import(store, preview, "skip")
        audit_path = PORTFOLIO_DIR / AUDIT_FILE
        assert audit_path.exists()
        log = audit_path.read_text(encoding="utf-8")
        assert "apply_import" in log


# ── 7. export_csv ──────────────────────────────────────────────────


class TestExportCsv:
    """导出持仓到 CSV（UTF-8 BOM）。"""

    def _pos(self, ticker: str, cost=10.0, qty=100) -> Position:
        return Position(
            position_id=f"id_{ticker}",
            ticker=ticker,
            name=f"名称-{ticker}",
            cost_basis=cost,
            quantity=qty,
            first_buy_date="2026-01-01",
            last_trade_date="2026-01-01",
            asset_class="stock",
            account="default",
        )

    def test_export_creates_file(self):
        """export_csv 返回 Path 且文件存在。"""
        positions = [self._pos("600595")]
        path = export_csv(positions)
        assert path.exists()
        # 清理
        path.unlink(missing_ok=True)

    def test_export_has_utf8_bom(self):
        """文件前 3 字节是 UTF-8 BOM（EF BB BF）。"""
        positions = [self._pos("600595")]
        path = export_csv(positions)
        raw = path.read_bytes()[:3]
        assert raw == b"\xef\xbb\xbf"
        path.unlink(missing_ok=True)

    def test_export_columns(self):
        """列名符合 spec。"""
        positions = [self._pos("600595", cost=10.5, qty=100)]
        path = export_csv(positions)
        text = path.read_text(encoding="utf-8-sig")
        # 第一行 header
        assert "代码" in text
        assert "名称" in text
        assert "成本价" in text
        assert "持仓数量" in text
        assert "账户" in text
        # 数据行
        assert "600595" in text
        assert "10.5" in text
        path.unlink(missing_ok=True)

    def test_export_transactions_creates_file(self):
        """export_transactions_csv 写到 /tmp。"""
        tx = Transaction(
            tx_id="t1", position_id="p1", ticker="600595",
            date="2026-01-01", action="buy", price=10.0,
            quantity=100, fees=5.0, notes="测试",
        )
        path = export_transactions_csv([tx])
        assert path.exists()
        assert "transactions_export" in path.name
        text = path.read_text(encoding="utf-8-sig")
        assert "代码" in text
        assert "动作" in text
        assert "手续费" in text
        path.unlink(missing_ok=True)

    def test_export_empty_positions(self):
        """空持仓 → 只有 header。"""
        path = export_csv([])
        text = path.read_text(encoding="utf-8-sig")
        # 至少有 header 一行
        assert "代码" in text
        path.unlink(missing_ok=True)


# ── 8. _read_header ─────────────────────────────────────────────────


class TestReadHeader:
    """辅助函数：读 CSV 第一行。"""

    def test_reads_first_line_as_header(self, tmp_csv):
        path = tmp_csv("h.csv", "a,b,c\n1,2,3\n")
        assert _read_header(path) == ["a", "b", "c"]

    def test_strips_whitespace(self, tmp_csv):
        path = tmp_csv("ws.csv", "  代码 ,  名称 ,  数量  \n")
        assert _read_header(path) == ["代码", "名称", "数量"]

    def test_skips_blank_lines_at_start(self, tmp_csv):
        """文件起始空白行会被跳过，找到首个非空行。"""
        path = tmp_csv("skip.csv", "\n\nh1,h2\n")
        assert _read_header(path) == ["h1", "h2"]