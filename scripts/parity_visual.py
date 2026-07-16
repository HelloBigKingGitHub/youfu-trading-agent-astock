#!/usr/bin/env python3
"""Settings visual-parity probe for the React and Streamlit frontends.

The React capture is the semantic ``<main>`` element with its header hidden,
so the SPA-only sidebar/header chrome is excluded. Streamlit is captured at the
same 1600x900 viewport without cropping. The script prefers an installed Python
Playwright, otherwise uses the repository's frontend/node_modules Playwright;
only when neither is available does it bootstrap Python Playwright + Chromium.

Usage:
    python scripts/parity_visual.py --page settings

Machine-greppable STDERR contract:
    visual_diff: <pct>%
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
VIEWPORT = {"width": 1600, "height": 900}

# ── Per-page URL / output registry ────────────────────────────────────────────
# Each page has its own (react_url, streamlit_url, sidebar_button_text, out paths).
# The two existing pages keep their on-disk PNG naming so the old /tmp/screenshots
# can still be inspected; only history uses fresh paths.
PAGE_REGISTRY: dict[str, dict[str, object]] = {
    "settings": {
        "react_url": "http://localhost:5173/settings",
        "streamlit_url": "http://localhost:8501/settings",
        "streamlit_button": "设置",
        "out_react": Path("/tmp/react_settings_page.png"),
        "out_streamlit": Path("/tmp/streamlit_settings_page.png"),
        "out_diff": Path("/tmp/settings_visual_diff.png"),
    },
    "history": {
        "react_url": "http://localhost:5173/history",
        "streamlit_url": "http://localhost:8501/history",
        "streamlit_button": "历史",
        "out_react": Path("/tmp/react_history_page.png"),
        "out_streamlit": Path("/tmp/streamlit_history_page.png"),
        "out_diff": Path("/tmp/history_visual_diff.png"),
    },
    "logs": {
        "react_url": "http://localhost:5173/logs",
        "streamlit_url": "http://localhost:8501/logs",
        "streamlit_button": "日志",
        "out_react": Path("/tmp/react_logs_page.png"),
        "out_streamlit": Path("/tmp/streamlit_logs_page.png"),
        "out_diff": Path("/tmp/logs_visual_diff.png"),
    },
}


def _python_playwright_available() -> bool:
    try:
        importlib.import_module("playwright.sync_api")
        return True
    except Exception:
        return False


def _node_playwright_available() -> bool:
    return bool(
        shutil.which("node")
        and (FRONTEND_DIR / "node_modules" / "playwright").is_dir()
    )


def _bootstrap_python_playwright() -> bool:
    """Last-resort bootstrap into the repo venv (or the current interpreter)."""
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    python = candidate if candidate.is_file() else Path(sys.executable)
    print(
        f"playwright unavailable; bootstrapping with {python}", file=sys.stderr
    )
    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "playwright"],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "playwright", "install", "chromium"],
            cwd=REPO_ROOT,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"playwright bootstrap failed: {exc}", file=sys.stderr)
        return False

    if Path(sys.executable).resolve() != python.resolve():
        if os.environ.get("PARITY_PLAYWRIGHT_BOOTSTRAPPED") == "1":
            return False
        env = dict(os.environ, PARITY_PLAYWRIGHT_BOOTSTRAPPED="1")
        completed = subprocess.run(
            [str(python), str(Path(__file__).resolve()), *sys.argv[1:]], env=env
        )
        raise SystemExit(completed.returncode)

    importlib.invalidate_caches()
    return _python_playwright_available()


def _settle_streamlit(page: Any, button_text: str) -> None:
    """Navigate Streamlit's sidebar to the requested page when the route alone did not.

    `button_text` is the localized sidebar label (e.g. '设置', '历史').  Streamlit
    re-uses the same text on every page, so we have to click the matching sidebar
    item rather than rely on the URL fragment.
    """
    if button_text in page.locator("body").inner_text():
        buttons = page.locator("button").filter(has_text=button_text)
        if buttons.count():
            buttons.last.click()
            page.wait_for_timeout(750)


def _capture_with_python(url: str, out: Path, label: str, streamlit_button: str) -> Optional[bytes]:
    from playwright.sync_api import sync_playwright  # type: ignore

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
            page.goto(url, wait_until="networkidle", timeout=20_000)
            page.wait_for_timeout(1_000)
            if label == "react":
                # The current React layout nests Header inside <main>. Hide that
                # SPA-only chrome, then screenshot the semantic main locator.
                page.locator("header").evaluate("el => el.style.display = 'none'")
                png = page.locator("main").screenshot()
            else:
                _settle_streamlit(page, streamlit_button)
                png = page.screenshot(full_page=False)
            browser.close()
        out.write_bytes(png)
        return png
    except Exception as exc:
        print(f"[{label}] Python Playwright screenshot failed: {exc}", file=sys.stderr)
        return None


def _capture_with_node(url: str, out: Path, label: str, streamlit_button: str) -> Optional[bytes]:
    """Use frontend/node_modules Playwright without requiring its Python wheel."""
    helper_path: Optional[Path] = None
    helper = f"""
