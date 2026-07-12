"""Watchlist store — JSON file persistence for user-curated ticker tags.

仿 backend/core/history_store.py 与 portfolio_store.py 风格：
dataclass + 单例 + 线程锁 + JSON 文件。

设计要点：
  * 单例：双检锁 + 类级 Lock + 实例级 RLock（与 portfolio_store 一致）
  * 原子写：tmp 文件 + replace，避免半写状态
  * 持久化：~/.tradingagents/watchlist.json
  * ticker 必须匹配 `^\\d{6}$`（与 portfolio 一致，仅 A 股 6 位代码）
  * tag 仅在 VALID_TAGS 内（避免自由文本污染）
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# 模块级路径常量：与 portfolio_store 同步暴露 `WATCHLIST_FILE` 与 `_WATCHLIST_FILE`
# 两个名字，指向同一 Path。测试通过 monkeypatch `WATCHLIST_FILE` 隔离。
_WATCHLIST_FILE: Path = Path.home() / ".tradingagents" / "watchlist.json"
WATCHLIST_FILE: Path = _WATCHLIST_FILE

VALID_TAGS: frozenset[str] = frozenset({"长线", "短线", "观察", "T0", "T1", "T2"})

_TICKER_RE = __import__("re").compile(r"^\d{6}$")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Dataclass ──────────────────────────────────────────────────────────────


@dataclass
class WatchEntry:
    """单条自选股条目。"""

    entry_id: str
    ticker: str
    tag: str = "观察"
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "ticker": self.ticker,
            "tag": self.tag,
            "note": self.note,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WatchEntry":
        return cls(
            entry_id=d.get("entry_id") or _new_id(),
            ticker=str(d.get("ticker", "")),
            tag=d.get("tag", "观察"),
            note=d.get("note", ""),
            created_at=float(d.get("created_at", time.time())),
        )


# ── Store ──────────────────────────────────────────────────────────────────


class WatchlistStore:
    """线程安全的单例 Watchlist 存储。

    所有 CRUD 方法在内部加 RLock；RLock 允许同一线程重入（add/remove
    内部调 _save 时 lock 不会死锁）。
    """

    _instance: "WatchlistStore | None" = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self._cache: list[dict] = []
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def get_instance(cls) -> "WatchlistStore":
        """双检锁获取单例。"""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_singleton(cls) -> None:
        """测试用：清空单例缓存，让下一轮 get_instance 重建。"""
        with cls._init_lock:
            cls._instance = None

    # ── CRUD ───────────────────────────────────────────────────────────────

    def add(self, ticker: str, tag: str = "观察", note: str = "") -> WatchEntry:
        """新增条目。ticker 必须 6 位、tag 必须在 VALID_TAGS。"""
        if not _TICKER_RE.match(ticker):
            raise ValueError(f"ticker 必须是 6 位数字: {ticker!r}")
        if tag not in VALID_TAGS:
            raise ValueError(
                f"tag 必须是 {sorted(VALID_TAGS)} 之一: {tag!r}"
            )
        entry = WatchEntry(
            entry_id=_new_id(),
            ticker=ticker,
            tag=tag,
            note=note,
        )
        with self._rlock:
            self._cache.append(entry.to_dict())
            self._save()
        return entry

    def remove(self, entry_id: str) -> bool:
        """按 entry_id 删除。返回是否找到并删除。"""
        with self._rlock:
            new_data = [d for d in self._cache if d.get("entry_id") != entry_id]
            if len(new_data) == len(self._cache):
                return False
            self._cache = new_data
            self._save()
            return True

    def list(self, tag: str | None = None) -> list[WatchEntry]:
        """列出条目。可选按 tag 过滤。"""
        with self._rlock:
            data = list(self._cache)
        out: list[WatchEntry] = []
        for d in data:
            if tag is not None and d.get("tag") != tag:
                continue
            out.append(WatchEntry.from_dict(d))
        out.sort(key=lambda e: (e.ticker, e.created_at))
        return out

    def count(self) -> int:
        with self._rlock:
            return len(self._cache)

    def clear(self) -> None:
        """清空全部条目（测试用）。"""
        with self._rlock:
            self._cache = []
            self._save()

    # ── Internal IO ───────────────────────────────────────────────────────

    def _load(self) -> None:
        if not WATCHLIST_FILE.exists():
            self._cache = []
            return
        try:
            raw = WATCHLIST_FILE.read_text(encoding="utf-8")
        except OSError:
            self._cache = []
            return
        if not raw.strip():
            self._cache = []
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._cache = []
            return
        if not isinstance(data, list):
            self._cache = []
            return
        self._cache = data

    def _save(self) -> None:
        try:
            WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = WATCHLIST_FILE.with_suffix(WATCHLIST_FILE.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(WATCHLIST_FILE)
        except OSError:
            pass  # Non-critical，与 portfolio_store 同容忍度


def get_watchlist_store() -> WatchlistStore:
    """模块级便捷访问：返回单例 WatchlistStore。"""
    return WatchlistStore.get_instance()
