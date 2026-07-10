"""Portfolio import — CSV 导入导出 + 4 种格式映射。

复用 backend.core.portfolio_store.PortfolioStore + Position / Account。
纯 IO + 解析层，不直接 import a_stock（保持可独立测试）。

Import flow:
  1. detect_format(csv_path)        → 'eastmoney' | 'ths' | 'xueqiu' | 'generic' | None
  2. parse_csv(csv_path, format)    → list[dict{ticker, name, cost, quantity, date}]
  3. preview_import(parsed, existing) → {"new": [...], "conflicts": [...], "invalid": [...]}
  4. apply_import(store, preview, strategy) → list[Position]
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Defensive _normalize_ticker import ─────────────────────────────────────
# a_stock 在某些精简环境（仅跑 backend 测试时）可能不可用。
# 退化为恒等映射：原 ticker 透传，不抛 ImportError。
try:
    from tradingagents.dataflows.a_stock import _normalize_ticker  # type: ignore[attr-defined]  # noqa: E402
except (ImportError, AttributeError):
    def _normalize_ticker(ticker: str) -> str:  # type: ignore[no-redef]
        """退化实现：去掉首尾空白，其它保持原样。"""
        return (ticker or "").strip()


# ── CSV_FORMATS: 4 种格式的列名映射 ─────────────────────────────────────────
# 前 3 种（eastmoney / ths / xueqiu）是精确列名（string）
# 第 4 种（generic）是候选项列表（list[str]），按顺序找第一个匹配的
CSV_FORMATS: dict[str, dict[str, str | list[str]]] = {
    "eastmoney": {
        "code": "证券代码",
        "name": "证券名称",
        "cost": "成本价",
        "quantity": "持有数量",
        "date": "建仓日期",
    },
    "ths": {  # 同花顺
        "code": "股票代码",
        "name": "股票名称",
        "cost": "成本价",
        "quantity": "持仓数量",
        "date": "买入日期",
    },
    "xueqiu": {
        "code": "symbol",
        "name": "name",
        "cost": "cost_price",
        "quantity": "quantity",
        "date": "created_at",
    },
    "generic": {  # 通用：候选项列表
        "code": ["ticker", "code", "代码"],
        "name": ["name", "名称"],
        "cost": ["cost", "成本价", "cost_basis"],
        "quantity": ["quantity", "数量", "qty"],
        "date": ["date", "日期", "buy_date"],
    },
}


# ── helpers ────────────────────────────────────────────────────────────────


def _normalize_date(date_str: str) -> str:
    """把各种日期格式转 ISO 'YYYY-MM-DD'。

    支持：
      - '2026/01/01'     → '2026-01-01'
      - '2026-01-01'     → '2026-01-01' (passthrough)
      - '2026.01.01'     → '2026-01-01'
      - '2026年01月01日' → '2026-01-01'
      - '20260101'       → '2026-01-01' (连续 8 位数字)
      - 空 / None        → '' (调用方处理)
    """
    s = (date_str or "").strip()
    if not s:
        return ""
    # 连续 8 位数字：YYYYMMDD
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # 把各种分隔符统一成 '-'，再去掉首尾 '-'
    normalized = re.sub(r"[/.年月日]", "-", s).strip("-")
    parts = normalized.split("-")
    if len(parts) == 3:
        y, m, d = parts[0].strip(), parts[1].strip(), parts[2].strip()
        # 月日补零
        if m.isdigit() and len(m) == 1:
            m = "0" + m
        if d.isdigit() and len(d) == 1:
            d = "0" + d
        return f"{y}-{m}-{d}"
    return s


def _resolve_columns(
    mapping: dict[str, str | list[str]],
    header: list[str],
) -> dict[str, str]:
    """把 mapping 里的每个 canonical 字段 → CSV 实际列名。

    - 精确字符串（eastmoney / ths / xueqiu）：直接 in header
    - list 候选（generic）：按顺序找第一个 in header
    """
    resolved: dict[str, str] = {}
    header_set = set(header)
    for canonical, target in mapping.items():
        if isinstance(target, str):
            if target in header_set:
                resolved[canonical] = target
        else:  # list[str]
            for alias in target:
                if alias in header_set:
                    resolved[canonical] = alias
                    break
    return resolved


def _read_header(path: Path) -> list[str]:
    """读 CSV 第一行 header，strip 空格，返回列名 list。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and any(c.strip() for c in row):
                return [c.strip() for c in row]
    return []


# ── 2.1 detect_format ──────────────────────────────────────────────────────


