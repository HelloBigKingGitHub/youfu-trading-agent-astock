"""Unit tests for ``web.components.sector_panel``.

The component is split into:
  - Pure helpers (parse_pct, sort_blocks, filter_blocks, block_avg_ratio,
    block_key, zhangfu_signal_cls) — no streamlit dependency, easy to test.
  - Render functions — call streamlit.* APIs; tested with module-level
    ``unittest.mock.patch`` of the streamlit symbol the component imports.

Run with:
    pytest tests/components/test_sector_panel.py -v
    pytest tests/components/test_sector_panel.py --cov=web.components.sector_panel
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from web.components.sector_panel import (
    block_avg_ratio,
    block_key,
    filter_blocks,
    parse_pct,
    sort_blocks,
    zhangfu_signal_cls,
)


# ── parse_pct ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestParsePct:
    def test_positive_string(self):
        assert parse_pct("+10.01%") == 10.01

    def test_negative_string(self):
        assert parse_pct("-3.5%") == -3.5

    def test_string_without_percent(self):
        assert parse_pct("+5.2") == 5.2

    def test_empty_string(self):
        assert parse_pct("") == 0.0

    def test_none(self):
        assert parse_pct(None) == 0.0

    def test_numeric_int(self):
        assert parse_pct(7) == 7.0

    def test_numeric_float(self):
        assert parse_pct(-2.3) == -2.3

    def test_garbage_string(self):
        assert parse_pct("N/A") == 0.0

    def test_zero(self):
        assert parse_pct("0%") == 0.0

    def test_limitup_value(self):
        assert parse_pct("+9.99%") == 9.99


# ── block_avg_ratio ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestBlockAvgRatio:
    def test_empty_list_returns_zero(self):
        assert block_avg_ratio([]) == 0.0

    def test_single_stock(self):
        assert block_avg_ratio([{"ratio": "+5.0%"}]) == 5.0

    def test_simple_average(self):
        stocks = [{"ratio": "+4%"}, {"ratio": "+6%"}, {"ratio": "-2%"}]
        assert block_avg_ratio(stocks) == pytest.approx(8 / 3)

    def test_missing_ratio_defaults_to_zero(self):
        stocks = [{"code": "300750"}, {"ratio": "+10%"}]
        assert block_avg_ratio(stocks) == 5.0

    def test_all_zeros(self):
        assert block_avg_ratio([{"ratio": "0%"}, {"ratio": "0%"}]) == 0.0


# ── block_key ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBlockKey:
    def test_returns_8_char_string(self):
        k = block_key("电池+储能")
        assert isinstance(k, str)
        assert len(k) == 8

    def test_stable_for_same_input(self):
        assert block_key("电池+储能") == block_key("电池+储能")

    def test_different_for_different_input(self):
        assert block_key("电池") != block_key("储能")

    def test_handles_special_chars(self):
        # Block names with +, &, / should not raise
        k = block_key("AI+视频&直播/算力")
        assert len(k) == 8

    def test_handles_unicode(self):
        k = block_key("固态电池")
        assert len(k) == 8


# ── sort_blocks ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSortBlocks:
    def test_sorts_by_stock_count_desc(self):
        blocks = {
            "A": [{"code": "1"}],
            "B": [{"code": "2"}, {"code": "3"}, {"code": "4"}],
            "C": [{"code": "5"}, {"code": "6"}],
        }
        result = sort_blocks(blocks)
        assert [n for n, _ in result] == ["B", "C", "A"]

    def test_empty_blocks(self):
        assert sort_blocks({}) == []

    def test_single_block(self):
        result = sort_blocks({"A": [{"code": "1"}]})
        assert result == [("A", [{"code": "1"}])]

    def test_tie_breaks_by_avg_ratio_desc(self):
        blocks = {
            "Low": [{"ratio": "+1%"}, {"ratio": "+1%"}],
            "High": [{"ratio": "+8%"}, {"ratio": "+8%"}],
        }
        result = sort_blocks(blocks)
        assert [n for n, _ in result] == ["High", "Low"]

    def test_returns_list_of_tuples(self):
        result = sort_blocks({"A": []})
        assert isinstance(result, list)
        assert isinstance(result[0], tuple)


# ── filter_blocks ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFilterBlocks:
    @pytest.fixture
    def sample(self):
        return [
            ("电池", [
                {"code": "300750", "name": "宁德时代", "ratio": "+10%"},
                {"code": "002594", "name": "比亚迪", "ratio": "+9%"},
            ]),
            ("芯片", [
                {"code": "688981", "name": "中芯国际", "ratio": "+8%"},
                {"code": "002415", "name": "海康威视", "ratio": "+5%"},
                {"code": "600584", "name": "长电科技", "ratio": "+3%"},
            ]),
            ("AI", [
                {"code": "300033", "name": "同花顺", "ratio": "+11%"},
            ]),
        ]

    def test_min_count_drops_small_blocks(self, sample):
        result = filter_blocks(sample, min_count=2, search="")
        names = {n for n, _ in result}
        assert names == {"电池", "芯片"}  # both have ≥2 stocks
        # AI (1 stock) is dropped
        assert "AI" not in names

    def test_min_count_one_keeps_all(self, sample):
        result = filter_blocks(sample, min_count=1, search="")
        assert len(result) == 3

    def test_search_by_code(self, sample):
        result = filter_blocks(sample, min_count=1, search="300")
        # 300750 and 300033 both match
        matched_stocks = [s["code"] for _, stocks in result for s in stocks]
        assert "300750" in matched_stocks
        assert "300033" in matched_stocks

    def test_search_by_name(self, sample):
        result = filter_blocks(sample, min_count=1, search="中芯")
        assert [n for n, _ in result] == ["芯片"]

    def test_search_by_block_name(self, sample):
        result = filter_blocks(sample, min_count=1, search="AI")
        assert [n for n, _ in result] == ["AI"]

    def test_search_case_insensitive(self, sample):
        result = filter_blocks(sample, min_count=1, search="ai")
        assert [n for n, _ in result] == ["AI"]

    def test_search_no_match(self, sample):
        result = filter_blocks(sample, min_count=1, search="zzz")
        assert result == []

    def test_min_count_and_search_combined(self, sample):
        # AI has 1 stock, fails min_count=2
        result = filter_blocks(sample, min_count=2, search="300")
        # Only 电池 (has 300750) passes both filters
        assert [n for n, _ in result] == ["电池"]

    def test_empty_search_passes(self, sample):
        result = filter_blocks(sample, min_count=1, search="   ")
        assert len(result) == 3


# ── zhangfu_signal_cls ───────────────────────────────────────────────────


@pytest.mark.unit
class TestZhangfuSignalCls:
    def test_limitup_is_buy(self):
        assert "buy" in zhangfu_signal_cls("+10.01%")

    def test_strong_up_is_hold(self):
        assert "hold" in zhangfu_signal_cls("+5.0%")

    def test_down_is_sell(self):
        assert "sell" in zhangfu_signal_cls("-2.0%")

    def test_zero_is_neutral(self):
        assert "neutral" in zhangfu_signal_cls("0%")

    def test_mild_up_is_neutral(self):
        assert "neutral" in zhangfu_signal_cls("+1.0%")

    def test_invalid_value_is_neutral(self):
        assert "neutral" in zhangfu_signal_cls("N/A")


# ── render-level smoke tests (mocked streamlit) ─────────────────────────


@pytest.mark.unit
class TestRenderSmoke:
    def test_render_sector_panel_with_empty_digest(self):
        """Empty digest → empty state, no crash."""
        from dataclasses import dataclass

        @dataclass
        class FakeDigest:
            hot_strategies: list = None
            hot_stocks: list = None
            concept_blocks: dict = None
            sources_ok: dict = None

        fake = FakeDigest(
            hot_strategies=[],
            hot_stocks=[],
            concept_blocks={},
            sources_ok={"np_ipick": False, "ths_limitup": False, "baidu_pae": False},
        )

        st_mock = MagicMock()
        st_mock.session_state = {"sector_digest_cache": fake}
        st_mock.button.return_value = False
        st_mock.expander.return_value.__enter__ = lambda s: s
        st_mock.expander.return_value.__exit__ = lambda s, *a: None
        # st.columns(N) returns a list of N column mocks
        st_mock.columns.side_effect = lambda n: [MagicMock() for _ in range(
            n if isinstance(n, int) else len(n)
        )]

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            # Re-import to pick up the mocked streamlit
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod.render_sector_panel()

        # html() should have been called for empty state
        assert st_mock.html.called

    def test_analyze_button_blocked_when_tracker_running(self):
        """When tracker.is_running, button click should warn + skip rerun."""
        from web.components.sector_panel import _render_analyze_button

        st_mock = MagicMock()
        st_mock.session_state = {
            "tracker": MagicMock(is_running=True),
        }
        st_mock.button.return_value = True  # simulate click

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod._render_analyze_button("300750", "abc12345")

        st_mock.warning.assert_called_once()
        # Should NOT have set start_analysis (since blocked)
        assert "start_analysis" not in st_mock.session_state
        st_mock.rerun.assert_not_called()

    def test_analyze_button_sets_session_state_when_idle(self):
        """When no running tracker, button click sets start_analysis + rerun."""
        from web.components.sector_panel import _render_analyze_button

        st_mock = MagicMock()
        st_mock.session_state = {}  # no tracker
        st_mock.button.return_value = True  # simulate click

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod._render_analyze_button("300750", "abc12345")

        assert st_mock.session_state["start_analysis"]["ticker"] == "300750"
        assert st_mock.session_state["nav"] == "analyze"
        assert st_mock.session_state["viewing_history"] is None
        st_mock.rerun.assert_called_once()

    def test_flat_fallback_when_concept_blocks_empty_but_hot_stocks_present(self):
        """No concept_blocks but hot_stocks has data → flat table renders."""
        from dataclasses import dataclass

        @dataclass
        class FakeDigest:
            hot_strategies: list = None
            hot_stocks: list = None
            concept_blocks: dict = None
            sources_ok: dict = None

        fake = FakeDigest(
            hot_strategies=[],
            hot_stocks=[{"code": "300750", "name": "宁德时代", "reason": "电池", "ratio": "+10%"}],
            concept_blocks={},
            sources_ok={"np_ipick": False, "ths_limitup": True, "baidu_pae": False},
        )

        st_mock = MagicMock()
        st_mock.session_state = {"sector_digest_cache": fake}
        st_mock.button.return_value = False
        st_mock.expander.return_value.__enter__ = lambda s: s
        st_mock.expander.return_value.__exit__ = lambda s, *a: None
        st_mock.columns.side_effect = lambda n: [MagicMock() for _ in range(
            n if isinstance(n, int) else len(n)
        )]

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod.render_sector_panel()

        # The flat fallback uses a different label than the empty state
        # Just confirm html() was called multiple times (header + meta + flat)
        assert st_mock.html.call_count >= 2

    def test_full_render_with_concept_blocks(self):
        """Full path: digest with concept_blocks → strategy expander + block tables."""
        from dataclasses import dataclass

        @dataclass
        class FakeDigest:
            hot_strategies: list = None
            hot_stocks: list = None
            concept_blocks: dict = None
            sources_ok: dict = None

        fake = FakeDigest(
            hot_strategies=[
                {"rank": 1, "heatValue": 8234, "chg": "+5%", "question": "涨幅>5%+连续拉升"},
                {"rank": 2, "heatValue": 6721, "chg": "+3%", "question": "量比>2+均线多头"},
            ],
            hot_stocks=[{"code": "300750", "name": "宁德时代", "reason": "电池", "ratio": "+10%"}],
            concept_blocks={
                "电池": [
                    {"code": "300750", "name": "宁德时代", "reason": "电池+储能", "ratio": "+10%"},
                    {"code": "002594", "name": "比亚迪", "reason": "电池+整车", "ratio": "+9%"},
                ],
                "AI": [
                    {"code": "300033", "name": "同花顺", "reason": "AI+金融", "ratio": "+11%"},
                ],
            },
            sources_ok={"np_ipick": True, "ths_limitup": True, "baidu_pae": True},
        )

        st_mock = MagicMock()
        st_mock.session_state = {"sector_digest_cache": fake}
        st_mock.button.return_value = False
        st_mock.expander.return_value.__enter__ = lambda s: s
        st_mock.expander.return_value.__exit__ = lambda s, *a: None
        st_mock.columns.side_effect = lambda n: [MagicMock() for _ in range(
            n if isinstance(n, int) else len(n)
        )]

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod.render_sector_panel()

        # Strategies rendered (expander) + meta + block expanders
        # Note: expander call_count varies by session_state; just confirm it was called
        assert st_mock.expander.called
        # Search input + selectbox rendered in toolbar
        assert st_mock.text_input.called
        assert st_mock.selectbox.called

    def test_blocks_filtered_out_render_no_match_message(self):
        """When search+filter eliminates all blocks, show empty-state msg."""
        from dataclasses import dataclass

        @dataclass
        class FakeDigest:
            hot_strategies: list = None
            hot_stocks: list = None
            concept_blocks: dict = None
            sources_ok: dict = None

        fake = FakeDigest(
            hot_strategies=[],
            hot_stocks=[],
            concept_blocks={
                "电池": [{"code": "300750", "name": "宁德时代", "ratio": "+10%"}],
            },
            sources_ok={"np_ipick": False, "ths_limitup": True, "baidu_pae": True},
        )

        st_mock = MagicMock()
        st_mock.session_state = {
            "sector_digest_cache": fake,
            "sector_search": "zzz_nomatch",
            "sector_min": 1,
        }
        st_mock.button.return_value = False
        st_mock.expander.return_value.__enter__ = lambda s: s
        st_mock.expander.return_value.__exit__ = lambda s, *a: None
        st_mock.text_input.return_value = "zzz_nomatch"
        st_mock.selectbox.return_value = 1
        st_mock.columns.side_effect = lambda n: [MagicMock() for _ in range(
            n if isinstance(n, int) else len(n)
        )]

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod.render_sector_panel()

        # Should NOT have rendered any block expanders (only strategy)
        # The "no match" empty-state html should be present
        html_calls = [str(c) for c in st_mock.html.call_args_list]
        assert any("没有匹配" in str(c) or "bb-sector-empty" in str(c) for c in html_calls)

    def test_fetch_digest_uses_cache(self):
        """When sector_digest_cache exists, _fetch_digest skips HTTP."""
        from web.components.sector_panel import _fetch_digest

        cached = MagicMock()
        st_mock = MagicMock()
        st_mock.session_state = {"sector_digest_cache": cached}
        st_mock.spinner.return_value.__enter__ = lambda s: s
        st_mock.spinner.return_value.__exit__ = lambda s, *a: None

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            digest, err = mod._fetch_digest()

        assert digest is cached
        assert err is None

    def test_fetch_digest_exception(self):
        """When vendor raises, _fetch_digest returns (None, error_msg)."""
        from web.components.sector_panel import _fetch_digest

        st_mock = MagicMock()
        st_mock.session_state = {}  # no cache
        st_mock.spinner.return_value.__enter__ = lambda s: s
        st_mock.spinner.return_value.__exit__ = lambda s, *a: None

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            with patch(
                "tradingagents.dataflows.interface.route_to_vendor",
                side_effect=ConnectionError("eastmoney timeout"),
            ):
                import importlib
                import web.components.sector_panel as mod
                importlib.reload(mod)
                digest, err = mod._fetch_digest()

        assert digest is None
        assert "加载失败" in err
        assert "eastmoney timeout" in err

    def test_refresh_button_clears_cache(self):
        """Clicking the refresh button should clear cache + rerun."""
        from web.components.sector_panel import _render_header

        st_mock = MagicMock()
        st_mock.session_state = {"sector_digest_cache": "old_data"}
        st_mock.button.return_value = True  # click
        st_mock.columns.side_effect = lambda n: [MagicMock() for _ in range(
            n if isinstance(n, int) else len(n)
        )]

        with patch.dict("sys.modules", {"streamlit": st_mock}):
            import importlib
            import web.components.sector_panel as mod
            importlib.reload(mod)
            mod._render_header()

        assert st_mock.session_state["sector_digest_cache"] is None
        st_mock.rerun.assert_called_once()
