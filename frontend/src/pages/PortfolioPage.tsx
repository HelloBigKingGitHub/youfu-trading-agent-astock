import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Briefcase, ClipboardList, LayoutDashboard, PieChart as PieIcon,
  ShieldAlert, TrendingUp,
} from 'lucide-react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { cn } from '@/lib/utils';
import {
  getAllocation,
  getRisk,
  groupBySector,
  listAlertRules,
  listAlerts,
  listPositions,
  listTransactions,
} from '@/api/portfolio';
import { PositionsTable } from '@/components/portfolio/positions-table';
import { TransactionsTable } from '@/components/portfolio/transactions-table';
import { AllocationCharts } from '@/components/portfolio/allocation-charts';
import { AlertsList } from '@/components/portfolio/alerts-list';
import { ImportExport } from '@/components/portfolio/import-export';
import { RiskCharts } from '@/components/portfolio/risk-charts';

type TabKey = 'overview' | 'transactions' | 'allocation' | 'alerts' | 'import' | 'risk';

interface TabDef {
  key: TabKey;
  label: string;
  testid: string;
  icon: React.ComponentType<{ className?: string }>;
  emoji: string;
}

const TABS: TabDef[] = [
  { key: 'overview',     label: '总览',     testid: 'portfolio-tab-overview',     icon: LayoutDashboard, emoji: '📊' },
  { key: 'transactions', label: '流水',     testid: 'portfolio-tab-transactions', icon: ClipboardList,   emoji: '📜' },
  { key: 'allocation',   label: '配置',     testid: 'portfolio-tab-allocation',   icon: PieIcon,         emoji: '🎯' },
  { key: 'alerts',       label: '预警',     testid: 'portfolio-tab-alerts',       icon: ShieldAlert,     emoji: '🔔' },
  { key: 'import',       label: '导入导出', testid: 'portfolio-tab-import',       icon: Briefcase,       emoji: '📥' },
  { key: 'risk',         label: '收益风险', testid: 'portfolio-tab-risk',         icon: TrendingUp,      emoji: '📈' },
];

const DEFAULT_TAB: TabKey = 'overview';

