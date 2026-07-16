/**
 * AllocationCharts — 配置 tab. Renders 3 pie views + concentration KPIs.
 *
 * Mirrors web/components/portfolio_allocation.py (3 pies: industry, sector,
 * asset class) + the concentration banner at the top.
 *
 * Pie renderer is a hand-rolled CSS conic-gradient (no external chart lib) —
 * keeps the bundle slim and the layout deterministic across tabs.  Both UIs
 * compute the same percentages from the same store, so visual parity is
 * guaranteed when both feeds use the live quote cache.
 */
import * as React from 'react';
import { Loader2, PieChart as PieIcon } from 'lucide-react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import type { GroupBySectorResponse } from '@/api/portfolio';

interface AllocationChartsProps {
  data: GroupBySectorResponse | undefined;
  isLoading?: boolean;
  error?: string | null;
}

// Fixed tailwind palette — P2 (palette change requires parity_visual re-verify).
const PIE_COLORS = [
  '#ff5252', '#ff9800', '#ffeb3b', '#4caf50', '#03a9f4',
  '#3f51b5', '#9c27b0', '#e91e63', '#795548', '#607d8b',
  '#00bcd4', '#8bc34a', '#cddc39', '#ffc107', '#ff5722',
];

interface Slice {
  label: string;
  value: number;
}

function slicesFromMap(m: Record<string, number>): Slice[] {
  return Object.entries(m)
    .map(([label, value]) => ({ label, value: Number(value) || 0 }))
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value);
}

function conicGradient(slices: Slice[]): string {
  if (!slices.length) return 'conic-gradient(#2a2a2a 0 360deg)';
  const total = slices.reduce((s, x) => s + x.value, 0);
  if (total <= 0) return 'conic-gradient(#2a2a2a 0 360deg)';
  let acc = 0;
  const stops: string[] = [];
  for (let i = 0; i < slices.length; i++) {
    const start = (acc / total) * 360;
    acc += slices[i].value;
    const end = (acc / total) * 360;
    const color = PIE_COLORS[i % PIE_COLORS.length];
    stops.push(`${color} ${start}deg ${end}deg`);
  }
  return `conic-gradient(${stops.join(', ')})`;
}

function PieCard({ title, slices, totalHint }: { title: string; slices: Slice[]; totalHint?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <PieIcon className="h-4 w-4" /> {title}
        </CardTitle>
        {totalHint && <CardDescription>{totalHint}</CardDescription>}
      </CardHeader>
      <CardContent>
        {slices.length === 0 ? (
          <div className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-4 text-center text-sm text-text-tertiary">
            暂无数据
          </div>
        ) : (
          <div className="flex items-center gap-4">
            <div
              className="h-32 w-32 rounded-full border border-border-1"
              style={{ background: conicGradient(slices) }}
              data-testid={`pie-${title}`}
            />
            <ul className="flex-1 space-y-1 text-xs">
              {slices.map((s, i) => (
                <li key={s.label} className="flex items-center gap-2">
                  <span
                    className="inline-block h-3 w-3 rounded-sm"
                    style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                  />
                  <span className="flex-1 truncate" title={s.label}>{s.label}</span>
                  <span className="font-mono text-text-secondary">
                    ¥{s.value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function AllocationCharts({ data, isLoading, error }: AllocationChartsProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="allocation-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载配置…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="allocation-error"
      >
        加载配置失败: {error}
      </div>
    );
  }
  if (!data) {
    return null;
  }
  const industry = slicesFromMap(data.by_industry);
  const sector = slicesFromMap(data.by_sector);
  const asset = slicesFromMap(data.by_asset_class);
  const totalValue = data.total_value || 0;
  return (
    <div className="space-y-4" data-testid="allocation-charts">
      {/* concentration KPI banner */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div>
            <div className="text-xs uppercase text-text-tertiary">持仓集中度 (前 5)</div>
            <div className="text-2xl font-bold font-mono text-bb-accent-bright">
              {(data.concentration_top5_pct * 100).toFixed(2)}%
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-text-tertiary">总市值</div>
            <div className="text-2xl font-bold font-mono">
              ¥{totalValue.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-text-tertiary">持仓数</div>
            <div className="text-2xl font-bold font-mono">{data.positions_count}</div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <PieCard
          title="按行业"
          slices={industry}
          totalHint="industry 分组 (MVP: 当前由 ticker 名称启发)"
        />
        <PieCard
          title="按板块"
          slices={sector}
          totalHint="由 portfolio_calc.group_by_sector 计算"
        />
        <PieCard
          title="按资产类别"
          slices={asset}
          totalHint="stock / etf / bond …"
        />
      </div>
    </div>
  );
}

export default AllocationCharts;