import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// ── Mock data ───────────────────────────────────────────────────────────────
// Mirrors backend.api.portfolio response shapes.  Use one position (600595
// 中孚实业 — the canonical dev fixture) and one transaction so the overview
// tab renders non-empty states.
const { MOCK_POSITIONS, MOCK_TRANSACTIONS, MOCK_ALLOCATION,
        MOCK_GROUP_BY_SECTOR, MOCK_ALERTS, MOCK_ALERT_RULES, MOCK_RISK } = vi.hoisted(() => ({
  MOCK_POSITIONS: {
    positions: [
      {
        position_id: 'pos_001', ticker: '600595', name: '中孚实业',
        cost_basis: 7.193, quantity: 2500,
        first_buy_date: '2026-01-28', last_trade_date: '2026-01-28',
        account: 'default', asset_class: 'stock', notes: '',
        created_at: 1783604358.64, current_price: 6.20,
      },
    ],
    count: 1, prices_source: 'tencent' as const, fetched_at: 1700000000,
  },
  MOCK_TRANSACTIONS: {
    transactions: [
      { tx_id: 'tx_001', position_id: 'pos_001', ticker: '600595',
        date: '2026-01-28', action: 'buy',
        price: 7.193, quantity: 2500, fees: 0, notes: '',
        created_at: 1783604358.64 },
    ],
    count: 1, fetched_at: 1700000000,
  },
  MOCK_ALLOCATION: {
    by_asset_class: { stock: 15500 },
    by_account: { default: 15500 },
    concentration_top5_pct: 1.0,
    total_value: 15500,
    total_cost: 17982.5,
    total_pnl_abs: -2482.5,
    total_pnl_pct: -0.138,
    positions_count: 1,
    fetched_at: 1700000000,
  },
  MOCK_GROUP_BY_SECTOR: {
    by_industry: {},
    by_sector: { '有色金属': 15500 },
    by_asset_class: { stock: 15500 },
    concentration_top5_pct: 1.0,
    total_value: 15500,
    positions_count: 1,
    fetched_at: 1700000000,
  },
  MOCK_ALERTS: {
    alerts: [
      { rule_id: 'alr_001', ticker: '600595', rule_type: 'stop_loss',
        threshold: 10, enabled: true, note: '止损 -10%',
        created_at: 1700000000, last_triggered_at: null,
        last_triggered_price: null, trigger_count: 0 },
    ],
    count: 1, fetched_at: 1700000000,
  },
  MOCK_ALERT_RULES: {
    rules: [
      { type: 'price_above', label: '现价突破',
        description: '现价 ≥ 阈值时触发', example: '现价突破 10.00' },
      { type: 'price_below', label: '现价跌破',
        description: '现价 ≤ 阈值时触发', example: '现价跌破 8.00' },
      { type: 'pct_change', label: '日涨跌幅',
        description: '当日涨跌幅绝对值 ≥ 阈值时触发', example: '日涨跌幅 ≥ 5%' },
      { type: 'pnl_pct', label: '盈亏比例',
        description: '当前盈亏 % ≥ 阈值时触发', example: '盈亏 % ≥ 20%' },
      { type: 'take_profit', label: '止盈',
        description: '现价 ≥ 成本 × (1 + 阈值/100) 时触发', example: '盈利 30% 时止盈' },
      { type: 'stop_loss', label: '止损',
        description: '现价 ≤ 成本 × (1 - 阈值/100) 时触发', example: '亏损 10% 时止损' },
      { type: 'trailing_stop', label: '移动止损',
        description: 'P2 stub', example: '回撤 5% 触发' },
    ],
    count: 7, anti_repeat_window_sec: 300,
  },
  MOCK_RISK: {
    xirr: null, xirr_status: 'no_data',
    sharpe: 0.0, sharpe_status: 'ok',
    max_drawdown: 0.0, max_drawdown_status: 'ok',
    brinson: { portfolio_return: 0.0, benchmark_return: -0.138,
               selection_effect: 0.138, allocation_effect: 0.0, total_effect: 0.138 },
    brinson_status: 'ok',
    sector_attribution: { '有色金属': 15500 },
    positions_count: 1, transactions_count: 1,
    fetched_at: 1700000000,
  },
}));

// ── Mock the portfolio API client ───────────────────────────────────────────
vi.mock('@/api/portfolio', async () => {
  const actual = await vi.importActual<typeof import('@/api/portfolio')>(
    '@/api/portfolio',
  );
  return {
    ...actual,
    listPositions: vi.fn().mockResolvedValue(MOCK_POSITIONS),
    listTransactions: vi.fn().mockResolvedValue(MOCK_TRANSACTIONS),
    getAllocation: vi.fn().mockResolvedValue(MOCK_ALLOCATION),
    groupBySector: vi.fn().mockResolvedValue(MOCK_GROUP_BY_SECTOR),
    listAlerts: vi.fn().mockResolvedValue(MOCK_ALERTS),
    listAlertRules: vi.fn().mockResolvedValue(MOCK_ALERT_RULES),
    getRisk: vi.fn().mockResolvedValue(MOCK_RISK),
    ackAlert: vi.fn().mockResolvedValue({
      ok: true,
      alert: MOCK_ALERTS.alerts[0],
      acked_at: 1700000001,
    }),
    previewImport: vi.fn(),
    commitImport: vi.fn(),
    downloadExport: vi.fn(),
    detectImportFormat: vi.fn(),
    exportUrl: vi.fn().mockReturnValue('/api/portfolio/export?format=positions'),
  };
});

