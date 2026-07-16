/**
 * History API client — mirrors backend/api/history.py 1:1.
 *
 * Endpoints:
 *   GET    /api/history              list with filters
 *   GET    /api/history/{id}         detail (full dict incl. results_path)
 *   DELETE /api/history/{id}         delete (idempotent)
 *   POST   /api/history/{id}/rerun   mark for re-analysis (delete + return intent)
 *   GET    /api/history/{id}/report  full report (full_states_log_*.json)
 *
 * Both UIs (Streamlit + React) ultimately read from the SAME store
 * (backend/core/history_store.py), so payloads from list/detail are the
 * canonical Pydantic mirror and do NOT need massaging in the React layer.
 *
 * React Query is used at the call site; this module is the *transport* layer
 * — keep it dumb (no caching, no transformation).
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

// ── list ──────────────────────────────────────────────────────────────────
export interface ListHistoryParams {
  status?: string;
  ticker?: string;
  signal?: string;
  min_elapsed?: number;
  max_elapsed?: number;
  limit?: number;
  offset?: number;
}

export interface HistoryItem {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  signal: string | null;
  elapsed: number;
  created_at: string;
  status: string | null;
  error: string | null;
  completed_stages: string[];
}

export interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function listHistory(params: ListHistoryParams = {}): Promise<HistoryListResponse> {
  const usp = new URLSearchParams();
  if (params.status) usp.set('status', params.status);
  if (params.ticker) usp.set('ticker', params.ticker);
  if (params.signal) usp.set('signal', params.signal);
  if (params.min_elapsed !== undefined && params.min_elapsed !== null)
    usp.set('min_elapsed', String(params.min_elapsed));
  if (params.max_elapsed !== undefined && params.max_elapsed !== null)
    usp.set('max_elapsed', String(params.max_elapsed));
  if (params.limit !== undefined) usp.set('limit', String(params.limit));
  if (params.offset !== undefined) usp.set('offset', String(params.offset));
  const qs = usp.toString();
  const url = _url(`/api/history${qs ? `?${qs}` : ''}`);
  const res = await fetch(url, { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/history ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as HistoryListResponse;
}

// ── detail ────────────────────────────────────────────────────────────────
export interface HistoryDetail extends HistoryItem {
  stage_reports: Record<string, string>;
  started_at: number | null;
  finished_at: number | null;
  results_path: string;
}

export async function getHistory(analysisId: string): Promise<HistoryDetail> {
  const res = await fetch(_url(`/api/history/${encodeURIComponent(analysisId)}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/history/${analysisId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as HistoryDetail;
}

// ── delete ────────────────────────────────────────────────────────────────
export async function deleteHistory(analysisId: string): Promise<{ ok: boolean; analysis_id: string }> {
  const res = await fetch(_url(`/api/history/${encodeURIComponent(analysisId)}`), {
    method: 'DELETE',
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`DELETE /api/history/${analysisId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as { ok: boolean; analysis_id: string };
}

// ── re-run ────────────────────────────────────────────────────────────────
export interface RerunResponse {
  ok: boolean;
  start_analysis: { ticker: string; trade_date: string };
  analysis_id: string;
}

export async function rerunHistory(analysisId: string): Promise<RerunResponse> {
  const res = await fetch(_url(`/api/history/${encodeURIComponent(analysisId)}/rerun`), {
    method: 'POST',
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`POST /api/history/${analysisId}/rerun ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as RerunResponse;
}

// ── report ────────────────────────────────────────────────────────────────
export interface HistoryReport {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  results_path: string;
  report: unknown;
}

export async function getReport(analysisId: string): Promise<HistoryReport> {
  const res = await fetch(_url(`/api/history/${encodeURIComponent(analysisId)}/report`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/history/${analysisId}/report ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as HistoryReport;
}