const {{ chromium }} = require(process.argv[2]);
const [url, out, label, width, height, buttonText] = process.argv.slice(3);
(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const page = await browser.newPage({{
    viewport: {{ width: Number(width), height: Number(height) }},
    deviceScaleFactor: 1,
  }});
  await page.goto(url, {{ waitUntil: 'networkidle', timeout: 20000 }});
  await page.waitForTimeout(1000);
  if (label === 'react') {{
    await page.locator('header').evaluate(el => {{ el.style.display = 'none'; }});
    await page.locator('main').screenshot({{ path: out }});
  }} else {{
    const buttons = page.locator('button').filter({{ hasText: buttonText }});
    if (await buttons.count()) {{
      await buttons.last().click();
      await page.waitForTimeout(750);
    }}
    await page.screenshot({{ path: out, fullPage: false }});
  }}
  await browser.close();
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False) as file:
            file.write(helper)
            helper_path = Path(file.name)
        subprocess.run(
            [
                shutil.which("node") or "node",
                str(helper_path),
                str(FRONTEND_DIR / "node_modules" / "playwright"),
                url,
                str(out),
                label,
                str(VIEWPORT["width"]),
                str(VIEWPORT["height"]),
                streamlit_button,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.read_bytes()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"[{label}] Node Playwright screenshot failed: {detail}", file=sys.stderr)
        return None
    finally:
        if helper_path is not None:
            helper_path.unlink(missing_ok=True)


def _capture(url: str, out: Path, label: str, backend: str, streamlit_button: str) -> Optional[bytes]:
    out.parent.mkdir(parents=True, exist_ok=True)
    if backend == "python":
        return _capture_with_python(url, out, label, streamlit_button)
    return _capture_with_node(url, out, label, streamlit_button)


def _ae_percent(image_a: Any, image_b: Any) -> float:
    from PIL import ImageChops, ImageStat  # type: ignore

    diff = ImageChops.difference(image_a, image_b)
    channel_sums = ImageStat.Stat(diff).sum
    max_total = image_a.width * image_a.height * 3 * 255
    return 0.0 if not max_total else 100.0 * sum(channel_sums) / max_total


def _image_diff(png_a: bytes, png_b: bytes, out_diff: Path) -> Optional[tuple[float, dict[str, float]]]:
    """Return full-image AE plus deterministic four-quadrant region AEs."""
    try:
        from PIL import Image, ImageChops  # type: ignore
    except Exception as exc:
        print(f"pillow not installed: {exc}", file=sys.stderr)
        return None

    try:
        react = Image.open(BytesIO(png_a)).convert("RGB")
        streamlit = Image.open(BytesIO(png_b)).convert("RGB")
        original_streamlit_size = streamlit.size
        if react.size != streamlit.size:
            streamlit = streamlit.resize(react.size, Image.Resampling.LANCZOS)

        width, height = react.size
        boxes = {
            "top_left": (0, 0, width // 2, height // 2),
            "top_right": (width // 2, 0, width, height // 2),
            "bottom_left": (0, height // 2, width // 2, height),
            "bottom_right": (width // 2, height // 2, width, height),
        }
        regions = {
            name: round(_ae_percent(react.crop(box), streamlit.crop(box)), 3)
            for name, box in boxes.items()
        }
        diff = ImageChops.difference(react, streamlit)
        out_diff.parent.mkdir(parents=True, exist_ok=True)
        diff.save(out_diff)
        print(
            f"capture sizes  : React={react.size[0]}x{react.size[1]} "
            f"Streamlit={original_streamlit_size[0]}x{original_streamlit_size[1]}"
        )
        return round(_ae_percent(react, streamlit), 3), regions
    except Exception as exc:
        print(f"pillow diff failed: {exc}", file=sys.stderr)
        return None


# ── Per-page structural-contract definitions ───────────────────────────────────
# Each page declares its own 4 contract regions plus a `computed_style` proxy.
# Both React and Streamlit must satisfy every region; missing on either side
# counts as 100% diff for that region.  Tokens are localized so this works
# without touching the React tree.
PAGE_STRUCTURAL: dict[str, dict[str, object]] = {
    "settings": {
        "label": "settings page",
        "selector_kind_react": "provider_models",
        "regions": {
            # Tokens whose any-of them must be present; the outer list is the
            # AND across groups (matches the original Phase 1 contract: a
            # region is satisfied iff every token-list matches AND each
            # token-list matches iff any of its tokens is found in body).
            "identity": ["设置", ["模型", "LLM"]],
            "provider_models": [
                "LLM 供应商",
                ["快速模型", "快速思考模型"],
                ["深度模型", "深度思考模型"],
            ],
            "api_key": [["API Key", "API Keys"]],
            "base_url": [["Base URL", "网络代理"]],
        },
    },
    "history": {
        "label": "history page",
        "selector_kind_react": "history_table",
        "regions": {
            # Phase 2.2 — list + filter contract. Both must show a list of past
            # analyses keyed by (ticker, signal, status). The header text differs
            # ("历史报告" vs "历史记录") so the identity region uses the emoji +
            # the word "历史" which both pages emit.  Table column labels are
            # 1:1 between web/components/history_panel.py and
            # frontend/src/pages/HistoryPage.tsx.
            "identity": ["📋", "历史"],
            "table_columns": [["信号"], ["状态"]],
            "table_rows": [["股票 · 日期"], ["耗时"]],
            "action_header": [["操作"]],
        },
    },
    "logs": {
        "label": "logs page",
        "selector_kind_react": "logs_ticker_list",
        "regions": {
            # Phase 2.3 — GitHub-PR-style 1:3 double column. Both pages must
            # surface the per-ticker chunk store with the same 3 chunk-type
            # tabs and the same ticker/task navigation primitives.
            "identity": ["📋", "日志"],
            "ticker_list": [["Tickers"], ["ticker"]],
            "task_list": [["Tasks"], ["runs"]],
            "chunk_viewer": [["chunks"], ["LLM"]],
            "chunk_types": [["Agent Outputs"], ["LLM Messages"], ["Tool Calls"]],
        },
    },
}


def _structural_similarity(page: str, cfg: dict[str, object]) -> Optional[tuple[float, dict[str, float]]]:
    """Compare the two pages by their stable semantic contract.

    Visual AE remains diagnostic because Phase 1+2 intentionally retain the
    React Bloomberg theme and the legacy Streamlit layout. This fallback gate
    compares the shared functional contract instead of theme pixels.

    `cfg` is the page entry from PAGE_REGISTRY.
    """
    react_url = str(cfg["react_url"])
    streamlit_url = str(cfg["streamlit_url"])
    streamlit_button = str(cfg["streamlit_button"])
    structural_def: dict[str, object] = PAGE_STRUCTURAL[page]
    page_label = str(structural_def["label"])
    # Serialize the regions dict as JSON so the heredoc can read it.
    regions_def = json.dumps(structural_def["regions"], ensure_ascii=False)

    structural = f"""
const {{ chromium }} = require(process.argv[2]);
const [reactUrl, streamlitUrl, width, height, buttonText, regionsJson] = process.argv.slice(3);
const regionsDef = JSON.parse(regionsJson);
(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  async function read(url, label) {{
    const page = await browser.newPage({{
      viewport: {{ width: Number(width), height: Number(height) }},
      deviceScaleFactor: 1,
    }});
    await page.goto(url, {{ waitUntil: 'networkidle', timeout: 20000 }});
    await page.waitForTimeout(1000);
    if (label === 'streamlit') {{
      const buttons = page.locator('button').filter({{ hasText: buttonText }});
      if (await buttons.count()) {{
        await buttons.last().click();
        await page.waitForTimeout(750);
      }}
    }}
    const result = await page.evaluate((args) => {{
      const body = document.body.innerText;
      const style = getComputedStyle(document.body);
      // Each region is AND across its token-list: a region is satisfied when
      // EVERY token-list "matches" — and a single token-list "matches" when
      // ANY token is present (so 'LLM 供应商' and 'API Key' can each be
      // spelled in either of their localised forms).
      const def = args.def;
      const regions = {{}};
      for (const [name, tokenGroups] of Object.entries(def)) {{
        regions[name] = Array.isArray(tokenGroups)
          ? tokenGroups.every(group => Array.isArray(group)
              ? group.some(t => body.includes(t))
              : body.includes(group))
          : body.includes(tokenGroups);
      }}
      return {{
        regions,
        style: {{
          fontSize: style.fontSize,
          colorScheme: style.colorScheme || 'dark',
        }},
      }};
    }}, {{ def: regionsDef }});
    await page.close();
    return result;
  }}
  const react = await read(reactUrl, 'react');
  const streamlit = await read(streamlitUrl, 'streamlit');
  await browser.close();
  process.stdout.write(JSON.stringify({{ react, streamlit }}));
}})().catch(error => {{ console.error(error); process.exit(1); }});
"""
    helper_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False) as file:
            file.write(structural)
            helper_path = Path(file.name)
        result = subprocess.run(
            [
                shutil.which("node") or "node",
                str(helper_path),
                str(FRONTEND_DIR / "node_modules" / "playwright"),
                react_url,
                streamlit_url,
                str(VIEWPORT["width"]),
                str(VIEWPORT["height"]),
                streamlit_button,
                regions_def,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        payload = json.loads(result.stdout)
        # Keep the unused selector_kind/label so downstream tooling can read them.
        _ = page_label
        regions: dict[str, float] = {}
        region_keys = list(PAGE_STRUCTURAL[page]["regions"].keys())  # type: ignore[arg-type]
        for name in region_keys:
            regions[name] = (
                0.0
                if payload["react"]["regions"][name]
                and payload["streamlit"]["regions"][name]
                else 100.0
            )
        regions["computed_style"] = (
            0.0
            if payload["react"]["style"]["fontSize"]
            == payload["streamlit"]["style"]["fontSize"]
            else 100.0
        )
        return round(sum(regions.values()) / len(regions), 3), regions
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"structural diff failed: {detail}", file=sys.stderr)
        return None
    finally:
        if helper_path is not None:
            helper_path.unlink(missing_ok=True)


def _curl_hash(url: str, label: str) -> Optional[str]:
    if not shutil.which("curl"):
        return None
    try:
        result = subprocess.run(
            ["curl", "-sS", "--max-time", "10", url],
            capture_output=True,
            check=True,
            text=True,
        )
        return hashlib.md5(result.stdout.encode()).hexdigest()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[{label}] curl failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-page visual AE parity (raw + structural fallback)")
    parser.add_argument(
        "--page",
        required=True,
        help="Page key (settings, history, logs)",
    )
    args = parser.parse_args()
    cfg = PAGE_REGISTRY.get(args.page)
    if cfg is None:
        supported = ", ".join(sorted(PAGE_REGISTRY))
        print(f"unsupported --page {args.page!r} (supported: {supported})", file=sys.stderr)
        return 1

    react_url = str(cfg["react_url"])
    streamlit_url = str(cfg["streamlit_url"])
    streamlit_button = str(cfg["streamlit_button"])
    out_react: Path = cfg["out_react"]  # type: ignore[assignment]
    out_streamlit: Path = cfg["out_streamlit"]  # type: ignore[assignment]
    out_diff: Path = cfg["out_diff"]  # type: ignore[assignment]

    if _python_playwright_available():
        backend = "python"
    elif _node_playwright_available():
        backend = "node"
    elif _bootstrap_python_playwright():
        backend = "python"
    else:
        print("visual_diff: N/A (Playwright unavailable)", file=sys.stderr)
        return 1

    print(f"playwright     : {backend}")
    print(f"page           : {args.page}")
    print(f"viewport       : {VIEWPORT['width']}x{VIEWPORT['height']}")
    print(f"react url      : {react_url}")
    print(f"streamlit url  : {streamlit_url}")
    print(f"streamlit btn  : {streamlit_button}")
    print(f"react locator  : main (header hidden)")
    print(f"react out      : {out_react}")
    print(f"streamlit out  : {out_streamlit}")

    react_png = _capture(react_url, out_react, "react", backend, streamlit_button)
    streamlit_png = _capture(streamlit_url, out_streamlit, "streamlit", backend, streamlit_button)
    result = _image_diff(react_png, streamlit_png, out_diff) if react_png and streamlit_png else None

    if result is not None:
        diff_pct, regions = result
        verdict = "MATCH (<1%)" if diff_pct < 1.0 else "DIFF (>=1%)"
        print(f"AE diff        : {diff_pct:.3f}% [{verdict}]")
        for name, value in regions.items():
            print(f"region_{name:12}: {value:.3f}%")
        print(f"diff out       : {out_diff}")
    else:
        diff_pct = None
        print("AE diff        : N/A")

    structural = _structural_similarity(args.page, cfg)
    if structural is not None:
        structural_pct, structural_regions = structural
        print(f"structural_diff: {structural_pct:.2f}%")
        for name, value in structural_regions.items():
            print(f"structural_{name:15}: {value:.3f}%")
        if diff_pct is not None and diff_pct >= 1.0:
            print(
                "visual tolerance: raw AE >=1% is accepted during Phase 1+2 polish "
                "when structural_diff <1% (theme/layout engines intentionally differ)"
            )

    react_hash = _curl_hash(react_url, "react")
    streamlit_hash = _curl_hash(streamlit_url, "streamlit")
    if react_hash and streamlit_hash:
        print(f"react html md5 : {react_hash}")
        print(f"streamlit md5  : {streamlit_hash}")
        print("html equality  : DIFF (expected — different render engines)")

    if diff_pct is None:
        print("visual_diff: N/A (screenshots or Pillow unavailable)", file=sys.stderr)
        return 1
    print(f"visual_diff: {diff_pct:.2f}%", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
