#!/usr/bin/env python3
"""Measure the Phase 1 settings parity endpoints.

The script deliberately uses only the Python standard library so it can run in
an environment where the project dependencies are not installed.  It measures
both FastAPI endpoints (``/api/settings`` and ``/api/health``), the React Vite
root, and the Streamlit root.  The machine-readable summary is written to
STDERR as requested by the parity gate.

Usage:
    python scripts/parity_perf.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProbeResult:
    name: str
    url: str
    elapsed_ms: float
    status: int | None
    error: str | None = None


TIMEOUT_SECONDS = 10.0
PROBES = (
    ("FastAPI settings", "http://localhost:8000/api/settings"),
    ("FastAPI health", "http://localhost:8000/api/health"),
    ("React", "http://localhost:5173/"),
    ("Streamlit", "http://localhost:8501/"),
)


def _probe(name: str, url: str) -> ProbeResult:
    request = Request(url, method="GET", headers={"User-Agent": "parity-perf/1"})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            # Consume the body so the measured request includes the response
            # transfer, not just the socket/header round-trip.
            response.read()
            status = int(response.status)
        return ProbeResult(name, url, (time.perf_counter() - started) * 1000, status)
    except (OSError, URLError, TimeoutError) as exc:
        return ProbeResult(
            name,
            url,
            (time.perf_counter() - started) * 1000,
            None,
            f"{type(exc).__name__}: {exc}",
        )


def _format_ms(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}ms"


def main() -> int:
    results = [_probe(name, url) for name, url in PROBES]
    by_name = {result.name: result for result in results}

    for result in results:
        status = str(result.status) if result.status is not None else "ERR"
        suffix = f" ({result.error})" if result.error else ""
        print(f"{result.name:16} {status:>3} {_format_ms(result.elapsed_ms)}{suffix}")

    settings = by_name["FastAPI settings"]
    health = by_name["FastAPI health"]
    react = by_name["React"]
    streamlit = by_name["Streamlit"]

    # The gate has one FastAPI slot but asks us to exercise two FastAPI routes.
    # Report their mean latency in that slot and print individual timings above.
    fastapi_ms: float | None = None
    if settings.status is not None and health.status is not None:
        fastapi_ms = (settings.elapsed_ms + health.elapsed_ms) / 2

    print(
        "perf_ms: "
        f"FastAPI={_format_ms(fastapi_ms)} "
        f"React={_format_ms(react.elapsed_ms if react.status is not None else None)} "
        f"Streamlit={_format_ms(streamlit.elapsed_ms if streamlit.status is not None else None)}",
        file=sys.stderr,
    )

    return 0 if all(result.status is not None and result.status < 500 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
