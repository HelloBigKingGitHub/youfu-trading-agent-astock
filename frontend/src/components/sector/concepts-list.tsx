/**
 * ConceptsList — concept block cards with aggregated stock count + avg ratio.
 *
 * Mirrors `web/components/sector_panel.py::_render_concept_blocks` — each
 * card shows block name + stock count + avg_ratio + a row of top codes.
 *
 * Sorted by stock_count desc (denser blocks first), matching the Streamlit
 * panel's `sort_blocks` rule.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ConceptSummary } from '@/api/sector';

interface ConceptsListProps {
  concepts: ConceptSummary[];
  isLoading?: boolean;
  error?: string | null;
}

function ratioColor(ratio: number): string {
  if (ratio >= 3) return 'text-bb-up font-bold';
  if (ratio >= 0) return 'text-bb-up font-semibold';
  if (ratio >= -3) return 'text-bb-down font-semibold';
  return 'text-bb-down font-bold';
}

export const ConceptsList = React.memo(function ConceptsList({
  concepts,
  isLoading,
  error,
}: ConceptsListProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="concepts-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载概念板块…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="concepts-error"
      >
        加载概念板块失败: {error}
      </div>
    );
  }

  if (!concepts.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="concepts-empty"
      >
        暂无概念板块数据
      </div>
    );
  }

  const sorted = [...concepts].sort((a, b) => {
    if (b.stock_count !== a.stock_count) return b.stock_count - a.stock_count;
    return a.name.localeCompare(b.name);
  });

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
      data-testid="concepts-list"
      aria-label="概念板块列表"
    >
      {sorted.map((c) => (
        <div
          key={c.name}
          data-testid={`concept-card-${c.name}`}
          className={cn(
            'rounded-md border border-border-1 bg-bg-elevated p-4',
            'hover:border-bb-accent/60 transition-colors'
          )}
        >
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-text-primary truncate" title={c.name}>
              {c.name}
            </h3>
            <span className={cn('text-sm font-mono tabular-nums shrink-0', ratioColor(c.avg_ratio))}>
              {c.avg_ratio >= 0 ? '+' : ''}
              {c.avg_ratio}%
            </span>
          </div>
          <div className="mt-1 flex items-center gap-3 text-[11px] text-text-secondary">
            <span className="font-mono">{c.stock_count} 只成分股</span>
          </div>
          {c.codes && c.codes.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.codes.slice(0, 6).map((code) => (
                <span
                  key={code}
                  className="font-mono text-[11px] px-1.5 py-0.5 rounded
                             bg-bg-surface border border-border-1 text-text-secondary"
                >
                  {code}
                </span>
              ))}
              {c.codes.length > 6 && (
                <span className="text-[10px] text-text-tertiary">
                  +{c.codes.length - 6}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
});