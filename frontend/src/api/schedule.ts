/**
 * Schedule API client — mirrors backend/api/schedule.py 1:1.
 *
 * Endpoints (13 total, mirroring Streamlit web/components/schedule_panel.py):
 *   GET  /api/schedule/list                        → list all schedules (enabled+disabled)
 *   GET  /api/schedule/watchlist                   → list watchlist entries (tag filter)
 *   GET  /api/schedule/notifier/channels           → 4 notify channels + config status
 *   GET  /api/schedule/{schedule_id}               → single schedule + recent 20 runs
 *   POST /api/schedule/create                      → create new (cron + source + notify)
 *   PUT  /api/schedule/{schedule_id}               → update fields
 *   DEL  /api/schedule/{schedule_id}               → delete
 *   POST /api/schedule/{schedule_id}/run_now       → fire immediately
 *   POST /api/schedule/{schedule_id}/pause         → pause
 *   POST /api/schedule/{schedule_id}/resume        → resume
 *   POST /api/schedule/{schedule_id}/test_notify   → fire one-shot test notify
 *   GET  /api/schedule/runs/{run_id}               → run detail
 *   GET  /api/schedule/test_notify/status/{run_id} → poll test_notify status
 *
 * Both UIs (Streamlit schedule_panel.py + this React SchedulePage) call the
 * same backend core (backend.core.scheduler / watchlist / notifier). No
 * business logic here — pure HTTP mirror of the FastAPI surface.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

// ── shared types ────────────────────────────────────────────────────────────

export interface Schedule {
  schedule_id: string;
  name: string;
  cron_expr: string;
  source_type: 'portfolio' | 'watchlist' | 'manual' | string;
  source_config: Record<string, unknown>;
  enabled: boolean;
  notify_channels: string[];
  notify_template: string;
  config: Record<string, unknown>;
  last_run_at: number | null;
  last_run_batch_id: string | null;
  last_run_status: 'never' | 'running' | 'ok' | 'error' | string;
  last_error: string | null;
  created_at: number;
  created_by: string;
  /** Computed: next cron fire timestamp (or null if cron invalid). */
  next_run_at: number | null;
  /** Computed: e.g. "持仓" / "自选股 · 长线" / "手动 · 3 只". */
  source_summary: string;
}

export interface ScheduleRun {
  run_id: string;
  schedule_id: string;
  started_at: number;
  finished_at: number | null;
  status: 'running' | 'ok' | 'error' | string;
  batch_id: string | null;
  job_ids: string[];
  duration: number;
  summary: string;
  error: string | null;
  ticker_count: number;
}

export interface WatchlistEntry {
  entry_id: string;
  ticker: string;
  tag: string;
  note: string;
  created_at: number;
}

export interface NotifierChannel {
  channel: 'wecom' | 'email' | 'desktop' | 'log' | string;
  label: string;
  enabled_in_config: boolean;
  configured: boolean;
  supports_test: boolean;
  test_endpoint: string;
}

// ── response shapes ─────────────────────────────────────────────────────────

export interface ListSchedulesResponse {
  schedules: Schedule[];
  count: number;
  scheduler_running: boolean;
  last_tick_at: number | null;
  fetched_at: number;
}

export interface ScheduleDetailResponse {
  schedule: Schedule;
  runs: ScheduleRun[];
  fetched_at: number;
}

export interface WatchlistResponse {
  entries: WatchlistEntry[];
  count: number;
  valid_tags: string[];
  fetched_at: number;
}

export interface NotifierChannelsResponse {
  channels: NotifierChannel[];
  count: number;
  enabled_channels: string[];
  fetched_at: number;
}

export interface RunDetailResponse {
  run: ScheduleRun;
  fetched_at: number;
}

export interface SimpleAckResponse {
  [key: string]: unknown;
  schedule_id?: string;
  run_id?: string;
}

// ── GET /api/schedule/list ──────────────────────────────────────────────────

export async function listSchedules(): Promise<ListSchedulesResponse> {
  const res = await fetch(_url('/api/schedule/list'), { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/schedule/list ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ListSchedulesResponse;
}

// ── GET /api/schedule/watchlist ─────────────────────────────────────────────

export async function listWatchlist(tag: string = ''): Promise<WatchlistResponse> {
  const qs = tag ? `?tag=${encodeURIComponent(tag)}` : '';
  const res = await fetch(_url(`/api/schedule/watchlist${qs}`), { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/schedule/watchlist ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as WatchlistResponse;
}

// ── GET /api/schedule/notifier/channels ─────────────────────────────────────

export async function listNotifierChannels(): Promise<NotifierChannelsResponse> {
  const res = await fetch(_url('/api/schedule/notifier/channels'), { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/schedule/notifier/channels ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as NotifierChannelsResponse;
}

// ── GET /api/schedule/{schedule_id} ─────────────────────────────────────────

export async function getSchedule(scheduleId: string): Promise<ScheduleDetailResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/schedule/${scheduleId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ScheduleDetailResponse;
}

// ── POST /api/schedule/create ───────────────────────────────────────────────

export interface CreateSchedulePayload {
  name: string;
  cron_expr: string;
  source_type: 'portfolio' | 'watchlist' | 'manual';
  source_config?: Record<string, unknown>;
  notify_channels?: string[];
  notify_template?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}

export async function createSchedule(payload: CreateSchedulePayload): Promise<ScheduleDetailResponse> {
  const res = await fetch(_url('/api/schedule/create'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`POST /api/schedule/create ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ScheduleDetailResponse;
}

// ── PUT /api/schedule/{schedule_id} ─────────────────────────────────────────

export async function updateSchedule(
  scheduleId: string,
  payload: Partial<CreateSchedulePayload>,
): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}`),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'omit',
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    throw new Error(`PUT /api/schedule/${scheduleId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── DELETE /api/schedule/{schedule_id} ──────────────────────────────────────

export async function deleteSchedule(scheduleId: string): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}`),
    { method: 'DELETE', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`DELETE /api/schedule/${scheduleId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── POST /api/schedule/{schedule_id}/run_now ────────────────────────────────

export async function runNow(scheduleId: string): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}/run_now`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/schedule/${scheduleId}/run_now ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── POST /api/schedule/{schedule_id}/pause ──────────────────────────────────

export async function pauseSchedule(scheduleId: string): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}/pause`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/schedule/${scheduleId}/pause ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── POST /api/schedule/{schedule_id}/resume ─────────────────────────────────

export async function resumeSchedule(scheduleId: string): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(`/api/schedule/${encodeURIComponent(scheduleId)}/resume`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/schedule/${scheduleId}/resume ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── POST /api/schedule/{schedule_id}/test_notify ────────────────────────────

export async function testNotify(
  scheduleId: string,
  channel: string,
): Promise<SimpleAckResponse> {
  const res = await fetch(
    _url(
      `/api/schedule/${encodeURIComponent(scheduleId)}/test_notify?channel=${encodeURIComponent(channel)}`,
    ),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(
      `POST /api/schedule/${scheduleId}/test_notify ${res.status}: ${await res.text()}`,
    );
  }
  return (await res.json()) as SimpleAckResponse;
}

// ── GET /api/schedule/runs/{run_id} ─────────────────────────────────────────

export async function getRun(runId: string): Promise<RunDetailResponse> {
  const res = await fetch(
    _url(`/api/schedule/runs/${encodeURIComponent(runId)}`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/schedule/runs/${runId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as RunDetailResponse;
}