function TabStrip({
  active,
  onSelect,
}: {
  active: TabKey;
  onSelect: (k: TabKey) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="仓位视图"
      className="flex flex-wrap gap-2 border-b border-border-1 pb-2"
      data-testid="portfolio-tabs"
    >
      {TABS.map((t) => {
        const Icon = t.icon;
        const isActive = active === t.key;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={`portfolio-tabpanel-${t.key}`}
            data-testid={t.testid}
            onClick={() => onSelect(t.key)}
            className={cn(
              'flex items-center px-3 py-1.5 text-sm rounded-t-md transition-colors',
              isActive
                ? 'bg-bb-accent-glow text-bb-accent font-semibold ring-1 ring-bb-accent/40 ' +
                  'shadow-[inset_0_-3px_0_0_var(--bb-accent-bright)]'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated',
            )}
          >
            <span className="mr-1.5" aria-hidden>{t.emoji}</span>
            <Icon className="mr-2 h-4 w-4" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * PortfolioPage — React counterpart of web/components/portfolio_panel.py.
 *
 * Layout: single Card with an inline tab strip + 6 tab panels.  Both UIs
 * consume the same backend (portfolio_store / portfolio_calc /
 * portfolio_alerts / portfolio_import), so every panel is a 1:1 data
 * mirror of the Streamlit version.
 *
 * React Query is used for cache + polling; the Overview and Allocation tabs
 * also share the positions query (React Query dedupe keeps it cheap).
 */
export function PortfolioPage() {
  const [activeTab, setActiveTab] = React.useState<TabKey>(DEFAULT_TAB);

  // ── shared queries ────────────────────────────────────────────────────────
  const positionsQuery = useQuery({
    queryKey: ['portfolio-positions'],
    queryFn: () => listPositions(),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const transactionsQuery = useQuery({
    queryKey: ['portfolio-transactions'],
    queryFn: () => listTransactions(),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const allocationQuery = useQuery({
    queryKey: ['portfolio-allocation'],
    queryFn: () => getAllocation(),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const groupBySectorQuery = useQuery({
    queryKey: ['portfolio-group-by-sector'],
    queryFn: () => groupBySector(),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const alertsQuery = useQuery({
    queryKey: ['portfolio-alerts', '', false],
    queryFn: () => listAlerts('', false),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  const alertRulesQuery = useQuery({
    queryKey: ['portfolio-alert-rules'],
    queryFn: () => listAlertRules(),
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });

  const riskQuery = useQuery({
    queryKey: ['portfolio-risk'],
    queryFn: () => getRisk(),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  function errorString(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }

  return (
    <div
      data-testid="portfolio-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Briefcase className="h-6 w-6" />
            <h1 className="text-inherit font-inherit" data-testid="portfolio-title">💼 我的仓位</h1>
          </CardTitle>
          <CardDescription>
            个人持仓跟踪 · 业绩归因 · 预警 (XIRR / Sharpe / MaxDD / Brinson / 板块归因)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <TabStrip active={activeTab} onSelect={setActiveTab} />

          {/* ── Overview tab ───────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-overview"
            aria-labelledby="portfolio-tab-overview"
            data-testid="portfolio-panel-overview"
            className={cn('space-y-4 pt-2', activeTab !== 'overview' && 'hidden')}
          >
            {allocationQuery.data && (
              <div
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border-1 bg-bg-elevated/40 px-4 py-3"
                data-testid="portfolio-overview-summary"
              >
                <div className="text-sm">
                  总市值{' '}
                  <strong className="font-mono text-bb-accent-bright">
                    ¥{allocationQuery.data.total_value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}
                  </strong>
                  {' · '}
                  盈亏{' '}
                  <strong className={`font-mono ${allocationQuery.data.total_pnl_abs >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {allocationQuery.data.total_pnl_abs >= 0 ? '+' : ''}
                    ¥{allocationQuery.data.total_pnl_abs.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}
                  </strong>
                  {' · '}
                  持仓 <strong className="font-mono">{allocationQuery.data.positions_count}</strong> 只
                </div>
                <div className="text-xs text-text-tertiary">
                  前 5 集中度{' '}
                  <span className="font-mono text-text-primary">
                    {(allocationQuery.data.concentration_top5_pct * 100).toFixed(2)}%
                  </span>
                </div>
              </div>
            )}
            <PositionsTable
              positions={positionsQuery.data?.positions ?? []}
              isLoading={positionsQuery.isLoading}
              error={positionsQuery.error ? errorString(positionsQuery.error) : null}
            />
            <p className="text-xs text-text-tertiary">
              共享 <code className="font-mono">backend.core.portfolio_store</code> 单例 ·
              与 Streamlit <code className="font-mono">web/components/portfolio_overview.py</code> 1:1
            </p>
          </div>

          {/* ── Transactions tab ───────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-transactions"
            aria-labelledby="portfolio-tab-transactions"
            data-testid="portfolio-panel-transactions"
            className={cn('space-y-4 pt-2', activeTab !== 'transactions' && 'hidden')}
          >
            <TransactionsTable
              transactions={transactionsQuery.data?.transactions ?? []}
              isLoading={transactionsQuery.isLoading}
              error={transactionsQuery.error ? errorString(transactionsQuery.error) : null}
            />
            <p className="text-xs text-text-tertiary">
              共 <strong className="font-mono">{transactionsQuery.data?.count ?? 0}</strong> 条流水 · 按日期倒序
            </p>
          </div>

          {/* ── Allocation tab ─────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-allocation"
            aria-labelledby="portfolio-tab-allocation"
            data-testid="portfolio-panel-allocation"
            className={cn('space-y-4 pt-2', activeTab !== 'allocation' && 'hidden')}
          >
            <AllocationCharts
              data={groupBySectorQuery.data}
              isLoading={groupBySectorQuery.isLoading}
              error={groupBySectorQuery.error ? errorString(groupBySectorQuery.error) : null}
            />
          </div>

          {/* ── Alerts tab ─────────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-alerts"
            aria-labelledby="portfolio-tab-alerts"
            data-testid="portfolio-panel-alerts"
            className={cn('space-y-4 pt-2', activeTab !== 'alerts' && 'hidden')}
          >
            <AlertsList
              rules={alertsQuery.data?.alerts ?? []}
              catalog={alertRulesQuery.data?.rules ?? []}
              isLoading={alertsQuery.isLoading || alertRulesQuery.isLoading}
              error={alertsQuery.error ? errorString(alertsQuery.error) : null}
            />
          </div>

          {/* ── Import / Export tab ─────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-import"
            aria-labelledby="portfolio-tab-import"
            data-testid="portfolio-panel-import"
            className={cn('space-y-4 pt-2', activeTab !== 'import' && 'hidden')}
          >
            <ImportExport />
          </div>

          {/* ── Risk tab ───────────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="portfolio-tabpanel-risk"
            aria-labelledby="portfolio-tab-risk"
            data-testid="portfolio-panel-risk"
            className={cn('space-y-4 pt-2', activeTab !== 'risk' && 'hidden')}
          >
            <RiskCharts
              data={riskQuery.data}
              isLoading={riskQuery.isLoading}
              error={riskQuery.error ? errorString(riskQuery.error) : null}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default PortfolioPage;