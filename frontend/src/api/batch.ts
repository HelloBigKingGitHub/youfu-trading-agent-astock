/**
 * Batch analysis API client — mirrors backend/api/batch.py 1:1.
 *
 * Endpoints (all POST/GET, no streaming body in HTTP path; SSE separately):
 *   POST /api/batch                       create a new batch (list of items)
 *   GET  /api/batch                       list current batches (newest first)
 *   GET  /api/batch/{batch_id}            full batch dict with per-job state
 *   GET  /api/batch/{batch_id}/summary    CSV-ready summary rows
 *   GET  /api/batch/{batch_id}/progress   simple HTTP-poll progress
 *   POST /api/batch/{batch_id}/cancel     cancel all jobs in batch
 *   POST /api/jobs/{job_id}/retry         retry a single failed job
 *   GET  /api/batch/{batch_id}/stream     SSE stream (used by EventSource)
 *
 * Both UIs (Streamlit batch_panel.py + this React BatchPage) ultimately call
 * the same backend queue (backend.core.job_queue). No business logic in this
 * client — pure HTTP mirror of the FastAPI surface, exactly like
 * frontend/src/api/{settings,history,logs,chart,sector}.ts.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

// ── shared types ────────────────────────────────────────────────────────────

export type JobStatus =
  | 'pending' | 'running' | 'completed' | 'error' | 'cancelled';

export type BatchStatus =
  | 'pending' | 'running' | 'completed' | 'partial'
  | 'failed' | 'cancelled';

export interface BatchJob {
  job_id: string;
  analysis_id?: string;
  ticker: string;
  trade_date: string;
  status: JobStatus;
  current_stage?: string;
  completed_stages: string[];
  stage_reports?: Record<string, unknown>;
  signal?: string;
  error?: string | null;
  elapsed?: number;
  created_at?: number;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface LLMSummary {
  ticker: string;
  trade_date: string;
  llm_provider: string;
  deep_think_llm: string;
  quick_think_llm: string;
}

export interface BatchItemInput {
  ticker: string;
  trade_date: string;            // YYYY-MM-DD
  llm_provider?: string | null;
  deep_think_llm?: string | null;
  quick_think_llm?: string | null;
  backend_url?: string | null;
}

export interface BatchCreateResponse {
  batch_id: string;
  total: number;
  jobs: Array<Pick<BatchJob, 'job_id' | 'ticker' | 'trade_date' | 'status'>>;
  llm_summary?: LLMSummary[];
}

export interface BatchListItem {
  batch_id: string;
  batch_status: BatchStatus;
  total: number;
  finished_count: number;
  error_count: number;
  created_at: number;
  jobs: BatchJob[];
}

export interface BatchListResponse {
  batches: BatchListItem[];
  total: number;
}

export interface BatchDetailResponse {
  batch_id: string;
  batch_status: BatchStatus;
  total: number;
  finished_count: number;
  error_count: number;
  jobs: BatchJob[];
}

export interface BatchProgressResponse {
  batch_id: string;
  batch_status: BatchStatus;
  total: number;
  finished_count: number;
  error_count: number;
  running_count: number;
  pending_count: number;
  jobs: BatchJob[];
}

export interface BatchSummaryRow {
  ticker: string;
  trade_date: string;
  status: JobStatus;
  signal: string;
  completed_stages_count: number;
  elapsed_seconds: number;
  error: string;
}

export interface BatchSummaryResponse {
  batch_id: string;
  batch_status: BatchStatus;
  rows: BatchSummaryRow[];
}

export interface BatchCancelResponse {
  batch_id: string;
  cancelled_count: number;
}

// ── POST /api/batch ─────────────────────────────────────────────────────────

export async function createBatch(
  items: BatchItemInput[],
  dedupe: boolean = false,
): Promise<BatchCreateResponse> {
  const qs = new URLSearchParams({ dedupe: String(dedupe) });
  const res = await fetch(_url(`/api/batch?${qs.toString()}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /api/batch ${res.status}: ${text}`);
  }
  return (await res.json()) as BatchCreateResponse;
}

// ── GET /api/batch ──────────────────────────────────────────────────────────

export async function listBatches(limit: number = 20): Promise<BatchListResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(_url(`/api/batch?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/batch ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as BatchListResponse;
}

// ── GET /api/batch/{id} ─────────────────────────────────────────────────────

export async function getBatch(batchId: string): Promise<BatchDetailResponse> {
  const res = await fetch(_url(`/api/batch/${encodeURIComponent(batchId)}`), {
    credentials: 'omit',
  });
  if (res.status === 404) {
    throw new Error('Batch not found');
  }
  if (!res.ok) {
    throw new Error(`GET /api/batch/${batchId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as BatchDetailResponse;
}

// ── GET /api/batch/{id}/summary ─────────────────────────────────────────────

export async function getBatchSummary(batchId: string): Promise<BatchSummaryResponse> {
  const res = await fetch(
    _url(`/api/batch/${encodeURIComponent(batchId)}/summary`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(
      `GET /api/batch/${batchId}/summary ${res.status}: ${await res.text()}`,
    );
  }
  return (await res.json()) as BatchSummaryResponse;
}

// ── GET /api/batch/{id}/progress ────────────────────────────────────────────

export async function getBatchProgress(
  batchId: string,
): Promise<BatchProgressResponse> {
  const res = await fetch(
    _url(`/api/batch/${encodeURIComponent(batchId)}/progress`),
    { credentials: 'omit' },
  );
  if (res.status === 404) {
    throw new Error('Batch not found');
  }
  if (!res.ok) {
    throw new Error(
      `GET /api/batch/${batchId}/progress ${res.status}: ${await res.text()}`,
    );
  }
  return (await res.json()) as BatchProgressResponse;
}

// ── POST /api/batch/{id}/cancel ─────────────────────────────────────────────

export async function cancelBatch(batchId: string): Promise<BatchCancelResponse> {
  const res = await fetch(
    _url(`/api/batch/${encodeURIComponent(batchId)}/cancel`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(
      `POST /api/batch/${batchId}/cancel ${res.status}: ${await res.text()}`,
    );
  }
  return (await res.json()) as BatchCancelResponse;
}

// ── POST /api/jobs/{job_id}/retry ───────────────────────────────────────────

export async function retryJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(
    _url(`/api/jobs/${encodeURIComponent(jobId)}/retry`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/jobs/${jobId}/retry ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as { job_id: string; status: string };
}

// ── SSE stream (used directly by EventSource — kept here for completeness) ──

export function streamUrl(batchId: string): string {
  return _url(`/api/batch/${encodeURIComponent(batchId)}/stream`);
}

// ── Ticker whitelist (mirrors backend TICKER_WHITELIST_RE for client-side pre-validation) ──

export const TICKER_PATTERN = /^(?:60[0-5]\d{3}|601\d{3}|603\d{3}|605\d{3}|688\d{3}|000\d{3}|001\d{3}|002\d{3}|003\d{3}|300\d{3}|301\d{3}|430\d{3})$/;

export function parseTickerList(text: string): { clean: string[]; invalid: string[] } {
  if (!text) return { clean: [], invalid: [] };
  const parts = text.split(/[,\n\r\s]+/).map(p => p.trim()).filter(Boolean);
  const seen = new Set<string>();
  const clean: string[] = [];
  const invalid: string[] = [];
  for (const p of parts) {
    if (TICKER_PATTERN.test(p)) {
      if (!seen.has(p)) {
        seen.add(p);
        clean.push(p);
      }
    } else {
      invalid.push(p);
    }
  }
  return { clean, invalid };
}