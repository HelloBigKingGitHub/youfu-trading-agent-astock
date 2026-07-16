"""GET /api/sector — read-only access to sector rotation digest.

Mirrors ``web/components/sector_panel.py`` 1:1 by exposing the same five
data slices the Streamlit panel renders:

- /sector/heatmap       — concept_blocks: block-name -> limit-up stocks
- /sector/top_stocks    — top_n hot strategies (np-ipick heatValue desc)
- /sector/concepts      — block-name -> aggregated stock-count + ratio
- /sector/limit_up      — hot_stocks: 同花顺 limit-up list with reason tags
- /sector/digest        — pre-rendered Markdown digest (4 sections)

The backend never consumes LLM tokens; ``get_sector_rotation_digest`` only
combines three HTTP data sources (np-ipick, 同花顺, 百度 PAE) and the markdown
is pre-rendered inside the business layer.  This API just splits the
``SectorRotationDigest`` dataclass into per-section GETs so the React page
can render each card independently.

This API does NOT modify the business layer: it reuses the existing
``tradingagents.dataflows.a_stock.get_sector_rotation_digest`` exactly.  The
Streamlit panel keeps running in parallel (硬约束 0 改).

Phase 2.5 of P2.5.P1 — the 5th page to come online after Settings, History,
Logs and Chart.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

router = APIRouter()

# In-process digest cache.  Mirrors ``sector_digest_cache`` in web/components/
# sector_panel.py — a refresh button + a 24h data-source cooldown make this
# safe to share across React + Streamlit sessions without per-call HTTP cost.
_DIGEST_CACHE: dict[str, Any] = {
    "digest": None,
    "fetched_at": 0.0,
    "params": None,  # (date, top_n) tuple
}
_CACHE_TTL = 24 * 3600  # 24h cooldown (same as Streamlit panel)


# ── helpers ──────────────────────────────────────────────────────────────────


def _validate_top_n(top_n: int) -> int:
    """Clamp top_n into [1, 50], mirroring the Streamlit panel's range."""
    if not isinstance(top_n, int) or top_n < 1 or top_n > 50:
        raise HTTPException(
            status_code=400,
            detail=f"invalid top_n {top_n!r}: must be int in [1, 50]",
        )
    return top_n


def _validate_date(date: str) -> str:
    """Permissive YYYY-MM-DD validator; empty string means 'today'."""
    if not date:
        return ""
    # Cheap structural check; the business layer tolerates malformed dates
    # gracefully (falls back to today), so we only guard against obvious
    # path-traversal-shaped strings.
    if any(ch in date for ch in ("/", "\\", "..", "\x00")):
        raise HTTPException(
            status_code=400,
            detail=f"invalid date {date!r}: use YYYY-MM-DD or empty",
        )
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise HTTPException(
            status_code=400,
            detail=f"invalid date {date!r}: use YYYY-MM-DD or empty",
        )
    return date


def _fetch_digest(date: str, top_n: int) -> Any:
    """Return a cached SectorRotationDigest or fetch a fresh one.

    The 24h cache key is the (date, top_n) tuple; this matches how the
    Streamlit panel invalidates its ``sector_digest_cache``.
    """
    params = (date, top_n)
    now = time.time()
    cached = _DIGEST_CACHE["digest"]
    if (
        cached is not None
        and _DIGEST_CACHE["params"] == params
        and (now - _DIGEST_CACHE["fetched_at"]) < _CACHE_TTL
    ):
        return cached

    try:
        from tradingagents.dataflows.a_stock import get_sector_rotation_digest

        digest = get_sector_rotation_digest(curr_date=date, top_n=top_n)
    except Exception as exc:
        logger.exception(
            "get_sector_rotation_digest raised for date=%s top_n=%d: %s",
            date,
            top_n,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"sector digest fetch failed: {exc}",
        ) from exc

    _DIGEST_CACHE["digest"] = digest
    _DIGEST_CACHE["fetched_at"] = now
    _DIGEST_CACHE["params"] = params
    return digest


def _digest_to_dict(digest: Any) -> dict[str, Any]:
    """Convert SectorRotationDigest dataclass → JSON-safe dict."""
    return {
        "hot_strategies": list(getattr(digest, "hot_strategies", []) or []),
        "hot_stocks": list(getattr(digest, "hot_stocks", []) or []),
        "concept_blocks": dict(getattr(digest, "concept_blocks", {}) or {}),
        "markdown": getattr(digest, "markdown", "") or "",
        "sources_ok": dict(getattr(digest, "sources_ok", {}) or {}),
    }


# ── endpoints ────────────────────────────────────────────────────────────────


