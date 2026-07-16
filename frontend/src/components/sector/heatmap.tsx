/**
 * Heatmap — concept block grid colored by avg_ratio (vs CSI 300).
 *
 * Mirrors `web/components/sector_panel.py::_render_concept_heatmap`.  We use a
 * simple CSS grid (no treemap layout) because:
 *   - block counts are bounded (≤ 86 in real data; usually 30-50 active blocks)
 *   - a grid is way more legible than a squashed treemap at 1600px wide
 *   - hover-tooltip carries the same data (block name + stock count + avg ratio)
 *
 * Color scale:
 *   avg_ratio >= +3%  → bright red (strong rally)
 *   avg_ratio >= 0    → light red
 *   avg_ratio >= -3%  → light green
 *   avg_ratio <  -3%  → bright green (deep sell-off, A-share inverted colors)
 *
 * Note: A-share convention is **red = up, green = down**, matching the
 * chart_panel + history_panel K-line conventions.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ConceptStock } from '@/api/sector';

export interface HeatmapBlockSummary {
  name: string;
  stock_count: number;
  avg_ratio: number;
  stocks: ConceptStock[];
}

interface HeatmapProps {
  blocks: Record<string, ConceptStock[]>;
  isLoading?: boolean;
  error?: string | null;
}

function ratioColor(ratio: number): string {
  if (ratio >= 3) return 'bg-red-600/85 text-white border-red-700';
  if (ratio >= 1) return 'bg-red-500/70 text-white border-red-600';
  if (ratio >= 0) return 'bg-red-400/40 text-text-primary border-red-400/50';
  if (ratio >= -1) return 'bg-green-400/40 text-text-primary border-green-400/50';
  if (ratio >= -3) return 'bg-green-500/70 text-white border-green-600';
  return 'bg-green-600/85 text-white border-green-700';
}

function computeBlockSummary(
  name: string,
  stocks: ConceptStock[],
): HeatmapBlockSummary {
  let sum = 0;
  let n = 0;
  for (const s of stocks) {
    const raw = (s as { ratio?: string | number }).ratio;
    if (typeof raw === 'number') {
      sum += raw;
      n += 1;
    } else if (typeof raw === 'string') {
      const m = raw.match(/([+-]?[\d.]+)/);
      if (m) {
        sum += parseFloat(m[1]);
        n += 1;
      }
    }
  }
  const avg_ratio = n > 0 ? Math.round((sum / n) * 100) / 100 : 0;
  return { name, stock_count: stocks.length, avg_ratio, stocks };
}

export const Heatmap = React.memo(function Heatmap({
  blocks,
  isLoading,
  error,
}: HeatmapProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="heatmap-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载板块热力图…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="heatmap-error"
      >
        加载热力图失败: {error}
      </div>
    );
  }

  const summaries = Object.entries(blocks)
    .map(([name, stocks]) => computeBlockSummary(name, stocks))
    .sort((a, b) => {
      if (b.stock_count !== a.stock_count) return b.stock_count - a.stock_count;
      return a.name.localeCompare(b.name);
    });

  if (!summaries.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="heatmap-empty"
      >
        暂无板块数据
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2"
      data-testid="heatmap-grid"
      aria-label="板块热力图"
    >
      {summaries.map((b) => (
        <div
          key={b.name}
          data-testid={`heatmap-block-${b.name}`}
          className={cn(
            'group relative rounded-md border p-3 cursor-default transition-transform',
            'hover:scale-[1.03] hover:shadow-lg',
            ratioColor(b.avg_ratio),
          )}
          title={`${b.name} · ${b.stock_count} 只股票 · 平均 ${b.avg_ratio >= 0 ? '+' : ''}${b.avg_ratio}%`}
        >
          <div className="text-sm font-semibold truncate" title={b.name}>
            {b.name}
          </div>
          <div className="mt-1 flex items-baseline justify-between gap-2 text-xs">
            <span className="font-mono opacity-90">{b.stock_count} 只</span>
            <span className="font-mono font-semibold">
              {b.avg_ratio >= 0 ? '+' : ''}
              {b.avg_ratio}%
            </span>
          </div>
          {/* codes overlay (top-3) on hover */}
          <div className="pointer-events-none absolute inset-0 hidden group-hover:flex
                          items-end justify-start p-2 rounded-md
                          bg-black/85 text-[10px] text-white font-mono leading-tight">
            <div className="space-y-0.5">
              <div className="text-text-secondary text-[9px] uppercase tracking-wider">
                {b.name} · top 3
              </div>
              {b.stocks.slice(0, 3).map((s) => (
                <div key={s.code}>{s.code} {s.name}</div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
});