def detect_format(csv_path: Path) -> str | None:
    """读 CSV header，匹配置信度最高的格式。

    算法：
      1. 读 csv 第一行（header）
      2. 对每种 format 计算匹配分 = 命中的必需列数
      3. 返回匹配分最高的 format
      4. 匹配分 < 3 → 返回 None
    """
    header = _read_header(csv_path)
    if not header:
        return None
    header_set = set(header)

    best_score = -1
    best_fmt: str | None = None
    for fmt, mapping in CSV_FORMATS.items():
        score = 0
        for canonical, target in mapping.items():
            if isinstance(target, str):
                if target in header_set:
                    score += 1
            else:
                # 任意候选命中算 1 分
                if any(alias in header_set for alias in target):
                    score += 1
        if score > best_score:
            best_score = score
            best_fmt = fmt

    if best_score < 3:
        return None
    return best_fmt


# ── 2.2 parse_csv ──────────────────────────────────────────────────────────


def parse_csv(csv_path: Path, format: str) -> list[dict]:
    """解析 CSV 为标准格式 list[{ticker, name, cost, quantity, date}, ...]

    format 必须已在 CSV_FORMATS 里，否则 raise ValueError。

    跳过规则：
      - cost < 0
      - quantity <= 0
      - date 无法解析
      - ticker 为空
    """
    if format not in CSV_FORMATS:
        raise ValueError(
            f"unknown format {format!r}; expected one of {list(CSV_FORMATS)}"
        )
    mapping = CSV_FORMATS[format]
    out: list[dict] = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return []
        header = [h.strip() for h in header]

        # 字段 → 列名 映射
        col_map = _resolve_columns(mapping, header)
        if "code" not in col_map:
            return []

        # 各字段的列 idx（缺失字段用 -1 标记）
        idx_code = header.index(col_map["code"])
        idx_name = header.index(col_map["name"]) if "name" in col_map else -1
        idx_cost = header.index(col_map["cost"]) if "cost" in col_map else -1
        idx_qty = header.index(col_map["quantity"]) if "quantity" in col_map else -1
        idx_date = header.index(col_map["date"]) if "date" in col_map else -1

        for raw in reader:
            if not raw or not any(c.strip() for c in raw):
                continue
            try:
                # ticker
                code = (
                    raw[idx_code] if idx_code < len(raw) else ""
                ).strip()
                if not code:
                    continue
                ticker = _normalize_ticker(code)

                # name
                name = (
                    raw[idx_name] if 0 <= idx_name < len(raw) else ""
                ).strip()

                # cost
                cost_raw = raw[idx_cost] if 0 <= idx_cost < len(raw) else ""
                if not cost_raw:
                    continue
                cost = float(cost_raw)

                # quantity
                qty_raw = raw[idx_qty] if 0 <= idx_qty < len(raw) else ""
                if not qty_raw:
                    continue
                quantity = int(float(qty_raw))

                # date
                date_raw = raw[idx_date] if 0 <= idx_date < len(raw) else ""
                date_iso = _normalize_date(date_raw)
                if not date_iso or date_iso == "":
                    continue

                # 跳过 cost < 0 或 quantity <= 0 的行
                if cost < 0 or quantity <= 0:
                    continue
            except (ValueError, IndexError):
                continue

            out.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "cost": cost,
                    "quantity": quantity,
                    "date": date_iso,
                }
            )

    return out


# ── 2.3 preview_import ─────────────────────────────────────────────────────


def preview_import(
    parsed: list[dict],
    existing_positions: list,  # list[Position]
) -> dict:
    """把 parsed 分类成 new / conflicts / invalid。

    Returns:
      {
        "new":       [parsed_item, ...],                # store 里没有的 ticker
        "conflicts": [
            {"parsed": {...}, "existing": Position, "ticker": "600595"},
            ...
        ],
        "invalid":   [parsed_item, ...],                # 校验失败的行
      }
    """
    existing_by_ticker: dict[str, Any] = {
        p.ticker: p for p in existing_positions
    }
    new_rows: list[dict] = []
    conflicts: list[dict] = []
    invalid: list[dict] = []

    for item in parsed:
        ticker = item.get("ticker", "")
        cost = item.get("cost", 0.0)
        quantity = item.get("quantity", 0)

        # 二次校验：防御 parse_csv 漏掉的边缘 case
        if not ticker or cost < 0 or quantity <= 0:
            invalid.append(item)
            continue

        if ticker in existing_by_ticker:
            conflicts.append(
                {
                    "parsed": item,
                    "existing": existing_by_ticker[ticker],
                    "ticker": ticker,
                }
            )
        else:
            new_rows.append(item)

    return {"new": new_rows, "conflicts": conflicts, "invalid": invalid}


# ── 2.4 apply_import ───────────────────────────────────────────────────────


