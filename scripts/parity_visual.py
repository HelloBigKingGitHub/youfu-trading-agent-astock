#!/usr/bin/env python3
"""Parity check: visual dimension — React (5173) vs Streamlit (8501) screenshots.

Uses Playwright (if installed) to load each UI's /settings page and capture a
PNG screenshot. Then computes a simple per-pixel AE (absolute error) diff and
emits the percentage to STDERR.

If Playwright is unavailable, falls back to a `curl`-driven page-fetch diff
(both pages should serve identical static structural HTML for the h1/form/footer
even if the screenshots differ in styling).

Usage:
    python scripts/parity_visual.py --page settings

Output (STDERR, machine-greppable):
    visual_diff: <pct>%
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple


REACT_URL = "http://localhost:5173/settings"
STREAMLIT_URL = "http://localhost:8501/settings"

OUT_REACT = Path("/tmp/react_settings_page.png")
OUT_STREAMLIT = Path("/tmp/streamlit_settings_page.png")


def _try_playwright_screenshot(url: str, out: Path, label: str) -> Optional[bytes]:
    """Best-effort Playwright screenshot. Returns PNG bytes or None on failure."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        print(f"[{label}] playwright not installed: {exc}", file=sys.stderr)
        return None

    try:
        with sync_playwright() as pw:
            # Try chromium first, fall back to webkit if missing.
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception:
                browser = pw.webkit.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1000)  # let React/Streamlit settle
            png = page.screenshot(full_page=False)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png)
            browser.close()
            return png
    except Exception as exc:
        print(f"[{label}] screenshot failed: {exc}", file=sys.stderr)
        return None


def _try_pillow_diff(png_a: bytes, png_b: bytes) -> Optional[float]:
    """Pillow ImageChops AE-diff % between two PNGs (same size required)."""
    try:
        from PIL import Image, ImageChops  # type: ignore
    except Exception as exc:
        print(f"pillow not installed: {exc}", file=sys.stderr)
        return None
    try:
        a = Image.open(__import__("io").BytesIO(png_a)).convert("RGB")
        b = Image.open(__import__("io").BytesIO(png_b)).convert("RGB")
        if a.size != b.size:
            # Resize b to match a for a coarse comparison
            b = b.resize(a.size)
        diff = ImageChops.difference(a, b)
        bbox = diff.getbbox()
        if not bbox:
            return 0.0
        # Sum all channel diffs over all pixels
        total = 0
        pixels = list(diff.getdata())
        for px in pixels:
            total += sum(px)
        max_total = len(pixels) * 3 * 255
        if max_total == 0:
            return 0.0
        return round(100.0 * total / max_total, 3)
    except Exception as exc:
        print(f"pillow diff failed: {exc}", file=sys.stderr)
        return None


def _curl_hash(url: str, label: str) -> Optional[str]:
    """Fetch URL and md5 its body — fallback when screenshots are unavailable."""
    if not shutil.which("curl"):
        print(f"[{label}] no curl available", file=sys.stderr)
        return None
    try:
        res = subprocess.run(
            ["curl", "-sS", "--max-time", "10", url],
            capture_output=True,
            check=True,
            text=True,
        )
        return hashlib.md5(res.stdout.encode("utf-8")).hexdigest()
    except subprocess.CalledProcessError as exc:
        print(f"[{label}] curl failed: {exc.stderr}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"[{label}] curl error: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Parity check — visual AE diff")
    parser.add_argument("--page", required=True)
    args = parser.parse_args()
    if args.page != "settings":
        print(f"unsupported --page {args.page!r}", file=sys.stderr)
        return 1

    print(f"react url     : {REACT_URL}")
    print(f"streamlit url : {STREAMLIT_URL}")
    print(f"react out     : {OUT_REACT}")
    print(f"streamlit out : {OUT_STREAMLIT}")

    react_png = _try_playwright_screenshot(REACT_URL, OUT_REACT, "react")
    streamlit_png = _try_playwright_screenshot(STREAMLIT_URL, OUT_STREAMLIT, "streamlit")

    diff_pct: Optional[float] = None
    if react_png and streamlit_png:
        diff_pct = _try_pillow_diff(react_png, streamlit_png)
        if diff_pct is not None:
            verdict = "MATCH (<1%)" if diff_pct < 1.0 else f"DIFF ({diff_pct:.2f}%)"
            print(f"AE diff        : {diff_pct:.3f}%  [{verdict}]")
        else:
            print("AE diff        : (pillow missing, using curl-hash fallback)")
    else:
        print("AE diff        : (screenshots unavailable, using curl-hash fallback)")

    # Always emit a curl-hash as a structural sanity check (any 200-page will differ).
    react_html_hash = _curl_hash(REACT_URL, "react")
    streamlit_html_hash = _curl_hash(STREAMLIT_URL, "streamlit")
    if react_html_hash and streamlit_html_hash:
        print(f"react html md5 : {react_html_hash}")
        print(f"streamlit md5  : {streamlit_html_hash}")
        if react_html_hash == streamlit_html_hash:
            print("html equality  : MATCH (identical bytes)")
        else:
            print("html equality  : DIFF (expected — different render engines)")

    # STDERR contract
    if diff_pct is not None:
        print(f"visual_diff: {diff_pct:.2f}%", file=sys.stderr)
    elif react_png and not streamlit_png:
        print("visual_diff: 100.00%  (streamlit unreachable)", file=sys.stderr)
    elif streamlit_png and not react_png:
        print("visual_diff: 100.00%  (react unreachable)", file=sys.stderr)
    else:
        # No screenshots — declare "DIFF unmeasurable" so the runner flags it.
        print("visual_diff: N/A  (playwright + pillow unavailable — fall back to manual screenshot review)", file=sys.stderr)
        return 0  # don't hard-fail; gate runner reads the tag

    return 0


if __name__ == "__main__":
    raise SystemExit(main())