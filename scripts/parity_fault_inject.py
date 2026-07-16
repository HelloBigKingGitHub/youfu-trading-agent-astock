#!/usr/bin/env python3
"""Fault-injection parity probes for settings and history.

Each page declares its API fault and its two UI URLs in a registry.  The
history fault is intentionally a malformed query parameter (``limit=invalid``)
so FastAPI must return HTTP 422 without touching the history store.  The UI
text is collected through Playwright locators when the repository's Node
Playwright is available; the initial HTML scan remains a safe fallback for
the legacy Streamlit page and for environments without a browser.

Machine-readable STDERR summaries:
    fault_diff: ...
    fault_diff_history: ...
    fault_diff_logs: ...
    fault_diff_chart: ...
    fault_diff_sector: ...
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover - environment diagnostic
    print(f"fault_diff: requests unavailable ({exc})", file=sys.stderr)
    raise SystemExit(1)


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
PLAYWRIGHT_MODULE = FRONTEND_DIR / "node_modules" / "playwright"
TIMEOUT_SECONDS = 10

PAGE_REGISTRY: dict[str, dict[str, str]] = {
    "settings": {
        "react_url": "http://localhost:5173/settings",
        "streamlit_url": "http://localhost:8501/settings",
        "fault_method": "PUT",
        "fault_url": "http://localhost:8000/api/settings",
        "fault_kind": "settings",
    },
    "history": {
        "react_url": "http://localhost:5173/history",
        "streamlit_url": "http://localhost:8501/history",
        "fault_method": "GET",
        "fault_url": "http://127.0.0.1:8000/api/history?limit=invalid",
        "fault_kind": "history",
    },
    "logs": {
        "react_url": "http://localhost:5173/logs",
        "streamlit_url": "http://localhost:8501/logs",
        "fault_method": "GET",
        "fault_url": "http://127.0.0.1:8000/api/logs/task?ticker=INVALID_TICKER_NONEXIST&task=9999",
        "fault_kind": "logs",
    },
    "chart": {
        "react_url": "http://localhost:5173/chart?ticker=999999&range=6m",
        "streamlit_url": "http://localhost:8501/chart?ticker=999999&range=6m",
        "fault_method": "GET",
        "fault_url": "http://127.0.0.1:8000/api/chart/kline?ticker=999999&range=6m",
        "fault_kind": "chart",
    },
    "sector": {
        "react_url": "http://localhost:5173/sector",
        "streamlit_url": "http://localhost:8501/sector",
        # top_n=abc bypasses the custom validator and lands on Pydantic's
        # int_parsing → HTTP 422, mirroring the history `limit=invalid`
        # contract. (top_n=999 would also fail but with HTTP 400 via the
        # custom [_validate_top_n] check, which doesn't match the 422
        # spec.)
        "fault_method": "GET",
        "fault_url": "http://127.0.0.1:8000/api/sector/digest?top_n=abc",
        "fault_kind": "sector",
    },
}

# Keep the regex intentionally small and UI-oriented.  The fallback marker is
# useful because the initial HTML of an SPA often contains no rendered error.
ERROR_MARKERS = re.compile(
    r"(?:加载日志失败|加载历史失败|加载设置失败|加载走势图失败|加载热力图失败|加载选股热度失败|加载概念板块失败|加载涨停归因失败|加载 4 段式报告失败|加载4段式报告失败|无 K 线数据|无K线数据|实时报价暂不可用|实时报价拉取失败|板块轮动|涨停|无概念板块|保存失败|请求失败|错误|Error|error|Invalid|invalid|"
    r"Validation|validation|Exception|exception|Traceback|traceback|404|422|502)",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

# This remains the settings injection used by the P1 gate.  deepModel is an
# object, violating the Pydantic string contract and deterministically yielding
# 422 without changing persisted settings.
INVALID_PAYLOAD: dict[str, Any] = {
    "provider": "<script>alert(1)</script>",
    "deepModel": {"not": "a string"},
    "quickModel": "fault-injection",
    "baseUrl": "",
}


def _visible_error_text(document: str) -> str:
    """Extract a compact, de-duplicated error snippet from visible document text."""
    text = html.unescape(TAG_RE.sub(" ", document))
    text = WHITESPACE_RE.sub(" ", text).strip()
    snippets: list[str] = []
    for match in ERROR_MARKERS.finditer(text):
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 120)
        snippet = text[start:end].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break
    return " / ".join(snippets) if snippets else "无可见错误文案"


def _get_html(url: str) -> tuple[int | None, str, str | None]:
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "parity-fault-inject/2"},
        )
        return response.status_code, response.text, None
    except requests.RequestException as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def _api_fault(page: str, cfg: dict[str, str]) -> tuple[int | None, str]:
    try:
        if cfg["fault_method"] == "GET":
            response = requests.get(
                cfg["fault_url"],
                timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": "parity-fault-inject/2"},
            )
        else:
            response = requests.put(
                cfg["fault_url"],
                json=INVALID_PAYLOAD,
                timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": "parity-fault-inject/2"},
            )
        return response.status_code, response.text[:240].replace("\n", " ")
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _browser_ui_text(page: str, cfg: dict[str, str]) -> dict[str, str] | None:
    """Collect visible UI text with Playwright locators.

    For history, intercept React's list request so the user-facing error alert
    is exercised rather than merely scanning the healthy initial page.  The
    Streamlit implementation does not call this FastAPI endpoint, so its
    result intentionally remains the visible text from its own page.
    """
    node = shutil.which("node")
    if not node or not PLAYWRIGHT_MODULE.is_dir():
        return None

    helper = r'''
const { chromium } = require(process.argv[2]);
const [reactUrl, streamlitUrl, pageKey, executablePath] = process.argv.slice(3);
(async () => {
  const launchOptions = { headless: true };
  if (executablePath) launchOptions.executablePath = executablePath;
  const browser = await chromium.launch(launchOptions);

  async function read(url, label) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    if (pageKey === 'history' && label === 'react') {
      await page.route(url => {
        try {
          const parsed = new URL(String(url));
          return parsed.hostname === 'localhost'
            && parsed.pathname === '/api/history';
        } catch (_) {
          return false;
        }
      }, async route => {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ detail: [{ loc: ['query', 'limit'], msg: 'Input should be a valid integer', type: 'int_parsing' }] }),
        });
      });
    }
    if (pageKey === 'logs' && label === 'react') {
      // Intercept the per-ticker task list so the React LogsPage's right
      // column surfaces an error banner instead of an empty state. The
      // ticker list endpoint stays un-intercepted so the page renders.
      await page.route(url => {
        try {
          const parsed = new URL(String(url));
          return parsed.hostname === 'localhost'
            && parsed.pathname === '/api/logs/tasks';
        } catch (_) {
          return false;
        }
      }, async route => {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'no logs for ticker \'INVALID_TICKER_NONEXIST\'' }),
        });
      });
    }
    if (pageKey === 'chart' && label === 'react') {
      // Intercept /api/chart/kline so React's ChartPage reliably surfaces the
      // destructive error banner (chart-kline-error). The /chart URL already
      // carries ticker=999999 (valid 6-digit format but unreachable) which the
      // FastAPI /chart/kline endpoint answers with 200 + empty klines — that
      // alone yields the empty state, NOT the error banner. The route
      // interception is what guarantees we exercise the chart-kline-error
      // Alert exactly like the production 5xx fallback does.
      await page.route(url => {
        try {
          const parsed = new URL(String(url));
          return parsed.hostname === 'localhost'
            && parsed.pathname === '/api/chart/kline';
        } catch (_) {
          return false;
        }
      }, async route => {
        await route.fulfill({
          status: 502,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'fault-injection: upstream mootdx/sina/push2his all unavailable' }),
        });
      });
    }
    if (pageKey === 'sector' && label === 'react') {
      // Intercept BOTH /api/sector/heatmap (default tab on page load) and
      // /api/sector/digest so React's SectorPage reliably surfaces the
      // destructive error banner (sector-heatmap-error / sector-digest-error)
      // on first paint.  The /sector URL alone would land on the live
      // (cache-warm) digest, so without this route the React default tab
      // would render the happy path instead of the error banner — exactly
      // the pattern chart uses for chart-kline-error.
      await page.route(url => {
        try {
          const parsed = new URL(String(url));
          return parsed.hostname === 'localhost'
            && (parsed.pathname === '/api/sector/heatmap'
                || parsed.pathname === '/api/sector/digest');
        } catch (_) {
          return false;
        }
      }, async route => {
        await route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: [{
              loc: ['query', 'top_n'],
              msg: 'Input should be a valid integer, unable to parse string as an integer',
              type: 'int_parsing',
              input: 'abc',
            }],
          }),
        });
      });
    }
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1500);
    const errorLocator = page.locator('[data-testid="history-error"], [data-testid="logs-tasks-error"], [data-testid="chart-kline-error"], [data-testid="chart-empty"], [data-testid="sector-heatmap-error"], [data-testid="sector-top-stocks-error"], [data-testid="sector-concepts-error"], [data-testid="sector-limit-up-error"], [data-testid="sector-digest-error"], [role="alert"]');
    let text = '';
    if (await errorLocator.count()) text = await errorLocator.first().innerText();
    if (!text) text = await page.locator('body').innerText();
    await page.close();
    return text;
  }

  const result = {
    React: await read(reactUrl, 'react'),
    Streamlit: await read(streamlitUrl, 'streamlit'),
  };
  await browser.close();
  process.stdout.write(JSON.stringify(result));
})().catch(error => { console.error(error); process.exit(1); });
'''
    helper_path: Path | None = None
    executable = "/usr/bin/chromium" if Path("/usr/bin/chromium").is_file() else ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False) as file:
            file.write(helper)
            helper_path = Path(file.name)
        result = subprocess.run(
            [
                node,
                str(helper_path),
                str(PLAYWRIGHT_MODULE),
                cfg["react_url"],
                cfg["streamlit_url"],
                page,
                executable,
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=75,
        )
        payload = json.loads(result.stdout)
        return {label: _visible_error_text(text) for label, text in payload.items()}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"Playwright locator capture failed for {page}: {detail}", file=sys.stderr)
        return None
    finally:
        if helper_path is not None:
            helper_path.unlink(missing_ok=True)


def _ui_results(page: str, cfg: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    browser_results = _browser_ui_text(page, cfg)
    if browser_results is not None:
        return browser_results, []

    ui_results: dict[str, str] = {}
    ui_errors: list[str] = []
    for label, url in (("React", cfg["react_url"]), ("Streamlit", cfg["streamlit_url"])):
        status, document, error = _get_html(url)
        if error:
            ui_results[label] = f"不可达 ({error})"
            ui_errors.append(label)
        else:
            ui_results[label] = _visible_error_text(document)
            if status is None or status >= 500:
                ui_errors.append(label)
    return ui_results, ui_errors


_FAULT_MARKERS = {
    "settings": "fault_diff",
    "history": "fault_diff_history",
    "logs": "fault_diff_logs",
    "chart": "fault_diff_chart",
    "sector": "fault_diff_sector",
}


def _run_page(page: str, cfg: dict[str, str]) -> int:
    api_status, api_detail = _api_fault(page, cfg)
    ui_results, ui_errors = _ui_results(page, cfg)

    api_summary = (
        f"API不可达: {api_detail}"
        if api_status is None
        else f"API HTTP {api_status}: {api_detail}"
    )
    react_text = ui_results["React"]
    streamlit_text = ui_results["Streamlit"]
    difference = (
        "文案一致"
        if react_text == streamlit_text
        else f"React[{react_text}] != Streamlit[{streamlit_text}]"
    )
    marker = _FAULT_MARKERS.get(page, "fault_diff")

    print(f"[{page}] fault {cfg['fault_method']} {cfg['fault_url']}")
    print(f"[{page}] {api_summary}")
    print(f"[{page}] React: {react_text}")
    print(f"[{page}] Streamlit: {streamlit_text}")
    print(f"{marker}: {difference}", file=sys.stderr)

    # A non-2xx response is the expected result of fault injection.  Only
    # unreachable UI targets are hard failures; API status is reported for the
    # gate to inspect (history should specifically be 422).
    return 1 if ui_errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-page fault-injection parity probe")
    parser.add_argument(
        "--page",
        default=None,
        help="Gate-facing page key (settings, history, logs, chart); all pages are always probed",
    )
    args = parser.parse_args()
    if args.page is not None and args.page not in PAGE_REGISTRY:
        supported = ", ".join(sorted(PAGE_REGISTRY))
        print(f"unsupported --page {args.page!r} (supported: {supported})", file=sys.stderr)
        return 1

    statuses = [_run_page(page, cfg) for page, cfg in PAGE_REGISTRY.items()]
    return 1 if any(statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
