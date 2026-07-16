import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// Mirrors shadcn Badge with custom variants for status pills used by the
// History page (and reusable for logs / chart / analyze later).
//
// Status colours:
//   completed → success (green, matches web history_panel.py bb-status--completed)
//   error     → destructive (red, matches bb-status--error)
//   running   → default (blue, with pulse animation)
//   partial   → warning (yellow, running-with-some-stages)
//   unknown   → outline (grey fallback)
const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-bb-accent focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-bb-accent text-white shadow',
        secondary: 'border-transparent bg-bg-elevated text-text-primary',
        destructive: 'border-transparent bg-bb-up text-white shadow',
        outline: 'text-text-primary border-border-2',
        success: 'border-transparent bg-bb-down text-white shadow',
        warning: 'border-transparent bg-yellow-500 text-black shadow',
      },
    },
    defaultVariants: { variant: 'default' },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />
  )
);
Badge.displayName = 'Badge';

export { badgeVariants };

// ── status helper ────────────────────────────────────────────────────────
// Used by history-row.tsx to map `status` string → Badge variant.
export type HistoryStatus = 'completed' | 'error' | 'running' | 'partial' | 'unknown';

export function statusVariant(status: string | null | undefined): VariantProps<typeof badgeVariants>['variant'] {
  const s = (status ?? '').toLowerCase();
  if (s === 'completed') return 'success';
  if (s === 'error') return 'destructive';
  if (s === 'running') return 'default';
  if (s === 'partial' || s === 'pending') return 'warning';
  return 'outline';
}

export function statusLabel(status: string | null | undefined): string {
  const s = (status ?? '').toLowerCase();
  if (s === 'completed') return '✅ 已完成';
  if (s === 'error') return '❌ 失败';
  if (s === 'running') return '🔄 进行中';
  if (s === 'partial') return '⚠️ 部分';
  if (s === 'pending') return '⏳ 等待';
  return '❔ 未知';
}

// ── signal helper ────────────────────────────────────────────────────────
// Mapping for the 5 signals used by the analyze pipeline. Mirrors
// streamlit _SIGNAL_LABELS.
export type AnalysisSignal =
  | 'Buy'
  | 'Sell'
  | 'Hold'
  | 'Overweight'
  | 'Underweight'
  | string
  | null
  | undefined;

export function signalVariant(
  signal: AnalysisSignal
): VariantProps<typeof badgeVariants>['variant'] {
  const s = (signal ?? '').toString().toUpperCase();
  if (s === 'BUY' || s === 'OVERWEIGHT') return 'success';
  if (s === 'SELL' || s === 'UNDERWEIGHT') return 'destructive';
  if (s === 'HOLD') return 'warning';
  return 'outline';
}

export function signalLabel(signal: AnalysisSignal): string {
  const s = (signal ?? '').toString();
  if (s === 'Buy') return '🟢 买入';
  if (s === 'Sell') return '🔴 卖出';
  if (s === 'Hold') return '🟡 持有';
  if (s === 'Overweight') return '🟢 超配';
  if (s === 'Underweight') return '🔴 低配';
  return s || '-';
}
