"""Tests for backend.core.watchlist — CRUD + 持久化 + 并发 + tag 过滤."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.core.watchlist import (
    VALID_TAGS,
    WATCHLIST_FILE,
    WatchEntry,
    WatchlistStore,
    get_watchlist_store,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_watchlist(tmp_path, monkeypatch):
    """重定向 WATCHLIST_FILE 到 tmp_path + 重置单例。"""
    monkeypatch.setattr("backend.core.watchlist.WATCHLIST_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr("backend.core.watchlist.WatchlistStore._instance", None)
    return tmp_path


@pytest.fixture
def store(tmp_watchlist):
    return WatchlistStore()


# ── WatchEntry dataclass ────────────────────────────────────────────────────


class TestWatchEntry:
    def test_to_dict_from_dict_round_trip(self):
        e = WatchEntry(entry_id="abc123", ticker="600595", tag="长线", note="测试", created_at=100.0)
        d = e.to_dict()
        restored = WatchEntry.from_dict(d)
        assert restored.entry_id == "abc123"
        assert restored.ticker == "600595"
        assert restored.tag == "长线"
        assert restored.note == "测试"
        assert restored.created_at == 100.0

    def test_from_dict_missing_entry_id_uses_new(self):
        e = WatchEntry.from_dict({"ticker": "688017"})
        assert len(e.entry_id) == 12
        assert e.tag == "观察"
        assert e.note == ""


# ── 单例 / init ────────────────────────────────────────────────────────────


class TestWatchlistStoreSingleton:
    def test_double_get_instance_returns_same(self, tmp_watchlist):
        a = WatchlistStore.get_instance()
        b = WatchlistStore.get_instance()
        assert a is b

    def test_reset_singleton_isolates(self, tmp_watchlist, monkeypatch):
        monkeypatch.setattr("backend.core.watchlist.WatchlistStore._instance", None)
        a = WatchlistStore.get_instance()
        monkeypatch.setattr("backend.core.watchlist.WatchlistStore._instance", None)
        b = WatchlistStore.get_instance()
        assert a is not b

    def test_get_watchlist_store_helper(self, tmp_watchlist):
        assert get_watchlist_store() is WatchlistStore.get_instance()


# ── CRUD 校验 ──────────────────────────────────────────────────────────────


class TestAdd:
    def test_add_valid_ticker_and_tag(self, store):
        e = store.add("600595", tag="长线", note="text")
        assert e.ticker == "600595"
        assert e.tag == "长线"
        assert e.note == "text"
        assert len(e.entry_id) == 12
        assert e in store.list()

    def test_add_invalid_ticker_raises(self, store):
        with pytest.raises(ValueError, match="6 位数字"):
            store.add("abc")
        with pytest.raises(ValueError, match="6 位数字"):
            store.add("6880")  # too short
        with pytest.raises(ValueError, match="6 位数字"):
            store.add("688017x")

    def test_add_invalid_tag_raises(self, store):
        with pytest.raises(ValueError, match="tag 必须是"):
            store.add("600519", tag="随便")
        with pytest.raises(ValueError, match="tag 必须是"):
            store.add("600519", tag="")

    def test_add_default_tag_is_观察(self, store):
        e = store.add("688017")
        assert e.tag == "观察"
        assert e.note == ""


# ── 删除 ───────────────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_existing(self, store):
        e = store.add("600595")
        assert store.remove(e.entry_id) is True
        assert store.count() == 0

    def test_remove_missing_returns_false(self, store):
        assert store.remove("nonexistent") is False

    def test_remove_one_of_many(self, store):
        a = store.add("600595")
        b = store.add("688017")
        assert store.remove(a.entry_id) is True
        remaining = store.list()
        assert len(remaining) == 1
        assert remaining[0].ticker == "688017"


# ── 列表 / 过滤 / count ────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, store):
        assert store.list() == []
        assert store.count() == 0

    def test_list_all(self, store):
        store.add("600595", tag="长线")
        store.add("688017", tag="短线")
        store.add("000001", tag="观察")
        items = store.list()
        assert len(items) == 3
        tickers = [e.ticker for e in items]
        assert tickers == sorted(tickers)

    def test_list_filter_by_tag(self, store):
        store.add("600595", tag="长线")
        store.add("688017", tag="长线")
        store.add("000001", tag="短线")
        items = store.list(tag="长线")
        assert len(items) == 2
        assert {e.ticker for e in items} == {"600595", "688017"}

    def test_list_filter_unknown_tag_returns_empty(self, store):
        store.add("600595", tag="长线")
        assert store.list(tag="T0") == []

    def test_count_matches_list(self, store):
        for i in range(5):
            store.add(f"{600000 + i:06d}", tag="观察")
        assert store.count() == 5


# ── 持久化 / 重启 ─────────────────────────────────────────────────────────


class TestPersistence:
    def test_persists_across_restart(self, tmp_watchlist):
        # 第 1 次：写 2 条
        s1 = WatchlistStore()
        s1.add("600595", tag="长线", note="持久")
        s1.add("688017", tag="短线")
        assert s1.count() == 2

        # 重置单例 → 模拟重启
        WatchlistStore._instance = None
        s2 = WatchlistStore()
        assert s2.count() == 2
        items = s2.list(tag="长线")
        assert items[0].ticker == "600595"
        assert items[0].note == "持久"

    def test_corrupt_file_recovers_to_empty(self, tmp_watchlist):
        path = tmp_watchlist / "watchlist.json"
        path.write_text("not valid json", encoding="utf-8")
        s = WatchlistStore()
        assert s.count() == 0
        # 仍能 add
        s.add("600519")
        assert s.count() == 1

    def test_clear(self, store):
        store.add("600595")
        store.add("688017")
        store.clear()
        assert store.count() == 0


# ── 并发 ───────────────────────────────────────────────────────────────────


class TestThreading:
    def test_concurrent_add(self, store):
        """多线程同时 add 不破坏文件。"""

        def worker(i: int) -> None:
            store.add(f"{600000 + i:06d}", tag="观察")

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(worker, range(20)))
        assert store.count() == 20

    def test_concurrent_add_and_remove(self, store):
        ids = []
        for i in range(10):
            ids.append(store.add(f"{600000 + i:06d}").entry_id)

        def remove_worker(eid: str) -> None:
            store.remove(eid)

        with ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(remove_worker, ids))
        assert store.count() == 0

    def test_validate_tags_set(self):
        assert "长线" in VALID_TAGS
        assert "T0" in VALID_TAGS
        assert "乱写" not in VALID_TAGS
