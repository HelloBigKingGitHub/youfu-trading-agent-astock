/**
 * Portfolio API client — mirrors backend/api/portfolio.py 1:1.
 *
 * Endpoints (12 total, mirroring Streamlit web/components/portfolio_panel.py):
 *   GET  /api/portfolio/positions                       → list positions + current price
 *   GET  /api/portfolio/transactions                    → list transactions (newest first)
 *   GET  /api/portfolio/positions/group_by_sector       → 3 pie data (industry/sector/asset_class) + top5 concentration
 *   GET  /api/portfolio/allocation                      → asset class + concentration summary
 *   GET  /api/portfolio/alerts                          → list alert rules
 *   GET  /api/portfolio/alerts/rules                    → 7 rule type catalog
 *   POST /api/portfolio/alerts/ack/{alert_id}           → ack an alert (idempotent)
 *   GET  /api/portfolio/risk                            → XIRR / Sharpe / MaxDD / Brinson + 板块归因
 *   GET  /api/portfolio/import/detect?file_path=        → detect 4 CSV formats
 *   POST /api/portfolio/import/preview                  → preview CSV (multipart upload)
 *   POST /api/portfolio/import/commit                   → commit import (multipart + format)
 *   GET  /api/portfolio/export?format=                  → export CSV (UTF-8 BOM)
 *
 * Both UIs (Streamlit portfolio_panel.py + this React PortfolioPage) ultimately
 * call the same backend core (backend.core.portfolio_store / portfolio_calc /
 * portfolio_alerts / portfolio_import). No business logic here — pure HTTP
 * mirror of the FastAPI surface, exactly like frontend/src/api/{settings,
 * history, logs, chart, sector, batch}.ts.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

// ── shared types ────────────────────────────────────────────────────────────

export interface Position {
  position_id: string;
  ticker: string;
  name: string;
  cost_basis: number;
  quantity: number;
  first_buy_date: string;
  last_trade_date: string;
  account: string;
  asset_class: string;
  notes: string;
  created_at: number;
  /** Injected by the backend /positions endpoint from the live quote cache. */
  current_price: number;
}

export interface PositionsResponse {
  positions: Position[];
  count: number;
  prices_source: 'tencent' | 'fallback-cost';
  fetched_at: number;
}

export interface Transaction {
  tx_id: string;
  position_id: string;
  ticker: string;
  date: string;        // YYYY-MM-DD
  action: 'buy' | 'sell' | string;
  price: number;
  quantity: number;
  fees: number;
  notes: string;
  created_at: number;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  count: number;
  fetched_at: number;
}

export interface AllocationResponse {
  by_asset_class: Record<string, number>;
  by_account: Record<string, number>;
  concentration_top5_pct: number;
  total_value: number;
  total_cost: number;
  total_pnl_abs: number;
  total_pnl_pct: number;
  positions_count: number;
  fetched_at: number;
}

export interface GroupBySectorResponse {
  by_industry: Record<string, number>;
  by_sector: Record<string, number>;
  by_asset_class: Record<string, number>;
  concentration_top5_pct: number;
  total_value: number;
  positions_count: number;
  fetched_at: number;
}

export interface AlertRule {
  rule_id: string;
  ticker: string;
  rule_type: string;
  threshold: number;
  enabled: boolean;
  note: string;
  created_at: number;
  last_triggered_at: number | null;
  last_triggered_price: number | null;
  trigger_count: number;
}

export interface AlertsResponse {
  alerts: AlertRule[];
  count: number;
  fetched_at: number;
}

export interface AlertRuleCatalogEntry {
  type: string;
  label: string;
  description: string;
  example: string;
}

export interface AlertRulesCatalogResponse {
  rules: AlertRuleCatalogEntry[];
  count: number;
  anti_repeat_window_sec: number;
}

export interface AckAlertResponse {
  ok: boolean;
  alert: AlertRule;
  acked_at: number;
}

export interface RiskResponse {
  xirr: number | null;
  xirr_status: string;
  sharpe: number | null;
  sharpe_status: string;
  max_drawdown: number | null;
  max_drawdown_status: string;
  brinson: Record<string, number>;
  brinson_status: string;
  sector_attribution: Record<string, number>;
  positions_count: number;
  transactions_count: number;
  fetched_at: number;
}

export interface DetectImportResponse {
  file_path: string;
  format: 'eastmoney' | 'ths' | 'xueqiu' | 'generic' | 'unknown' | null;
  detected_at: number;
}

export interface PreviewImportResponse {
  format: string;
  total_rows: number;
  preview: Array<Record<string, unknown>>;
  preview_hash: string;
  detected_at: number;
}

