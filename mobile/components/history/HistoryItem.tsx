import Link from "next/link";
import type { HistoryItem } from "@/lib/types";
import { Badge } from "../ui/Badge";

interface HistoryItemProps {
  item: HistoryItem;
}

export function HistoryItem({ item }: HistoryItemProps) {
  const SIGNAL_MAP: Record<string, "buy" | "sell" | "hold" | "overweight" | "underweight" | "default"> = {
    Buy: "buy",
    Sell: "sell",
    Hold: "hold",
    Overweight: "overweight",
    Underweight: "underweight",
  };
  const signalVariant = item.signal ? (SIGNAL_MAP[item.signal] ?? "default") : "default";

  return (
    <Link
      href={`/report/${item.analysis_id}`}
      className="block bg-[var(--bg-card)] rounded-xl p-4 border border-[var(--border-subtle)] hover:border-[var(--accent)]/30 transition-colors"
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-[var(--text-primary)]">{item.ticker}</span>
            {item.signal && (
              <Badge variant={signalVariant}>{item.signal}</Badge>
            )}
          </div>
          <div className="text-xs text-[var(--text-muted)]">
            {item.trade_date} · {item.elapsed ? `${item.elapsed.toFixed(1)}s` : ""}
          </div>
        </div>
        <div className="text-[var(--text-muted)] text-sm ml-2">›</div>
      </div>
    </Link>
  );
}