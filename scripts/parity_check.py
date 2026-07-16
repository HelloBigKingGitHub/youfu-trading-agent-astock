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


def main() -> int:
    parser = argparse.ArgumentParser(description="Parity check — data hash per page")
    parser.add_argument("--page", required=True, help="Page key: 'settings' (P1), 'history' (P2.2), or 'logs' (P2.3)")
    args = parser.parse_args()

    if args.page == "settings":
        return _check_settings()
    if args.page == "history":
        return _check_history()
    if args.page == "logs":
        return _check_logs()

    print(
        f"unsupported --page {args.page!r} (supported: 'settings', 'history', 'logs')",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
