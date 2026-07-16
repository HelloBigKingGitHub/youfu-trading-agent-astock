#!/usr/bin/env python3
"""Measure the React/Streamlit/FastAPI latency for every parity page.

The first version of this probe was settings-specific and also averaged the
health endpoint into the FastAPI number.  Page two needs a real API probe, so
the targets now live in a registry.  A run always exercises both registered
pages; ``--page`` is retained as the gate-facing selector and is validated so
that a typo cannot silently produce a partial parity result.

The script deliberately uses only the Python standard library.  Human-readable
individual timings go to STDOUT and the one-line machine-readable contract is
written to STDERR:

    perf_ms: settings_FastAPI=Xms settings_React=Yms settings_Streamlit=Zms history_FastAPI=Xms history_React=Yms history_Streamlit=Zms logs_FastAPI=Xms logs_React=Yms logs_Streamlit=Zms chart_FastAPI=Xms chart_React=Yms chart_Streamlit=Zms sector_FastAPI=Xms sector_React=Yms sector_Streamlit=Zms
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProbeResult:
    page: str
    target: str
    url: str
    elapsed_ms: float
    status: int | None
    error: str | None = None


TIMEOUT_SECONDS = 10.0
PROBE_TARGETS = ("FastAPI", "React", "Streamlit")

# Keep this registry in the same shape as parity_visual.py: adding a page is a
# single entry, rather than another set of hard-coded branches in this script.
PAGE_REGISTRY: dict[str, dict[str, str]] = {
    "settings": {
        "FastAPI": "http://localhost:8000/api/settings",
        "React": "http://localhost:5173/settings",
        "Streamlit": "http://localhost:8501/settings",
    },
    "history": {
        "FastAPI": "http://127.0.0.1:8000/api/history",
        "React": "http://localhost:5173/history",
        "Streamlit": "http://localhost:8501/history",
    },
    "logs": {
        "FastAPI": "http://localhost:8000/api/logs/tickers",
        "React": "http://localhost:5173/logs",
        "Streamlit": "http://localhost:8501/logs",
    },
    "chart": {
        "FastAPI": "http://127.0.0.1:8000/api/chart/kline?ticker=600595&range=6m",
        "React": "http://localhost:5173/chart?ticker=600595&range=6m",
        "Streamlit": "http://localhost:8501/chart?ticker=600595&range=6m",
    },
    "sector": {
        "FastAPI": "http://127.0.0.1:8000/api/sector/digest?top_n=20",
        "React": "http://localhost:5173/sector",
        "Streamlit": "http://localhost:8501/sector",
    },
}


def _probe(page: str, target: str, url: str) -> ProbeResult:
    request = Request(url, method="GET", headers={"User-Agent": "parity-perf/2"})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            # Consume the body so the measured request includes transfer time,
            # not only the socket/header round-trip.
            response.read()
            status = int(response.status)
        return ProbeResult(page, target, url, (time.perf_counter() - started) * 1000, status)
    except (OSError, URLError, TimeoutError) as exc:
        return ProbeResult(
            page,
            target,
            url,
            (time.perf_counter() - started) * 1000,
            None,
            f"{type(exc).__name__}: {exc}",
        )


def _format_ms(result: ProbeResult) -> str:
    return "N/A" if result.status is None else f"{result.elapsed_ms:.2f}ms"


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-page parity performance probe")
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

    results: dict[str, dict[str, ProbeResult]] = {}
    for page, targets in PAGE_REGISTRY.items():
        results[page] = {}
        for target in PROBE_TARGETS:
            result = _probe(page, target, targets[target])
            results[page][target] = result
            status = str(result.status) if result.status is not None else "ERR"
            suffix = f" ({result.error})" if result.error else ""
            print(f"{page:8} {target:9} {status:>3} {_format_ms(result)}{suffix}")

    fields: list[str] = []
    for page in PAGE_REGISTRY:
        for target in PROBE_TARGETS:
            result = results[page][target]
            fields.append(f"{page}_{target}={_format_ms(result)}")
    print("perf_ms: " + " ".join(fields), file=sys.stderr)

    return 0 if all(
        result.status is not None and result.status < 500
        for page_results in results.values()
        for result in page_results.values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
