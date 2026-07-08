"""Portfolio CSV import / export — broker format adapters.

Supports four well-known CSV column layouts (东方财富 / 同花顺 / 雪球 /
generic) plus export to UTF-8-BOM CSV (Excel-friendly).

Import flow (called by the Streamlit panel):
  1. detect_format(csv_path)        → format name (or None)
  2. parse_csv(csv_path, format)    → list[{ticker, name, cost, quantity, date}]
  3. preview_import(parsed, existing) → {"new": [...], "conflicts": [...], "invalid": [...]}
  4. apply_import(preview, strategy, store) → list[Position]

Each successful import writes one line to ~/.tradingagents/portfolio/audit.log
via store._audit().
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tradingagents.dataflows.a_stock import _normalize_ticker  # noqa: E402

if TYPE_CHECKING:
    from backend.core.portfolio_store import PortfolioStore, Position, Transaction


# ── format definitions ──────────────────────────────────────────────────────

# Each entry maps the canonical field → list of acceptable CSV header names.
# The first match in the header wins. Multiple aliases let us handle broker
# variations without forcing the user to remap.
CSV_FORMATS: dict[str, dict[str, list[str]]] = {
    "eastmoney": {
        "code": ["证券代码", "代码"],
        "name": ["证券名称", "名称"],
        "cost": ["成本价", "持仓成本价"],
        "quantity": ["持有数量", "持仓数量", "当前数量"],
        "date": ["建仓日期", "买入日期"],
    },
    "ths": {  # 同花顺
        "code": ["股票代码", "代码"],
        "name": ["股票名称", "名称"],
        "cost": ["成本价"],
        "quantity": ["持仓数量", "当前持仓"],
        "date": ["买入日期"],
    },
    "xueqiu": {
        "code": ["symbol", "code", "ticker"],
        "name": ["name"],
        "cost": ["cost_price", "cost"],
        "quantity": ["quantity", "qty"],
        "date": ["created_at", "buy_date"],
    },
    "generic": {
        "code": ["ticker", "code", "代码", "证券代码"],
        "name": ["name", "名称", "证券名称"],
        "cost": ["cost", "成本价", "cost_basis", "持仓成本价"],
        "quantity": ["quantity", "数量", "qty", "持有数量", "持仓数量"],
        "date": ["date", "日期", "buy_date", "建仓日期", "买入日期"],
    },
}


@dataclass
class ImportRow:
    """Standardized parsed row (after format-mapping)."""

    ticker: str
    name: str
    cost: float
    quantity: int
    date: str  # YYYY-MM-DD


# ── detection ───────────────────────────────────────────────────────────────


def _read_header(path: Path, max_lines: int = 5) -> list[str]:
    """Return the first non-empty CSV header line as a list of cell strings."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for _ in range(max_lines):
            try:
                row = next(reader)
            except StopIteration:
                return []
            if row and any(c.strip() for c in row):
                return [c.strip() for c in row]
    return []


def detect_format(csv_path: Path) -> str | None:
    """Score each known format against the CSV header; return the best match.

    Confidence = (matched canonical fields) / (canonical fields). Returns the
    highest-scoring format when confidence >= 0.6, else None.
    """
    header = _read_header(csv_path)
    if not header:
        return None
    header_set = set(header)
    best: tuple[float, str] | None = None
    for fmt, mapping in CSV_FORMATS.items():
        matched = 0
        for aliases in mapping.values():
            if any(alias in header_set for alias in aliases):
                matched += 1
        score = matched / len(mapping)
        if best is None or score > best[0]:
            best = (score, fmt)
    if best is None or best[0] < 0.6:
        return None
    return best[1]


# ── parsing ─────────────────────────────────────────────────────────────────


def _pick(mapping: dict[str, list[str]], header: list[str]) -> dict[str, str]:
    """Resolve canonical → CSV column using the first alias found in header."""
    resolved: dict[str, str] = {}
    for canonical, aliases in mapping.items():
        for alias in aliases:
            if alias in header:
                resolved[canonical] = alias
                break
    return resolved


