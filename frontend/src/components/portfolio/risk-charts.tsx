/**
 * RiskCharts — 收益风险 tab. Renders 4 KPI cards (XIRR / Sharpe / MaxDD /
 * Brinson) + 板块归因 table.
 *
 * Mirrors web/components/portfolio_risk.py.  Both UIs call the same backend
 * /api/portfolio/risk composite, so the 4 numbers are byte-identical between
 * Streamlit and React.
 *
 * Color convention:
 *   - positive metric (XIRR, Sharpe, Brinson total_effect) → red (A-share: up)
 *   - negative metric (MaxDD) → green if losses deep (down), red if recovery
 */
import * as React from 'react';
import { Loader2, TrendingDown, TrendingUp, BarChart3, Activity } from 'lucide-react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { RiskResponse } from '@/api/portfolio';

interface RiskChartsProps {
  data: RiskResponse | undefined;
  isLoading?: boolean;
  error?: string | null;
}

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(digits)}%`;
}

function fmtNum(n: number | null | undefined, digits = 4): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  return n.toFixed(digits);
}

interface KpiProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  value: string;
  status: string;
  hint?: string;
  positive?: boolean;
}

function Kpi({ icon: Icon, title, value, status, hint, positive }: KpiProps) {
  const color =
    positive === undefined
      ? 'text-text-primary'
      : positive
        ? 'text-red-400'      // A-share: red = up
        : 'text-green-400';   // green = down
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-text-secondary">
          <Icon className="h-4 w-4" /> {title}
        </CardTitle>
        {hint && <CardDescription>{hint}</CardDescription>}
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold font-mono ${color}`} data-testid={`risk-kpi-${title}`}>
          {value}
        </div>
        <div className="mt-1 text-[11px] uppercase tracking-wider text-text-tertiary font-mono">
          {status}
        </div>
      </CardContent>
    </Card>
  );
}

export function RiskCharts({ data, isLoading, error }: RiskChartsProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="risk-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载业绩归因…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="risk-error"
      >
        加载业绩归因失败: {error}
      </div>
    );
  }
  if (!data) return null;

  const xirrPositive = data.xirr !== null && data.xirr > 0;
  const sharpePositive = data.sharpe !== null && data.sharpe > 0;
  // MaxDD is negative by convention; "good" MaxDD is *less* negative (closer to 0)
  const maxDdPositive = data.max_drawdown !== null && data.max_drawdown > -0.1;
  const brinsonTotal = data.brinson?.total_effect;
  const brinsonPositive = brinsonTotal !== undefined && brinsonTotal > 0;

  const sectorRows = Object.entries(data.sector_attribution).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-4" data-testid="risk-charts">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi
          icon={TrendingUp}
          title="XIRR"
          value={fmtPct(data.xirr)}
          status={data.xirr_status}
          hint="年化收益率"
          positive={xirrPositive}
        />
        <Kpi
          icon={Activity}
          title="Sharpe"
          value={fmtNum(data.sharpe, 3)}
          status={data.sharpe_status}
          hint="rf=2.5%"
          positive={sharpePositive}
        />
        <Kpi
          icon={TrendingDown}
          title="MaxDD"
          value={fmtPct(data.max_drawdown)}
          status={data.max_drawdown_status}
          hint="最大回撤 (负值)"
          positive={maxDdPositive}
        />
        <Kpi
          icon={BarChart3}
          title="Brinson"
          value={fmtPct(brinsonTotal)}
          status={data.brinson_status}
          hint="总归因效应"
          positive={brinsonPositive}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">板块归因</CardTitle>
          <CardDescription>
            按持仓所属板块汇总当前市值 · 共 {sectorRows.length} 个板块
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sectorRows.length === 0 ? (
            <div
              className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-4 text-center text-sm text-text-tertiary"
              data-testid="risk-sectors-empty"
            >
              暂无板块归因数据
            </div>
          ) : (
            <Table data-testid="risk-sectors-table">
              <TableHeader>
                <TableRow>
                  <TableHead>板块</TableHead>
                  <TableHead className="text-right">市值 (¥)</TableHead>
                  <TableHead className="text-right">占比</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(() => {
                  const total = sectorRows.reduce((s, [, v]) => s + v, 0);
                  return sectorRows.map(([sector, value]) => (
                    <TableRow key={sector} data-testid={`risk-sector-row-${sector}`}>
                      <TableCell>{sector}</TableCell>
                      <TableCell className="text-right font-mono">
                        ¥{value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}
                      </TableCell>
                      <TableCell className="text-right font-mono text-text-secondary">
                        {total > 0 ? `${((value / total) * 100).toFixed(2)}%` : '—'}
                      </TableCell>
                    </TableRow>
                  ));
                })()}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default RiskCharts;