def apply_import(
    store: Any,  # PortfolioStore
    preview: dict,
    resolution_strategy: str,  # 'overwrite' | 'skip' | 'merge'
) -> list:
    """把 preview_import 结果应用到 store。

    resolution_strategy:
      - 'overwrite': 先 delete existing_position，再 add_position (parsed)
      - 'skip':      只 add preview['new']，跳过 conflicts
      - 'merge':     MVP 暂不实现 → raise NotImplementedError

    写 store._audit() 记录 file_path + row_count + conflicts + strategy。
    """
    if resolution_strategy == "merge":
        raise NotImplementedError(
            "merge 策略在 MVP 中暂不实现：quantity 累加 + cost 加权平均逻辑复杂，"
            "请先用 overwrite 或 skip。UI 不应让用户选 merge。"
        )
    if resolution_strategy not in ("overwrite", "skip"):
        raise ValueError(
            f"resolution_strategy must be 'overwrite' | 'skip' | 'merge', "
            f"got {resolution_strategy!r}"
        )

    added: list = []

    # 1) new 行：直接 add
    for item in preview.get("new", []):
        pos = store.add_position(
            ticker=item["ticker"],
            name=item.get("name", ""),
            cost_basis=item["cost"],
            quantity=item["quantity"],
            first_buy_date=item["date"],
        )
        added.append(pos)

    # 2) conflicts：按 strategy 处理
    for entry in preview.get("conflicts", []):
        parsed_item: dict = entry["parsed"]
        existing = entry["existing"]
        if resolution_strategy == "skip":
            continue
        # overwrite：先 delete 再 add
        store.delete_position(existing.position_id)
        pos = store.add_position(
            ticker=parsed_item["ticker"],
            name=parsed_item.get("name", ""),
            cost_basis=parsed_item["cost"],
            quantity=parsed_item["quantity"],
            first_buy_date=parsed_item["date"],
        )
        added.append(pos)

    # 3) audit
    store._audit(
        f"apply_import strategy={resolution_strategy} "
        f"new={len(preview.get('new', []))} "
        f"conflicts={len(preview.get('conflicts', []))} "
        f"invalid={len(preview.get('invalid', []))} "
        f"applied={len(added)}"
    )
    return added


# ── 2.5 export_csv ─────────────────────────────────────────────────────────


def export_csv(
    positions: list,  # list[Position]
    transactions: list | None = None,  # list[Transaction]
) -> Path:
    """生成 UTF-8 BOM CSV 文件，返回文件路径。

    临时文件路径：/tmp/portfolio_export_YYYYMMDD_HHMMSS.csv

    列：代码, 名称, 成本价, 持仓数量, 持仓金额, 浮动盈亏, 盈亏比例,
        首次买入日期, 账户, 备注

    "持仓金额" / "浮动盈亏" / "盈亏比例" 留空 —— 由 UI 层 import 行情后填。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"/tmp/portfolio_export_{ts}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "代码",
        "名称",
        "成本价",
        "持仓数量",
        "持仓金额",
        "浮动盈亏",
        "盈亏比例",
        "首次买入日期",
        "账户",
        "备注",
    ]

    rows: list[list[Any]] = []
    for p in positions:
        rows.append(
            [
                p.ticker,
                p.name,
                round(float(p.cost_basis), 4),
                int(p.quantity),
                "",  # 持仓金额 → UI 行情后填
                "",  # 浮动盈亏 → UI 行情后填
                "",  # 盈亏比例 → UI 行情后填
                p.first_buy_date,
                getattr(p, "account", "default"),
                getattr(p, "notes", ""),
            ]
        )

    # UTF-8 BOM + csv
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return out_path


# ── 2.6 export_transactions_csv ────────────────────────────────────────────


def export_transactions_csv(transactions: list) -> Path:
    """导出交易流水到 UTF-8 BOM CSV。

    列：日期, 代码, 动作, 价格, 数量, 手续费, 账户, 备注
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"/tmp/portfolio_transactions_export_{ts}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "日期",
        "代码",
        "动作",
        "价格",
        "数量",
        "手续费",
        "账户",
        "备注",
    ]

    # 流水本身没有 account 字段（账户引用在 Position 里），
    # 这里保留空白让 UI 层 join Position 补全，或由调用方预先把 account 写到 tx.
    rows: list[list[Any]] = []
    for tx in sorted(transactions, key=lambda t: t.date, reverse=True):
        rows.append(
            [
                tx.date,
                tx.ticker,
                tx.action,
                round(float(tx.price), 4),
                int(tx.quantity),
                round(float(getattr(tx, "fees", 0.0)), 2),
                getattr(tx, "account", ""),
                getattr(tx, "notes", ""),
            ]
        )

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return out_path
