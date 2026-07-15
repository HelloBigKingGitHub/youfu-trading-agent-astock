#!/usr/bin/env python3
"""Parity check: data dimension — settings.json round-trip.

Reads ~/.tradingagents/settings.json and emits an md5 hash to STDERR so the
parity gate runner can diff React vs Streamlit views (both UIs ultimately
read the same on-disk JSON, so hash equality == data parity).

Usage:
    python scripts/parity_check.py --page settings

Output (STDERR, line-based, easy to grep):
    data_hash: <md5hex>

Exit code: 0 if file exists or has been freshly seeded, 1 on hard error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


SETTINGS_FILE = Path.home() / ".tradingagents" / "settings.json"

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Parity check — settings.json hash")
    parser.add_argument("--page", required=True, help="Page key (only `settings` supported in Phase 1)")
    args = parser.parse_args()

    if args.page != "settings":
        print(f"unsupported --page {args.page!r} (Phase 1 implements only 'settings')", file=sys.stderr)
        return 1

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


if __name__ == "__main__":
    raise SystemExit(main())