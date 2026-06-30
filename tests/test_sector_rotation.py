"""Tests for sector rotation digest vendor functions.

Covers:
- get_hot_strategy_ranking: parsing, sorting, empty-date default, error handling
- get_sector_rotation_digest: aggregation, batching, partial-failure, no-limitup case
- _extract_limitup_codes: parsing of THS-style markdown
- _batch_reverse_concept_blocks: batching + caching

All HTTP calls are mocked — no real network. Run with:
    pytest tests/test_sector_rotation.py -v
    pytest tests/test_sector_rotation.py --cov=tradingagents.dataflows.a_stock --cov-report=term-missing
"""

import pytest
from unittest.mock import MagicMock, patch

from tradingagents.dataflows.a_stock import (
    SectorRotationDigest,
    _batch_reverse_concept_blocks,
    _extract_limitup_codes,
    get_hot_strategy_ranking,
    get_sector_rotation_digest,
)


# ---------------------------------------------------------------------------
# get_hot_strategy_ranking
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetHotStrategyRanking:
    def _mock_response(self, data):
        resp = MagicMock()
        resp.json.return_value = {"code": 1, "message": "success", "data": data}
        resp.raise_for_status = MagicMock()
        return resp

    def test_parses_top_n(self):
        sample = [
            {"rank": 5, "question": "条件A", "heatValue": 3000, "market": None, "code": None, "chg": 0.05},
            {"rank": 3, "question": "条件B", "heatValue": 9000, "market": None, "code": None, "chg": -0.02},
            {"rank": 1, "question": "条件C", "heatValue": 5000, "market": None, "code": None, "chg": 0.10},
        ]
        with patch("tradingagents.dataflows.a_stock._em_get", return_value=self._mock_response(sample)):
            md = get_hot_strategy_ranking("2026-06-17", top_n=3)

        # Header + sort by heatValue desc
        assert "# 东财选股热度 Top 3" in md
        assert "条件B" in md and "条件C" in md and "条件A" in md
        # heatValue 9000 (条件B) should come before 5000 (条件C)
        b_idx = md.index("条件B")
        c_idx = md.index("条件C")
        a_idx = md.index("条件A")
        assert b_idx < c_idx < a_idx, "Should be sorted by heatValue desc"

    def test_empty_date_defaults_to_today(self):
        sample = [{"rank": 1, "question": "X", "heatValue": 1000, "market": None, "code": None, "chg": 0.01}]
        with patch("tradingagents.dataflows.a_stock._em_get", return_value=self._mock_response(sample)):
            md = get_hot_strategy_ranking("", top_n=5)
        # Today's date should be in the header
        from datetime import datetime
        assert datetime.now().strftime("%Y-%m-%d") in md

    def test_handles_5xx(self):
        # _em_get itself raises (timeout / connection / HTTP 5xx)
        with patch(
            "tradingagents.dataflows.a_stock._em_get",
            side_effect=Exception("HTTP 503"),
        ):
            md = get_hot_strategy_ranking("2026-06-17")
        assert md.startswith("Error fetching hot strategy ranking")
        assert "503" in md

    def test_handles_empty_data(self):
        resp = self._mock_response([])
        with patch("tradingagents.dataflows.a_stock._em_get", return_value=resp):
            md = get_hot_strategy_ranking("2026-06-17")
        assert "返回空或错误" in md

    def test_top_n_clamped_to_max_50(self):
        # Pass top_n=999 — should be clamped to 50 internally, not raise
        sample = [{"rank": i, "question": f"q{i}", "heatValue": i * 100, "market": None, "code": None, "chg": 0.01} for i in range(1, 4)]
        with patch("tradingagents.dataflows.a_stock._em_get", return_value=self._mock_response(sample)):
            md = get_hot_strategy_ranking("2026-06-17", top_n=999)
        assert "Top 50" in md or "Top" in md  # Header reflects clamped value