def _parse_date(s: str) -> str | None:
    """Tolerant date parser → ISO YYYY-MM-DD; returns None on failure."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_csv(csv_path: Path, format: str) -> list[ImportRow]:
    """Parse a CSV file into standardized ImportRow objects.

    Invalid rows (missing ticker / cost / quantity / date) are silently
    dropped here; `preview_import` re-checks for the UI.
    """
    if format not in CSV_FORMATS:
        raise ValueError(f"unknown format {format!r}; expected one of {list(CSV_FORMATS)}")
    mapping = CSV_FORMATS[format]
    out: list[ImportRow] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return []
        header = [h.strip() for h in header]
        resolved = _pick(mapping, header)
        if "code" not in resolved:
            return []
        code_idx = header.index(resolved["code"])
        name_idx = header.index(resolved["name"]) if "name" in resolved else -1
        cost_idx = header.index(resolved["cost"]) if "cost" in resolved else -1
        qty_idx = header.index(resolved["quantity"]) if "quantity" in resolved else -1
        date_idx = header.index(resolved["date"]) if "date" in resolved else -1
        for raw in reader:
            if not raw or not any(c.strip() for c in raw):
                continue
            try:
                code = (raw[code_idx] if code_idx < len(raw) else "").strip()
                if not code:
                    continue
                ticker = _normalize_ticker(code)
                name = (raw[name_idx] if name_idx >= 0 and name_idx < len(raw) else "").strip()
                cost = float(raw[cost_idx]) if cost_idx >= 0 and cost_idx < len(raw) and raw[cost_idx] else 0.0
                qty_raw = raw[qty_idx] if qty_idx >= 0 and qty_idx < len(raw) else ""
                quantity = int(float(qty_raw)) if qty_raw else 0
                date_raw = raw[date_idx] if date_idx >= 0 and date_idx < len(raw) else ""
                date_iso = _parse_date(date_raw)
                if not date_iso:
                    continue  # invalid date → drop
                if quantity <= 0 or cost < 0:
                    continue
            except (ValueError, IndexError):
                continue
            out.append(
                ImportRow(
                    ticker=ticker,
                    name=name,
                    cost=cost,
                    quantity=quantity,
                    date=date_iso,
                )
            )
    return out


# ── preview ─────────────────────────────────────────────────────────────────


def preview_import(
    parsed: list[ImportRow],
    existing_positions: list["Position"],
) -> dict[str, Any]:
    """Categorize parsed rows into new / conflicts / invalid buckets.

    `new` = ticker not currently held.
    `conflicts` = ticker already exists; caller decides overwrite/skip/merge.
    `invalid` = cost <= 0 / quantity <= 0 / bad ticker.
    """
    existing_by_ticker: dict[str, "Position"] = {p.ticker: p for p in existing_positions}
    new_rows: list[ImportRow] = []
    conflicts: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for row in parsed:
        if not row.ticker or row.cost <= 0 or row.quantity <= 0:
            invalid.append({"row": row, "reason": "missing or invalid fields"})
            continue
        if row.ticker in existing_by_ticker:
            conflicts.append(
                {
                    "parsed": row,
                    "existing": existing_by_ticker[row.ticker],
                    "resolution": "skip",  # default; user can change
                }
            )
        else:
            new_rows.append(row)
    return {"new": new_rows, "conflicts": conflicts, "invalid": invalid}


# ── apply ───────────────────────────────────────────────────────────────────


def apply_import(
    preview: dict[str, Any],
    resolution_strategy: str,
    store: "PortfolioStore",
    file_path: str | None = None,
    row_count: int | None = None,
) -> list["Position"]:
    """Persist previewed rows into `store` according to resolution_strategy.

    resolution_strategy: "overwrite" | "skip" | "merge"
      - overwrite: replace existing position's cost_basis/quantity/first_buy_date
      - skip:      keep existing position untouched (conflict ignored)
      - merge:     weighted-average the cost basis, sum the quantity
                   (uses existing.first_buy_date as the historical anchor)

    New rows are inserted via `add_position`. Returns the list of created
    or updated Position objects.
    """
    if resolution_strategy not in ("overwrite", "skip", "merge"):
        raise ValueError(
            f"resolution_strategy must be overwrite|skip|merge, got {resolution_strategy!r}"
        )
    created: list["Position"] = []

    for row in preview.get("new", []):
        created.append(
            store.add_position(
                ticker=row.ticker,
                name=row.name,
                cost_basis=row.cost,
                quantity=row.quantity,
                first_buy_date=row.date,
            )
        )

    for entry in preview.get("conflicts", []):
        parsed: ImportRow = entry["parsed"]
        existing: "Position" = entry["existing"]
        if resolution_strategy == "skip":
            continue
        if resolution_strategy == "overwrite":
            updated = store.update_position(
                existing.position_id,
                cost_basis=parsed.cost,
                quantity=parsed.quantity,
                last_trade_date=max(existing.last_trade_date, parsed.date),
            )
            created.append(updated)
        elif resolution_strategy == "merge":
            total_qty = existing.quantity + parsed.quantity
            if total_qty <= 0:
                continue
            merged_cost = (
                existing.cost_basis * existing.quantity
                + parsed.cost * parsed.quantity
            ) / total_qty
            updated = store.update_position(
                existing.position_id,
                cost_basis=round(merged_cost, 4),
                quantity=total_qty,
                last_trade_date=max(existing.last_trade_date, parsed.date),
            )
            created.append(updated)

    # Audit log line — best-effort, non-critical if it fails.
    store._audit(
        f"apply_import file={file_path or '<in-memory>'} "
        f"rows={row_count if row_count is not None else len(created)} "
        f"strategy={resolution_strategy} "
        f"applied={len(created)} "
        f"conflicts={len(preview.get('conflicts', []))} "
        f"invalid={len(preview.get('invalid', []))}"
    )
    return created


# ── export ──────────────────────────────────────────────────────────────────


def _write_bom_csv(path: Path, header: list[str], rows: list[list[Any]]) -> Path:
    """Write UTF-8 BOM CSV (Excel auto-detects encoding)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            writer.writerow(r)
    return path


