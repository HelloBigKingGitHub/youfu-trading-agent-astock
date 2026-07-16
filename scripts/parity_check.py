#!/usr/bin/env python3
"""Parity check: data dimension — settings.json / history / logs round-trip.

Reads the on-disk data source for the page under test and emits an md5 hash
to STDERR so the parity gate runner can diff React vs Streamlit views (both
UIs ultimately read the same on-disk files, so hash equality == data parity).

Usage:
    python scripts/parity_check.py --page settings
    python scripts/parity_check.py --page history
    python scripts/parity_check.py --page logs

Output (STDERR, line-based, easy to grep):
    data_hash: <md5hex>
    data_count: <N>          # history / logs pages

Exit code: 0 if file/dir exists or has been freshly seeded, 1 on hard error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


SETTINGS_FILE = Path.home() / ".tradingagents" / "settings.json"
HISTORY_DIR = Path.home() / ".tradingagents" / "logs" / "history"
LOGS_ROOT = Path.home() / ".tradingagents" / "logs"

# Stable seed for the parity round-trip — written once if missing, then
# used to hash the file in deterministic order. Avoids nondeterminism from
# `json.dump(indent=2, sort_keys=True)` vs unsorted vs trailing newline.
SEED_PAYLOAD: dict = {
    "provider": "minimax",
    "deepModel": "MiniMax-M3",
    "quickModel": "MiniMax-M2.7-highspeed",
    "baseUrl": "",
}


def _canonical_bytes(payload: dict) -> bytes:
    """Serialize to bytes in a canonical (sorted-keys, no-indent) form.

    `hashlib.md5` is content-based, so we just need the same byte input on
    both the React read path and the Streamlit read path. Canonical form
    gives us that guarantee.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _seed_if_missing(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(SEED_PAYLOAD, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _check_settings() -> int:
    """Phase 1 settings page — single settings.json round-trip."""
    _seed_if_missing(SETTINGS_FILE)
    payload = _read_json(SETTINGS_FILE)
    digest = hashlib.md5(_canonical_bytes(payload)).hexdigest()

    # STDOUT: human-readable summary
    print(f"settings.json path : {SETTINGS_FILE}")
    print(f"settings.json keys : {sorted(payload.keys())}")
    print(f"md5(canonical)     : {digest}")

    # STDERR: machine-greppable key/value
    print(f"data_hash: {digest}", file=sys.stderr)
    print(f"data_keys: {','.join(sorted(payload.keys()))}", file=sys.stderr)
    return 0


def _check_history() -> int:
    """Phase 2.2 history page — concatenate all ~/.tradingagents/logs/history/*.json.

    The store is the single source of truth for both the React history page
    (which reads via FastAPI /api/history) and the Streamlit history panel
    (which reads from the same dir). Sorting by filename gives us a stable
    byte ordering: filenames encode ticker + date + analysis_id, both
    naturally sortable in chronological/lexical order.
    """
    if not HISTORY_DIR.is_dir():
        print(f"history dir missing: {HISTORY_DIR}", file=sys.stderr)
        return 1

    json_files = sorted(HISTORY_DIR.glob("*.json"))
    # Apply same 50-entry cap as the React page default for parity alignment.
    json_files = json_files[:50]
    if not json_files:
        print(f"no history entries in {HISTORY_DIR}", file=sys.stderr)
        print("data_hash: empty", file=sys.stderr)
        print("data_count: 0", file=sys.stderr)
        return 1

    # Canonical: sorted files, sorted-keys, no-indent concat with separator.
    # Same canonical-bytes strategy as settings, so hash equals across both.
    parts: list[bytes] = []
    for path in json_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"skipping malformed {path.name}: {exc}", file=sys.stderr)
            continue
        parts.append(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    joined = b"\n".join(parts)
    digest = hashlib.md5(joined).hexdigest()

    # STDOUT: human-readable summary
    print(f"history dir     : {HISTORY_DIR}")
    print(f"history entries : {len(parts)} (of {len(json_files)} sorted files)")
    print(f"md5(canonical)  : {digest}")

    # STDERR: machine-greppable key/value
    print(f"data_hash: {digest}", file=sys.stderr)
    print(f"data_count: {len(parts)}", file=sys.stderr)
    return 0


def _check_logs() -> int:
    """Phase 2.3 logs page — concatenate every meta.json under
    ~/.tradingagents/logs/{ticker}/{date}_run{NN}/meta.json.

    The store is the single source of truth for both the React logs page
    (which reads via FastAPI /api/logs/*) and the Streamlit logs panel
    (which reads the same dir via LogStore). The per-task meta.json is the
    canonical Pydantic mirror; we hash its sorted-keys content to assert
    data parity between the two views.

    Excludes the legacy sub-tree ({ticker}/TradingAgentsStrategy_logs/) —
    it carries full_states_log_*.json blobs that dwarf the meta and would
    skew the parity hash. Those legacy tasks still appear in /api/logs but
    with chunk_counts=0, so excluding their meta from the parity hash is
    intentional and stable.
    """
    if not LOGS_ROOT.is_dir():
        print(f"logs root missing: {LOGS_ROOT}", file=sys.stderr)
        return 1

    # Iterate ticker dirs (skip hidden + the dedicated history dir).
    ticker_dirs = sorted(
        d for d in LOGS_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "history"
    )
    if not ticker_dirs:
        print(f"no tickers under {LOGS_ROOT}", file=sys.stderr)
        print("data_hash: empty", file=sys.stderr)
        print("data_count: 0", file=sys.stderr)
        return 1

    meta_paths: list[Path] = []
    for ticker_dir in ticker_dirs:
        # Skip the legacy sub-tree: it does not follow the meta.json convention.
        for child in sorted(ticker_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name == "TradingAgentsStrategy_logs":
                continue
            meta = child / "meta.json"
            if meta.is_file():
                meta_paths.append(meta)

    if not meta_paths:
        print(f"no meta.json under {LOGS_ROOT}", file=sys.stderr)
        print("data_hash: empty", file=sys.stderr)
        print("data_count: 0", file=sys.stderr)
        return 1

    parts: list[bytes] = []
    for path in meta_paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"skipping malformed {path}: {exc}", file=sys.stderr)
            continue
        parts.append(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    joined = b"\n".join(parts)
    digest = hashlib.md5(joined).hexdigest()

    # STDOUT: human-readable summary
    print(f"logs root      : {LOGS_ROOT}")
    print(f"ticker dirs    : {len(ticker_dirs)}")
    print(f"meta.json files: {len(parts)}")
    print(f"md5(canonical) : {digest}")

    # STDERR: machine-greppable key/value
    print(f"data_hash: {digest}", file=sys.stderr)
    print(f"data_count: {len(parts)}", file=sys.stderr)
    return 0


def _check_chart() -> int:
    """Phase 2.4 chart page — hash the canonical API K-line payload."""
    url = "http://127.0.0.1:8000/api/chart/kline?ticker=600595&range=6m"
    try:
        request = Request(url, headers={"User-Agent": "parity-check/2.4"})
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"chart endpoint failed: {exc}", file=sys.stderr)
        return 1

    klines = payload.get("klines") if isinstance(payload, dict) else None
    if not isinstance(klines, list):
        print("chart endpoint returned no klines list", file=sys.stderr)
        return 1
    canonical = json.dumps(klines, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.md5(canonical).hexdigest()
    print(f"chart endpoint  : {url}")
    print(f"chart source    : {payload.get('source', 'unknown')}")
    print(f"chart count     : {len(klines)}")
    print(f"md5(canonical)  : {digest}")
    print(f"data_hash_chart: {digest}", file=sys.stderr)
    print(f"data_count_chart: {len(klines)}", file=sys.stderr)
    return 0


def _check_sector() -> int:
    """Phase 2.5 sector page — hash the canonical API digest Markdown.

    The endpoint returns a pre-rendered 4-section Markdown digest (no LLM
    involved); the React SectorPage feeds it into a monospace block. Both
    UIs ultimately read from the same ``get_sector_rotation_digest`` business
    layer call, so the Markdown bytes are guaranteed identical → hash equality
    proves parity at the data level.
    """
    url = "http://127.0.0.1:8000/api/sector/digest?top_n=20"
    try:
        request = Request(url, headers={"User-Agent": "parity-check/2.5"})
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"sector endpoint failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("sector endpoint returned non-dict", file=sys.stderr)
        return 1

    markdown = payload.get("markdown") or ""
    if not markdown:
        print("sector endpoint returned empty markdown", file=sys.stderr)
        return 1

    # Canonical bytes: markdown + counters. Sort keys for byte stability.
    canonical_payload = {
        "markdown": markdown,
        "hot_strategies_count": payload.get("hot_strategies_count", 0),
        "hot_stocks_count": payload.get("hot_stocks_count", 0),
        "concept_blocks_count": payload.get("concept_blocks_count", 0),
    }
    canonical = json.dumps(
        canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.md5(canonical).hexdigest()
    sources_ok = payload.get("sources_ok") or {}
    ok_count = sum(1 for v in sources_ok.values() if v)

    print(f"sector endpoint : {url}")
    print(f"sector markdown : {len(markdown)} chars")
    print(f"sector sources  : {ok_count}/{len(sources_ok)} OK")
    print(f"md5(canonical)  : {digest}")
    print(f"data_hash_sector: {digest}", file=sys.stderr)
    print(f"data_count_sector: {len(markdown)}", file=sys.stderr)
    return 0


def _check_batch() -> int:
    """Phase 2.6 batch page — hash the canonical GET /api/batch?limit=20 list.

    The endpoint returns the JobQueue singleton's currently-known batches,
    newest-first. Both the React BatchPage (history tab) and the Streamlit
    ``web/components/batch_panel.py`` history expander hit the same backend
    queue, so the JSON bytes are guaranteed identical → hash equality proves
    parity at the data level. We canonicalise by stripping volatile fields
    (timestamps + per-job runtime) so the hash is stable across runs where
    jobs may have advanced between snapshots.
    """
    url = "http://127.0.0.1:8000/api/batch?limit=20"
    try:
        request = Request(url, headers={"User-Agent": "parity-check/2.6"})
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"batch endpoint failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("batch endpoint returned non-dict", file=sys.stderr)
        return 1

    batches = payload.get("batches")
    if not isinstance(batches, list):
        print("batch endpoint returned no batches list", file=sys.stderr)
        return 1

    # Strip volatile fields per batch + per job for stable parity hash.
    # Mirrors the strategy used by logs/history: identity is captured by
    # batch_id + ticker + status + signal, NOT by elapsed/created_at.
    VOLATILE_BATCH_KEYS = {"created_at", "finished_at"}
    VOLATILE_JOB_KEYS = {"created_at", "started_at", "finished_at", "elapsed"}
    cleaned_batches: list[dict] = []
    for b in batches:
        if not isinstance(b, dict):
            continue
        cb = {k: v for k, v in b.items() if k not in VOLATILE_BATCH_KEYS}
        jobs = cb.get("jobs") or []
        cb["jobs"] = [
            {k: v for k, v in j.items() if k not in VOLATILE_JOB_KEYS}
            for j in jobs if isinstance(j, dict)
        ]
        cleaned_batches.append(cb)

    canonical = json.dumps(
        {"batches": cleaned_batches, "total": payload.get("total", len(cleaned_batches))},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.md5(canonical).hexdigest()

    print(f"batch endpoint  : {url}")
    print(f"batch batches   : {len(cleaned_batches)}")
    print(f"batch jobs total: {sum(len(b.get('jobs', [])) for b in cleaned_batches)}")
    print(f"md5(canonical)  : {digest}")
    print(f"data_hash_batch: {digest}", file=sys.stderr)
    print(f"data_count_batch: {len(cleaned_batches)}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Parity check — data hash per page")
    parser.add_argument("--page", required=True, help="Page key: 'settings' (P1), 'history' (P2.2), 'logs' (P2.3), 'chart' (P2.4), 'sector' (P2.5), or 'batch' (P2.6)")
    args = parser.parse_args()

    if args.page == "settings":
        return _check_settings()
    if args.page == "history":
        return _check_history()
    if args.page == "logs":
        return _check_logs()
    if args.page == "chart":
        return _check_chart()
    if args.page == "sector":
        return _check_sector()
    if args.page == "batch":
        return _check_batch()

    print(
        f"unsupported --page {args.page!r} (supported: 'settings', 'history', 'logs', 'chart', 'sector', 'batch')",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