@router.get("/sector/heatmap")
def get_heatmap(
    date: str = Query("", description="Date YYYY-MM-DD; empty = today"),
    top_n: int = Query(20, description="Top-N limit-up stocks to reverse-lookup"),
) -> dict[str, Any]:
    """Concept block heatmap: block-name → list of limit-up stocks.

    Mirrors ``concept_blocks`` in ``SectorRotationDigest``.  Each block is
    sorted by stock count desc so the React heatmap can pick the densest
    blocks first.  Useful for the treemap / grid visual in the React page.
    """
    date = _validate_date(date)
    top_n = _validate_top_n(top_n)
    digest = _fetch_digest(date, top_n)
    payload = _digest_to_dict(digest)

    blocks = payload["concept_blocks"]
    # Sort by stock count desc; tie-breaker by block name asc.
    sorted_blocks = sorted(
        blocks.items(),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
    return {
        "date": date or "today",
        "top_n": top_n,
        "concept_blocks": dict(sorted_blocks),
        "sources_ok": payload["sources_ok"],
        "count": len(sorted_blocks),
    }


@router.get("/sector/top_stocks")
def get_top_stocks(
    date: str = Query("", description="Date YYYY-MM-DD; empty = today"),
    limit: int = Query(20, description="How many top strategies to return"),
) -> dict[str, Any]:
    """Top-N hot stock-picking strategies from np-ipick.

    Mirrors ``hot_strategies`` in ``SectorRotationDigest``.  Sorted by
    ``heatValue`` desc inside the business layer; the React page can
    truncate to ``limit`` for the table view.
    """
    date = _validate_date(date)
    limit = _validate_top_n(limit)
    digest = _fetch_digest(date, limit)
    payload = _digest_to_dict(digest)
    return {
        "date": date or "today",
        "limit": limit,
        "strategies": payload["hot_strategies"][:limit],
        "sources_ok": payload["sources_ok"],
        "count": min(len(payload["hot_strategies"]), limit),
    }


@router.get("/sector/concepts")
def get_concepts(
    date: str = Query("", description="Date YYYY-MM-DD; empty = today"),
    top_n: int = Query(20, description="Top-N limit-up stocks to reverse-lookup"),
) -> dict[str, Any]:
    """Concept block list with aggregated stock-count + avg block ratio.

    Mirrors the per-block aggregation in ``web/components/sector_panel.py``
    (``block_avg_ratio`` + ``sort_blocks``).  Each entry is one block's
    summary for the React ``<ConceptsList>``.
    """
    date = _validate_date(date)
    top_n = _validate_top_n(top_n)
    digest = _fetch_digest(date, top_n)
    payload = _digest_to_dict(digest)

    blocks = payload["concept_blocks"]
    concepts: list[dict[str, Any]] = []
    for name, stocks in blocks.items():
        # Reuse the same simple-average rule as sector_panel.block_avg_ratio.
        ratios: list[float] = []
        for s in stocks:
            raw = s.get("ratio", 0) if isinstance(s, dict) else 0
            if isinstance(raw, (int, float)):
                ratios.append(float(raw))
            elif isinstance(raw, str):
                import re

                m = re.search(r"([+-]?[\d.]+)", raw)
                ratios.append(float(m.group(1)) if m else 0.0)
        avg_ratio = round(sum(ratios) / len(ratios), 2) if ratios else 0.0
        concepts.append(
            {
                "name": name,
                "stock_count": len(stocks),
                "avg_ratio": avg_ratio,
                "codes": [s.get("code", "") for s in stocks if isinstance(s, dict)],
            }
        )

    concepts.sort(key=lambda c: (-c["stock_count"], c["name"]))
    return {
        "date": date or "today",
        "top_n": top_n,
        "concepts": concepts,
        "sources_ok": payload["sources_ok"],
        "count": len(concepts),
    }


@router.get("/sector/limit_up")
def get_limit_up(
    date: str = Query("", description="Date YYYY-MM-DD; empty = today"),
    top_n: int = Query(20, description="Top-N limit-up stocks to return"),
) -> dict[str, Any]:
    """Limit-up stocks from 同花顺, with reason tags.

    Mirrors ``hot_stocks`` in ``SectorRotationDigest``.  Each entry carries
    ``{code, name, reason}`` (and a few optional fields parsed back by
    the Streamlit panel for ratio/huanshou/chengjiaoe/ddejingliang).
    """
    date = _validate_date(date)
    top_n = _validate_top_n(top_n)
    digest = _fetch_digest(date, top_n)
    payload = _digest_to_dict(digest)
    return {
        "date": date or "today",
        "top_n": top_n,
        "stocks": payload["hot_stocks"][:top_n],
        "sources_ok": payload["sources_ok"],
        "count": min(len(payload["hot_stocks"]), top_n),
    }


@router.get("/sector/digest")
def get_digest(
    date: str = Query("", description="Date YYYY-MM-DD; empty = today"),
    top_n: int = Query(20, description="Top-N limit-up stocks to reverse-lookup"),
) -> dict[str, Any]:
    """Pre-rendered 4-section Markdown digest (调度器/文字/表格混合).

    The Markdown is identical to what ``web/components/sector_panel.py``
    would render — same business layer function, same render path, no
    LLM involved.  The React page feeds it into a Markdown renderer
    (or shows it as monospace text); the parity-check script hashes this
    Markdown byte-for-byte so any drift between React and Streamlit is
    caught deterministically.
    """
    date = _validate_date(date)
    top_n = _validate_top_n(top_n)
    digest = _fetch_digest(date, top_n)
    payload = _digest_to_dict(digest)
    markdown = payload["markdown"]
    digest_hash = hashlib.md5(
        json.dumps(
            {
                "markdown": markdown,
                "hot_strategies": payload["hot_strategies"],
                "hot_stocks": payload["hot_stocks"],
                "concept_blocks": payload["concept_blocks"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "date": date or "today",
        "top_n": top_n,
        "markdown": markdown,
        "sources_ok": payload["sources_ok"],
        "hot_strategies_count": len(payload["hot_strategies"]),
        "hot_stocks_count": len(payload["hot_stocks"]),
        "concept_blocks_count": len(payload["concept_blocks"]),
        "digest_hash": digest_hash,
    }