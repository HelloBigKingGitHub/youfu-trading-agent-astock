"""CLI for schedule management — list/add/pause/resume/run-now/delete/runs.

用法：
    python -m cli.schedule list [--enabled-only]
    python -m cli.schedule add --name X --cron "0 18 * * 1-5" [--source portfolio] [--tickers ...] [--tag ...]
    python -m cli.schedule run-now <schedule_id>
    python -m cli.schedule pause <schedule_id>
    python -m cli.schedule resume <schedule_id>
    python -m cli.schedule delete <schedule_id>
    python -m cli.schedule runs [<schedule_id>] [--limit 20]

Rich table 输出 + 颜色（绿 ok / 红 error / 黄 partial / 灰 skipped）。
Typer 用于参数解析与 auto --help。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import typer
from rich.console import Console
from rich.table import Table

from backend.core.scheduler import (
    RUNS_DIR,
    SCHEDULES_DIR,
    SourceType,
    VALID_CRON_HELPERS,
    Schedule,
    Scheduler,
)

app = typer.Typer(help="schedule: 管理定时分析任务", add_completion=False)
console = Console()

_STATUS_STYLE = {
    "ok": "green",
    "partial": "yellow",
    "error": "red",
    "skipped": "grey50",
    "never": "grey50",
    "running": "cyan",
}


def _status_text(status: str) -> str:
    return f"[{_STATUS_STYLE.get(status, 'white')}]{status}[/]"


def _bootstrap_scheduler() -> Scheduler:
    """CLI 入口：懒加载 scheduler（确保 SCHEDULES_DIR 存在 + presets 已建）。"""
    SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return Scheduler.get_instance()


@app.command("list")
def list_cmd(
    enabled_only: bool = typer.Option(False, "--enabled-only", help="仅显示启用的"),
):
    """列出所有 schedule。"""
    s = _bootstrap_scheduler()
    items = s.list_schedules(enabled_only=enabled_only)
    if not items:
        console.print("[yellow]没有 schedule。跑 `python -m cli.schedule add` 新增一个。[/]")
        return
    table = Table(title="Schedules", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("name")
    table.add_column("cron", style="magenta")
    table.add_column("source")
    table.add_column("enabled", justify="center")
    table.add_column("last_run_at")
    table.add_column("last_status")
    table.add_column("notify")
    for sched in items:
        enabled_mark = "[green]✅[/]" if sched.enabled else "[grey50]⏸[/]"
        last_run = (
            "—"
            if not sched.last_run_at
            else f"{__import__('datetime').datetime.fromtimestamp(sched.last_run_at).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        table.add_row(
            sched.schedule_id,
            sched.name,
            sched.cron_expr,
            sched.source_type.value if hasattr(sched.source_type, "value") else str(sched.source_type),
            enabled_mark,
            last_run,
            _status_text(sched.last_run_status),
            ",".join(sched.notify_channels),
        )
    console.print(table)
    console.print(f"\n[dim]共 {len(items)} 个 (enabled_only={enabled_only})[/]")


@app.command("add")
def add_cmd(
    name: str = typer.Option(..., "--name", help="schedule 名"),
    cron: str = typer.Option(..., "--cron", help="cron 表达式，如 '0 18 * * 1-5'"),
    source: str = typer.Option("portfolio", "--source", help="portfolio / watchlist / manual"),
    tickers: str = typer.Option("", "--tickers", help="manual 源逗号分隔的 6 位代码"),
    tag: str = typer.Option("", "--tag", help="watchlist 源 tag (长线/短线/观察/T0/T1/T2)"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="默认启用"),
    notify: str = typer.Option("log", "--notify", help="逗号分隔：log/desktop/wecom/email"),
):
    """新增 schedule。"""
    s = _bootstrap_scheduler()
    try:
        src = SourceType(source)
    except ValueError:
        console.print(f"[red]source 必须是 portfolio/watchlist/manual, got {source!r}[/]")
        raise typer.Exit(code=1)
    src_cfg: dict = {}
    if src == SourceType.MANUAL:
        if not tickers:
            console.print("[red]manual 源必须 --tickers[/]")
            raise typer.Exit(code=1)
        src_cfg["tickers"] = [t.strip() for t in tickers.split(",") if t.strip()]
    elif src == SourceType.WATCHLIST:
        if tag:
            src_cfg["tag"] = tag

    sched = Schedule(
        schedule_id="",
        name=name,
        cron_expr=cron,
        source_type=src,
        source_config=src_cfg,
        enabled=enabled,
        notify_channels=[c.strip() for c in notify.split(",") if c.strip()],
        created_by="cli",
    )
    err = sched.validate()
    if err:
        console.print(f"[red]{err}[/]")
        raise typer.Exit(code=1)
    sid = s.add_schedule(sched)
    console.print(f"[green]✅ 新增 schedule:[/] {sid} ({sched.name})")


@app.command("run-now")
def run_now_cmd(
    schedule_id: str = typer.Argument(..., help="schedule ID"),
):
    """立即跑一次。返回 batch_id。"""
    s = _bootstrap_scheduler()
    try:
        batch_id = s.run_now(schedule_id)
    except KeyError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]✅ 已提交 batch_id={batch_id}[/]")
    console.print("[dim]等待 scheduler._run_schedule 异步跑完，详情见 runs/ 子命令[/]")


@app.command("pause")
def pause_cmd(
    schedule_id: str = typer.Argument(..., help="schedule ID"),
):
    """暂停。"""
    s = _bootstrap_scheduler()
    if s.pause_schedule(schedule_id):
        console.print(f"[green]⏸ {schedule_id} 已暂停[/]")
    else:
        console.print(f"[red]未找到 {schedule_id}[/]")
        raise typer.Exit(code=1)


@app.command("resume")
def resume_cmd(
    schedule_id: str = typer.Argument(..., help="schedule ID"),
):
    """启用。"""
    s = _bootstrap_scheduler()
    if s.resume_schedule(schedule_id):
        console.print(f"[green]▶ {schedule_id} 已启用[/]")
    else:
        console.print(f"[red]未找到 {schedule_id}[/]")
        raise typer.Exit(code=1)


@app.command("delete")
def delete_cmd(
    schedule_id: str = typer.Argument(..., help="schedule ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过二次确认"),
):
    """删除（默认二次确认）。"""
    if not yes:
        confirm = typer.confirm(f"确认删除 {schedule_id}?", default=False)
        if not confirm:
            console.print("[yellow]已取消[/]")
            raise typer.Exit()
    s = _bootstrap_scheduler()
    if s.delete_schedule(schedule_id):
        console.print(f"[green]🗑 {schedule_id} 已删除[/]")
    else:
        console.print(f"[red]未找到 {schedule_id}[/]")
        raise typer.Exit(code=1)


@app.command("runs")
def runs_cmd(
    schedule_id: str = typer.Argument("", help="schedule ID（留空 = 全部）"),
    limit: int = typer.Option(20, "--limit", "-n", help="最大条数"),
):
    """看运行历史。"""
    s = _bootstrap_scheduler()
    items = s.list_runs(schedule_id=schedule_id or None, limit=limit)
    if not items:
        console.print("[yellow]暂无运行记录[/]")
        return
    table = Table(title=f"Runs (last {limit})", show_lines=False)
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("schedule_id", style="cyan")
    table.add_column("started_at")
    table.add_column("duration (s)", justify="right")
    table.add_column("status")
    table.add_column("ticker_count", justify="right")
    table.add_column("summary")
    for r in items:
        from datetime import datetime as _dt
        table.add_row(
            r.run_id,
            r.schedule_id,
            _dt.fromtimestamp(r.started_at).strftime("%Y-%m-%d %H:%M:%S"),
            f"{r.duration:.1f}",
            _status_text(r.status),
            str(r.ticker_count),
            r.summary or (r.error or "—"),
        )
    console.print(table)


@app.command("helpers")
def helpers_cmd():
    """列出 cron helper（5 个预置）。"""
    table = Table(title="Cron Helpers", show_lines=False)
    table.add_column("label")
    table.add_column("cron expr", style="magenta")
    for label, expr in VALID_CRON_HELPERS.items():
        table.add_row(label, expr)
    console.print(table)


if __name__ == "__main__":
    app()