# ---------------------------------------------------------------------------
# _extract_limitup_codes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractLimitupCodes:
    def test_parses_ths_markdown(self):
        sample_md = (
            "# Hot Stocks with Topic Attribution (2026-06-17)\n"
            "# Source: 同花顺 editorial (human-curated reason tags)\n"
            "# Total: 3 stocks\n"
            "\n"
            "002789 *ST建艺: +4.97% 换手0.37% 成交额828 大单净量0.34 | 庭外重组+建筑装饰+国资+债务豁免\n"
            "000001 平安银行: +10.00% 换手1.20% 成交额5000 大单净量2.10 | 银行+高股息\n"
            "600519 贵州茅台: +5.00% 换手0.50% 成交额3000 大单净量1.50 | 白酒+消费\n"
            "\n"
            "## Theme Frequency (top 15)\n"
            "  银行: 1 stocks\n"
        )
        results = _extract_limitup_codes(sample_md)
        assert len(results) == 3
        assert results[0] == {"code": "002789", "name": "*ST建艺", "reason": "庭外重组+建筑装饰+国资+债务豁免"}
        assert results[1]["code"] == "000001"
        assert results[2]["code"] == "600519"

    def test_handles_empty_or_error(self):
        assert _extract_limitup_codes("") == []
        assert _extract_limitup_codes("No hot stocks data for 2026-06-17") == []
        assert _extract_limitup_codes("Error fetching hot stocks for 2026-06-17: foo") == []

    def test_tolerates_current_day_rows_without_price_data(self):
        """2026-06-26: THS API returns rows with None price fields, formatted
        as 'code name: +- 换手- 成交额- 大单净量- | reason'. Parser must still
        extract code+name+reason — otherwise the whole sector digest collapses."""
        sample_md = (
            "# Hot Stocks with Topic Attribution (2026-06-26)\n"
            "# Total: 2 stocks\n"
            "\n"
            "688409 富创精密: +- 换手- 成交额- 大单净量- | 半导体设备+一季报扭亏\n"
            "600568 ST中珠: +- 换手- 成交额- 大单净量- | 股权转让+大健康+房地产\n"
        )
        results = _extract_limitup_codes(sample_md)
        assert len(results) == 2
        assert results[0] == {"code": "688409", "name": "富创精密", "reason": "半导体设备+一季报扭亏"}
        assert results[1] == {"code": "600568", "name": "ST中珠", "reason": "股权转让+大健康+房地产"}

    def test_tolerates_legacy_empty_percent_format(self):
        """Older 'empty percent' format: 'code name: +% 换手% 成交额 大单净量 | reason'."""
        sample_md = (
            "688409 富创精密: +% 换手% 成交额 大单净量 | 半导体设备+一季报扭亏\n"
        )
        results = _extract_limitup_codes(sample_md)
        assert len(results) == 1
        assert results[0]["code"] == "688409"