// ── Mock React Query hooks so we control state without a real QueryClient ──
// Mirrors the pattern from BatchPage / HistoryPage tests.
vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query',
  );
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      const k = queryKey[0];
      if (k === 'portfolio-positions') {
        return { data: MOCK_POSITIONS, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-transactions') {
        return { data: MOCK_TRANSACTIONS, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-allocation') {
        return { data: MOCK_ALLOCATION, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-group-by-sector') {
        return { data: MOCK_GROUP_BY_SECTOR, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-alerts' || (Array.isArray(k) && false)) {
        return { data: MOCK_ALERTS, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-alert-rules') {
        return { data: MOCK_ALERT_RULES, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'portfolio-risk') {
        return { data: MOCK_RISK, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      return { data: undefined, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
      reset: vi.fn(),
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
      getQueryData: vi.fn(),
      cancelQueries: vi.fn(),
    }),
  };
});

import PortfolioPage from '@/pages/PortfolioPage';

describe('PortfolioPage', () => {
  it('renders 6 tabs + default overview panel (positions table + summary)', async () => {
    render(<PortfolioPage />);

    // outer page wrapper + title
    expect(screen.getByTestId('portfolio-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /我的仓位/ })).toBeInTheDocument();

    // 6 tab buttons (mirrors Streamlit portfolio_panel.py 6-tab layout)
    expect(screen.getByTestId('portfolio-tab-overview')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-tab-transactions')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-tab-allocation')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-tab-alerts')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-tab-import')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-tab-risk')).toBeInTheDocument();

    // Default tab is overview → summary banner + positions table
    expect(screen.getByTestId('portfolio-panel-overview')).toBeInTheDocument();
    expect(screen.getByTestId('portfolio-overview-summary')).toBeInTheDocument();
    expect(screen.getByTestId('positions-table')).toBeInTheDocument();
    // Mocked 600595 row renders
    expect(screen.getByTestId('positions-row-600595')).toBeInTheDocument();
  });

  it('switches to transactions tab and renders the transactions table', async () => {
    render(<PortfolioPage />);

    screen.getByTestId('portfolio-tab-transactions').click();
    await waitFor(() =>
      expect(screen.getByTestId('portfolio-panel-transactions')).toBeVisible(),
    );
    expect(screen.getByTestId('transactions-table')).toBeInTheDocument();
    // Mocked tx_001 row renders
    expect(screen.getByTestId('transactions-row-tx_001')).toBeInTheDocument();
  });

  it('switches to allocation tab and renders 3 pie charts', async () => {
    render(<PortfolioPage />);

    screen.getByTestId('portfolio-tab-allocation').click();
    await waitFor(() =>
      expect(screen.getByTestId('portfolio-panel-allocation')).toBeVisible(),
    );
    expect(screen.getByTestId('allocation-charts')).toBeInTheDocument();
  });

  it('switches to alerts tab and renders 7-rule catalog + alerts table', async () => {
    render(<PortfolioPage />);

    screen.getByTestId('portfolio-tab-alerts').click();
    await waitFor(() =>
      expect(screen.getByTestId('portfolio-panel-alerts')).toBeVisible(),
    );
    expect(screen.getByTestId('alerts-list')).toBeInTheDocument();
    // 7 rule catalog entries (stop_loss is one of them)
    expect(screen.getByTestId('alert-catalog-stop_loss')).toBeInTheDocument();
    expect(screen.getByTestId('alert-catalog-trailing_stop')).toBeInTheDocument();
  });

  it('switches to risk tab and renders 4 KPI cards', async () => {
    render(<PortfolioPage />);

    screen.getByTestId('portfolio-tab-risk').click();
    await waitFor(() =>
      expect(screen.getByTestId('portfolio-panel-risk')).toBeVisible(),
    );
    expect(screen.getByTestId('risk-charts')).toBeInTheDocument();
    // 4 KPI cards
    expect(screen.getByTestId('risk-kpi-XIRR')).toBeInTheDocument();
    expect(screen.getByTestId('risk-kpi-Sharpe')).toBeInTheDocument();
    expect(screen.getByTestId('risk-kpi-MaxDD')).toBeInTheDocument();
    expect(screen.getByTestId('risk-kpi-Brinson')).toBeInTheDocument();
  });
});