export interface CommitImportResponse {
  ok: boolean;
  format: string;
  inserted: number;
  skipped: number;
  errors: unknown[];
  committed_at: number;
}

// ── GET /api/portfolio/positions ────────────────────────────────────────────

export async function listPositions(
  account: string = '',
  assetClass: string = '',
): Promise<PositionsResponse> {
  const qs = new URLSearchParams();
  if (account) qs.set('account', account);
  if (assetClass) qs.set('asset_class', assetClass);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(_url(`/api/portfolio/positions${suffix}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/positions ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as PositionsResponse;
}

// ── GET /api/portfolio/transactions ─────────────────────────────────────────

export async function listTransactions(
  ticker: string = '',
  since: string = '',
): Promise<TransactionsResponse> {
  const qs = new URLSearchParams();
  if (ticker) qs.set('ticker', ticker);
  if (since) qs.set('since', since);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(_url(`/api/portfolio/transactions${suffix}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/transactions ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as TransactionsResponse;
}

// ── GET /api/portfolio/allocation ───────────────────────────────────────────

export async function getAllocation(): Promise<AllocationResponse> {
  const res = await fetch(_url('/api/portfolio/allocation'), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/allocation ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AllocationResponse;
}

// ── GET /api/portfolio/positions/group_by_sector ────────────────────────────

export async function groupBySector(): Promise<GroupBySectorResponse> {
  const res = await fetch(_url('/api/portfolio/positions/group_by_sector'), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/positions/group_by_sector ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as GroupBySectorResponse;
}

// ── GET /api/portfolio/alerts ───────────────────────────────────────────────

export async function listAlerts(
  ticker: string = '',
  enabledOnly: boolean = false,
): Promise<AlertsResponse> {
  const qs = new URLSearchParams();
  if (ticker) qs.set('ticker', ticker);
  qs.set('enabled_only', String(enabledOnly));
  const res = await fetch(_url(`/api/portfolio/alerts?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/alerts ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AlertsResponse;
}

// ── GET /api/portfolio/alerts/rules ─────────────────────────────────────────

export async function listAlertRules(): Promise<AlertRulesCatalogResponse> {
  const res = await fetch(_url('/api/portfolio/alerts/rules'), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/alerts/rules ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AlertRulesCatalogResponse;
}

// ── POST /api/portfolio/alerts/ack/{alert_id} ───────────────────────────────

export async function ackAlert(alertId: string): Promise<AckAlertResponse> {
  const res = await fetch(
    _url(`/api/portfolio/alerts/ack/${encodeURIComponent(alertId)}`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/portfolio/alerts/ack/${alertId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AckAlertResponse;
}

// ── GET /api/portfolio/risk ─────────────────────────────────────────────────

export async function getRisk(): Promise<RiskResponse> {
  const res = await fetch(_url('/api/portfolio/risk'), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/risk ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as RiskResponse;
}

// ── GET /api/portfolio/import/detect ────────────────────────────────────────

export async function detectImportFormat(
  filePath: string,
): Promise<DetectImportResponse> {
  const qs = new URLSearchParams({ file_path: filePath });
  const res = await fetch(
    _url(`/api/portfolio/import/detect?${qs.toString()}`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/portfolio/import/detect ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as DetectImportResponse;
}

// ── POST /api/portfolio/import/preview ──────────────────────────────────────

export async function previewImport(file: File): Promise<PreviewImportResponse> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(_url('/api/portfolio/import/preview'), {
    method: 'POST',
    body: form,
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`POST /api/portfolio/import/preview ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as PreviewImportResponse;
}

// ── POST /api/portfolio/import/commit ───────────────────────────────────────

export async function commitImport(
  file: File,
  format: 'eastmoney' | 'ths' | 'xueqiu' | 'generic',
): Promise<CommitImportResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('format', format);
  const res = await fetch(_url('/api/portfolio/import/commit'), {
    method: 'POST',
    body: form,
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`POST /api/portfolio/import/commit ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as CommitImportResponse;
}

// ── GET /api/portfolio/export ───────────────────────────────────────────────

export function exportUrl(format: 'positions' | 'transactions' = 'positions'): string {
  return _url(`/api/portfolio/export?format=${encodeURIComponent(format)}`);
}

export async function downloadExport(
  format: 'positions' | 'transactions' = 'positions',
): Promise<void> {
  // The export endpoint returns a binary body (UTF-8 BOM + CSV). Browsers
  // navigate to the URL directly to trigger download with the correct
  // Content-Disposition filename. We expose both: the URL builder for `<a
  // href>` and an async helper for callers that want a Promise.
  if (typeof window === 'undefined') return;
  window.location.assign(exportUrl(format));
}