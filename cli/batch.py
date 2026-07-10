"""CLI for batch analysis — submits a list of tickers + dates and watches
progress with a Rich Live table.

Run examples:
    python -m cli.batch 688017,600519 --date 2026-06-30
    python -m cli.batch --tickers-file ./portfolio.txt --date 2026-06-30
    python -m cli.batch 688017 --date 2026-06-30 --workers 3 --no-live \\
        --output-md ./summary.md

Flags:
    --tickers "688017,600519,000001"
    --tickers-file ./portfolio.txt   (one per line, # = comment)
    --date YYYY-MM-DD                (required)
    --workers N                       (sets BATCH_MAX_WORKERS for this run)
    --provider PROVIDER
    --deep-model MODEL
    --quick-model MODEL
    --output-md /path/to/summary.md
    --no-live                         (skip Rich Live panel)

Exit codes: 0 = all completed, 1 = some errored, 2 = all errored.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date as _date_cls
from pathlib import Path

# Make project root importable when run as `python -m cli.batch`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.table import Table  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

from backend.core.job_queue import (  # noqa: E402
    TICKER_WHITELIST_RE,
    get_job_queue,
)
from backend.api.batch_helpers import build_default_configs  # noqa: E402

console = Console()


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_tickers_from_text(text: str) -> list[str]:
    """Split text on comma/newline/whitespace and strip. Empty pieces dropped."""
    if not text:
        return []
    parts = re.split(r"[,\n\r\s]+", text)
    return [p.strip() for p in parts if p.strip()]


def _load_tickers_file(path: Path) -> list[str]:
    """Load tickers from a text file (one per line, # = comment)."""
    if not path.exists():
        raise typer.BadParameter(f"tickers 文件不存在: {path}")
    tickers: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Support comma-separated within a line too
        for piece in line.split(","):
            piece = piece.strip()
            if piece and not piece.startswith("#"):
                tickers.append(piece)
    return tickers


def _validate_tickers(tickers: list[str]) -> list[str]:
    """Validate against whitelist + dedupe. Returns deduped valid list.

    Raises typer.BadParameter on invalid / duplicate.
    """
    if not tickers:
        raise typer.BadParameter("未提供任何 ticker")

    invalid = [t for t in tickers if not TICKER_WHITELIST_RE.match(t)]
    if invalid:
        raise typer.BadParameter(
            "非法 ticker (必须是 6 位 A 股代码): " + ", ".join(invalid)
        )

    seen: set[str] = set()
    dups: list[str] = []
    out: list[str] = []
    for t in tickers:
        if t in seen:
            dups.append(t)
            continue
        seen.add(t)
        out.append(t)
    if dups:
        raise typer.BadParameter("同一 batch 内的重复 ticker: " + ", ".join(dups))
    return out


def _validate_date(s: str) -> str:
    """YYYY-MM-DD strict."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""):
        raise typer.BadParameter(f"date 必须是 YYYY-MM-DD: {s!r}")
    try:
        y, m, d = s.split("-")
        _date_cls(int(y), int(m), int(d))
    except ValueError:
        raise typer.BadParameter(f"date 不是有效日期: {s!r}")
    return s


# ── Rich Live panel ──────────────────────────────────────────────────────────


_STATUS_ICONS = {
    "pending":   "⏳ pend",
    "running":   "● run ",
    "completed": "✓ done",
    "error":     "✗ err ",
    "cancelled": "⊘ canc",
}


def _build_table(jobs: list, batch_id: str, batch_status: str) -> Table:
    """Construct the Rich Table snapshot for a tick of the Live panel."""
    table = Table(
        title=f"Batch {batch_id}  ·  status: {batch_status}  ·  {len(jobs)} jobs",
        title_style="bold cyan",
        header_style="bold magenta",
        expand=True,
    )
    table.add_column("ticker",     style="cyan",  no_wrap=True)
    table.add_column("status",     no_wrap=True)
    table.add_column("current_stage", style="yellow")
    table.add_column("elapsed",    justify="right", no_wrap=True)
    table.add_column("signal",     style="green",  no_wrap=True)
    table.add_column("error",      style="red",   overflow="fold")

    for j in jobs:
        d = j.to_dict()
        status = d.get("status", "pending")
        icon = _STATUS_ICONS.get(status, status)
        stage = d.get("current_stage") or "—"
        elapsed = d.get("elapsed") or 0.0
        elapsed_str = f"{elapsed:5.1f}s" if elapsed else "   -  "
        signal = d.get("signal") or ""
        err = (d.get("error") or "")[:80]
        table.add_row(d["ticker"], icon, stage, elapsed_str, signal, err)
    return table


def _watch_progress(
    batch_id: str, no_live: bool, poll_interval: float = 1.0
) -> None:
    """Poll the queue until batch reaches a terminal state."""
    q = get_job_queue()
    if no_live:
        # Stdout-only progress: one line per tick.
        while True:
            batch = q.get_batch(batch_id)
            if not batch:
                console.print("[red]batch 不存在[/red]")
                return
            counts = {"completed": 0, "error": 0, "running": 0, "pending": 0, "cancelled": 0}
            for j in batch.jobs:
                counts[j.status] = counts.get(j.status, 0) + 1
            console.print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"batch={batch.batch_status} "
                f"done={counts['completed']} "
                f"err={counts['error']} "
                f"run={counts['running']} "
                f"pend={counts['pending']}"
            )
            if batch.batch_status in ("completed", "partial", "failed", "cancelled"):
                return
            time.sleep(poll_interval)
        return

    with Live(console=console, refresh_per_second=2, transient=False) as live:
        while True:
            batch = q.get_batch(batch_id)
            if not batch:
                live.update(
                    Table(title=f"Batch {batch_id} 已不存在", title_style="red")
                )
                return
            table = _build_table(batch.jobs, batch_id, batch.batch_status)
            live.update(table)
            if batch.batch_status in ("completed", "partial", "failed", "cancelled"):
                # One final refresh so the table stays on screen.
                time.sleep(0.3)
                return
            time.sleep(poll_interval)


# ── Markdown summary ────────────────────────────────────────────────────────


def _render_markdown_summary(batch_id: str) -> tuple[str, list]:
    """Build a markdown summary table for the batch. Returns (md_text, jobs)."""
    q = get_job_queue()
    batch = q.get_batch(batch_id)
    if not batch:
        return f"_Batch {batch_id} 未找到_", []
    lines = [f"# Batch 汇总 · {batch_id}", ""]
    lines.append(f"- **状态**: `{batch.batch_status}`")
    lines.append(f"- **总数**: {len(batch.jobs)}")
    lines.append("")
    lines.append("| ticker | trade_date | status | current_stage | elapsed | signal | error |")
    lines.append("|--------|------------|--------|---------------|--------:|--------|-------|")
    for j in batch.jobs:
        d = j.to_dict()
        err = (d.get("error") or "").replace("|", "\\|").replace("\n", " ")[:80]
        signal = d.get("signal") or ""
        elapsed = d.get("elapsed") or 0.0
        elapsed_str = f"{elapsed:.1f}s" if elapsed else "-"
        stage = d.get("current_stage") or "-"
        lines.append(
            f"| {d['ticker']} | {d['trade_date']} | {d['status']} "
            f"| {stage} | {elapsed_str} | {signal} | {err} |"
        )
    return "\n".join(lines) + "\n", batch.jobs


# ── main callback ────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Argparse 入口 — 比 typer 更直接,支持位置参数 ticker 列表。"""
    p = argparse.ArgumentParser(
        prog="python -m cli.batch",
        description="批量分析 CLI — 并行跑多个 ticker + date,Rich Live 进度面板。",
    )
    p.add_argument(
        "tickers_pos",
        nargs="?",
        default=None,
        help="(可选) 逗号/空格分隔的 ticker 列表(如 688017,600519)。",
    )
    p.add_argument(
        "--tickers",
        dest="tickers_opt",
        default=None,
        help="与位置参数等价的显式形式。",
    )
    p.add_argument(
        "--tickers-file",
        dest="tickers_file",
        type=Path,
        default=None,
        help="ticker 文件路径(每行一个,# 开头为注释)。",
    )
    p.add_argument(
        "--date", "-d",
        dest="date",
        default=None,
        help="分析日期 YYYY-MM-DD (默认今天)。",
    )
    p.add_argument(
        "--workers", "-w",
        dest="workers",
        type=int,
        default=None,
        help="并发 worker 数 (覆盖 BATCH_MAX_WORKERS)。",
    )
    p.add_argument(
        "--provider",
        dest="provider",
        default=None,
        help="LLM provider (覆盖 BATCH_LLM_PROVIDER)。",
    )
    p.add_argument(
        "--deep-model",
        dest="deep_model",
        default=None,
        help="深度思考模型 (覆盖 BATCH_DEEP_MODEL)。",
    )
    p.add_argument(
        "--quick-model",
        dest="quick_model",
        default=None,
        help="快速思考模型 (覆盖 BATCH_QUICK_MODEL)。",
    )
    p.add_argument(
        "--output-md",
        dest="output_md",
        type=Path,
        default=None,
        help="把 markdown 汇总写入该路径。",
    )
    p.add_argument(
        "--no-live",
        dest="no_live",
        action="store_true",
        help="跳过 Rich Live 面板,只打 stdout 进度。",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """批量分析 CLI 入口。返回 exit code。"""
    args = _build_parser().parse_args(argv)

    # ── 1. 收集 tickers ────────────────────────────────────────────
    raw: list[str] = []
    if args.tickers_file is not None:
        raw.extend(_load_tickers_file(args.tickers_file))
    if args.tickers_pos:
        raw.extend(_parse_tickers_from_text(args.tickers_pos))
    if args.tickers_opt:
        raw.extend(_parse_tickers_from_text(args.tickers_opt))
    if not raw:
        console.print("[red]未提供任何 ticker — 给位置参数、--tickers 或 --tickers-file[/red]")
        return 1
    clean = _validate_tickers(raw)

    # ── 2. date ────────────────────────────────────────────────────
    if args.date is None:
        args.date = _date_cls.today().isoformat()
    args.date = _validate_date(args.date)

    # ── 3. env overrides ──────────────────────────────────────────
    if args.workers is not None:
        os.environ["BATCH_MAX_WORKERS"] = str(args.workers)
    if args.provider:
        os.environ["BATCH_LLM_PROVIDER"] = args.provider
    if args.deep_model:
        os.environ["BATCH_DEEP_MODEL"] = args.deep_model
    if args.quick_model:
        os.environ["BATCH_QUICK_MODEL"] = args.quick_model

    console.print(
        f"[bold cyan]批量分析[/bold cyan]  "
        f"{len(clean)} tickers  ·  date={args.date}  ·  "
        f"workers={args.workers or os.environ.get('BATCH_MAX_WORKERS', 5)}"
    )
    console.print(f"  tickers: {', '.join(clean)}")

    # ── 4. submit ─────────────────────────────────────────────────
    # Reset the singleton BEFORE creating the queue so BATCH_MAX_WORKERS
    # overrides take effect for this run.
    from backend.core.job_queue import JobQueue as _JQ
    _JQ._reset_singleton()
    q = get_job_queue()

    items = [{"ticker": t, "trade_date": args.date} for t in clean]
    batch_id, batch = q.create_batch(items)
    configs = build_default_configs(batch.jobs)
    q.submit(batch_id, batch.jobs, configs=configs)

    console.print(f"[green]✓ batch 已提交: {batch_id}[/green]")

    # ── 5. watch ──────────────────────────────────────────────────
    _watch_progress(batch_id, no_live=args.no_live, poll_interval=1.0)

    # ── 6. summary ────────────────────────────────────────────────
    md_text, jobs = _render_markdown_summary(batch_id)
    console.print()
    console.print(md_text)
    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(md_text, encoding="utf-8")
        console.print(f"[green]✓ markdown 汇总已写入 {args.output_md}[/green]")

    # ── 7. exit code ──────────────────────────────────────────────
    statuses = [j.status for j in jobs]
    err_count = sum(1 for s in statuses if s == "error")
    done_count = sum(1 for s in statuses if s == "completed")
    if err_count == len(statuses):
        return 2
    if err_count > 0 and done_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())