def export_csv(
    positions: list["Position"],
    transactions: list["Transaction"] | None = None,
    output_dir: Path | None = None,
    current_prices: dict[str, float] | None = None,
) -> Path:
    """Export positions (with optional computed columns) to UTF-8 BOM CSV.

    Output columns: 代码, 名称, 成本价, 持仓数量, 持仓金额, 浮动盈亏,
    盈亏比例, 首次买入日期, 备注. When `transactions` is provided, an
    extra `交易笔数` column is appended.

    Returns the absolute path of the written file.
    """
    out_dir = output_dir or (Path.home() / ".tradingagents" / "portfolio" / "exports")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"positions_{ts}.csv"
    prices = current_prices or {}
    tx_counts: dict[str, int] = {}
    for tx in transactions or []:
        tx_counts[tx.ticker] = tx_counts.get(tx.ticker, 0) + 1
    include_tx = bool(transactions)

    header = [
        "代码",
        "名称",
        "成本价",
        "持仓数量",
        "持仓金额",
        "浮动盈亏",
        "盈亏比例",
        "首次买入日期",
        "最后交易日期",
        "备注",
    ]
    if include_tx:
        header.append("交易笔数")

    rows: list[list[Any]] = []
    for p in positions:
        price = prices.get(p.ticker, p.cost_basis)
        value = round(price * p.quantity, 2)
        pnl = round((price - p.cost_basis) * p.quantity, 2)
        pnl_pct = round((price - p.cost_basis) / p.cost_basis * 100, 2) if p.cost_basis else 0.0
        row = [
            p.ticker,
            p.name,
            round(p.cost_basis, 4),
            p.quantity,
            value,
            pnl,
            f"{pnl_pct:+.2f}%",
            p.first_buy_date,
            p.last_trade_date,
            p.notes,
        ]
        if include_tx:
            row.append(tx_counts.get(p.ticker, 0))
        rows.append(row)

    return _write_bom_csv(out_path, header, rows)


def export_transactions_csv(
    transactions: list["Transaction"],
    output_dir: Path | None = None,
) -> Path:
    """Export the transactions log to UTF-8 BOM CSV."""
    out_dir = output_dir or (Path.home() / ".tradingagents" / "portfolio" / "exports")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"transactions_{ts}.csv"
    header = [
        "日期",
        "代码",
        "动作",
        "价格",
        "数量",
        "手续费",
        "金额",
        "备注",
    ]
    rows: list[list[Any]] = []
    for tx in sorted(transactions, key=lambda t: t.date, reverse=True):
        amount = round(tx.price * tx.quantity, 2)
        rows.append(
            [
                tx.date,
                tx.ticker,
                tx.action,
                round(tx.price, 4),
                tx.quantity,
                round(tx.fees, 2),
                amount,
                tx.notes,
            ]
        )
    return _write_bom_csv(out_path, header, rows)