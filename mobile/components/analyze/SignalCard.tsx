import { PIPELINE_STAGES, SIGNAL_COLORS } from "@/lib/constants";
import type { ProgressResponse } from "@/lib/types";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";

interface SignalCardProps {
  signal: string | null;
  ticker: string;
  tradeDate: string;
  elapsed?: number;
  variant?: "header" | "compact";
}

const SIGNAL_BADGE_VARIANTS: Record<string, "buy" | "sell" | "hold" | "overweight" | "underweight" | undefined> = {
  Buy: "buy",
  Sell: "sell",
  Hold: "hold",
  Overweight: "overweight",
  Underweight: "underweight",
};

export function SignalCard({ signal, ticker, tradeDate, elapsed, variant = "header" }: SignalCardProps) {
  if (!signal) return null;

  const colors = SIGNAL_COLORS[signal];
  if (!colors) return null;

  if (variant === "compact") {
    return (
      <Badge variant={SIGNAL_BADGE_VARIANTS[signal] ?? "default"}>
        {signal}
      </Badge>
    );
  }

  return (
    <Card
      className="relative overflow-hidden"
      style={{
        background: `linear-gradient(135deg, ${colors.bg} 0%, transparent 60%)`,
      }}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-[var(--text-muted)] mb-1">{ticker} · {tradeDate}</div>
          <div
            className="text-5xl font-bold tracking-tight"
            style={{ color: colors.color }}
          >
            {signal}
          </div>
        </div>
        <div className="text-right">
          <div
            className="text-4xl font-bold"
            style={{ color: colors.color }}
          >
            {signal === "Buy" ? "▲" : signal === "Sell" ? "▼" : signal === "Hold" ? "●" : "◆"}
          </div>
          {elapsed !== undefined && (
            <div className="text-xs text-[var(--text-muted)] mt-2">
              {elapsed.toFixed(1)}s
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}