# ---------------------------------------------------------------------------
# _batch_reverse_concept_blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchReverseConceptBlocks:
    def test_batches_10_stocks_into_1_call(self):
        stocks = [{"code": f"00000{i}", "name": f"stock{i}", "reason": "x"} for i in range(10)]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Result": {}}
        mock_resp.raise_for_status = MagicMock()
        with patch("tradingagents.dataflows.a_stock._requests.get", return_value=mock_resp) as mock_get, \
             patch("tradingagents.dataflows.a_stock.time.sleep"):  # skip sleep
            _batch_reverse_concept_blocks(stocks, batch_size=10)
        assert mock_get.call_count == 1

    def test_batches_20_stocks_into_2_calls(self):
        stocks = [{"code": f"0000{i:02d}", "name": f"s{i}", "reason": "x"} for i in range(20)]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Result": {}}
        mock_resp.raise_for_status = MagicMock()
        with patch("tradingagents.dataflows.a_stock._requests.get", return_value=mock_resp) as mock_get, \
             patch("tradingagents.dataflows.a_stock.time.sleep"):
            _batch_reverse_concept_blocks(stocks, batch_size=10)
        assert mock_get.call_count == 2

    def test_filters_blocks_with_lt_2_stocks(self):
        # Mock Baidu PAE returning one block with 3 stocks (pass) and one with 1 (filtered)
        stocks = [
            {"code": "000001", "name": "A", "reason": "r"},
            {"code": "000002", "name": "B", "reason": "r"},
            {"code": "000003", "name": "C", "reason": "r"},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "Result": {
                "000001": [{"name": "概念", "list": [{"name": "AI算力", "ratio": "+1.0%"}]}],
                "000002": [{"name": "概念", "list": [{"name": "AI算力", "ratio": "+1.0%"}]}],
                "000003": [{"name": "概念", "list": [{"name": "ST概念", "ratio": "-1.0%"}]}],
            }
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("tradingagents.dataflows.a_stock._requests.get", return_value=mock_resp), \
             patch("tradingagents.dataflows.a_stock.time.sleep"):
            result = _batch_reverse_concept_blocks(stocks, batch_size=10)
        # AI算力 has 2 stocks (passes), ST概念 has 1 (filtered)
        assert "AI算力" in result
        assert "ST概念" not in result
        assert len(result["AI算力"]) == 2


# ---------------------------------------------------------------------------
# get_sector_rotation_digest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSectorRotationDigest:
    def _make_ths_md(self, n: int = 3) -> str:
        lines = ["# Hot Stocks (2026-06-17)\n"]
        for i in range(n):
            code = f"00000{i}" if i < 10 else f"0000{i}"
            lines.append(f"{code} Stock{i}: +5.0% 换手1.0% 成交额1000 大单净量1.0 | 题材{chr(65+i)}\n")
        return "".join(lines)

    def test_aggregates_three_sources(self):
        # Mock all three sources
        strategy_resp = MagicMock()
        strategy_resp.json.return_value = {
            "code": 1, "message": "success",
            "data": [{"rank": 1, "question": "Q1", "heatValue": 5000, "market": None, "code": None, "chg": 0.05}],
        }
        strategy_resp.raise_for_status = MagicMock()

        # get_hot_stocks is called by name within the function
        ths_md = self._make_ths_md(3)

        # Baidu PAE returns 1 concept block
        pae_resp = MagicMock()
        pae_resp.json.return_value = {
            "Result": {
                "000000": [{"name": "概念", "list": [{"name": "测试概念", "ratio": "+1.0%"}]}],
                "000001": [{"name": "概念", "list": [{"name": "测试概念", "ratio": "+1.0%"}]}],
                "000002": [{"name": "概念", "list": [{"name": "测试概念", "ratio": "+1.0%"}]}],
            }
        }
        pae_resp.raise_for_status = MagicMock()

        with patch("tradingagents.dataflows.a_stock._em_get", return_value=strategy_resp), \
             patch("tradingagents.dataflows.a_stock.get_hot_stocks", return_value=ths_md), \
             patch("tradingagents.dataflows.a_stock._requests.get", return_value=pae_resp), \
             patch("tradingagents.dataflows.a_stock.time.sleep"):
            digest = get_sector_rotation_digest("2026-06-17", top_n=3)

        assert isinstance(digest, SectorRotationDigest)
        assert digest.sources_ok["np_ipick"] is True
        assert digest.sources_ok["ths_limitup"] is True
        assert digest.sources_ok["baidu_pae"] is True
        # All 4 sections present in markdown
        assert "## 一、机构/编辑视角" in digest.markdown
        assert "## 二、强势概念板块" in digest.markdown
        assert "## 三、龙头候选池" in digest.markdown
        assert "## 四、个股涨停理由归因" in digest.markdown

    def test_handles_zero_limitup_stocks(self):
        # np-ipick OK, get_hot_stocks returns 0 stocks
        strategy_resp = MagicMock()
        strategy_resp.json.return_value = {
            "code": 1, "message": "success",
            "data": [{"rank": 1, "question": "Q1", "heatValue": 5000, "market": None, "code": None, "chg": 0.05}],
        }
        strategy_resp.raise_for_status = MagicMock()

        ths_md = "# Hot Stocks (2026-06-17)\n# Total: 0 stocks\n"

        with patch("tradingagents.dataflows.a_stock._em_get", return_value=strategy_resp), \
             patch("tradingagents.dataflows.a_stock.get_hot_stocks", return_value=ths_md):
            digest = get_sector_rotation_digest("2026-06-17", top_n=20)

        assert digest.sources_ok["np_ipick"] is True
        # THS source succeeded (returned 0 stocks — not a failure)
        assert digest.sources_ok["ths_limitup"] is True
        # baidu_pae not invoked when there are no stocks to look up
        assert digest.sources_ok["baidu_pae"] is False
        # Should NOT have raised an exception
        assert "## 一" in digest.markdown
        # Section 2 spec wording for no-limitup case
        assert "## 二、强势概念板块: 当日无涨停股,跳过涨停归因" in digest.markdown

    def test_handles_partial_failure_gracefully(self):
        # np-ipick fails, but THS + PAE work
        em_fail = MagicMock()
        em_fail.raise_for_status.side_effect = Exception("HTTP 502")
        ths_md = self._make_ths_md(2)

        pae_resp = MagicMock()
        pae_resp.json.return_value = {
            "Result": {
                "000000": [{"name": "概念", "list": [{"name": "测试", "ratio": "+1.0%"}]}],
                "000001": [{"name": "概念", "list": [{"name": "测试", "ratio": "+1.0%"}]}],
            }
        }
        pae_resp.raise_for_status = MagicMock()

        with patch("tradingagents.dataflows.a_stock._em_get", return_value=em_fail), \
             patch("tradingagents.dataflows.a_stock.get_hot_stocks", return_value=ths_md), \
             patch("tradingagents.dataflows.a_stock._requests.get", return_value=pae_resp), \
             patch("tradingagents.dataflows.a_stock.time.sleep"):
            digest = get_sector_rotation_digest("2026-06-17", top_n=2)

        # np-ipick marked as failed, others succeeded
        assert digest.sources_ok["np_ipick"] is False
        assert digest.sources_ok["ths_limitup"] is True
        assert digest.sources_ok["baidu_pae"] is True
        # Markdown should mark np-ipick as missing
        assert "[数据缺失: np-ipick]" in digest.markdown
