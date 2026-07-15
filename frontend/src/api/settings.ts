import type { SettingsPayload, SettingsResponse, SettingsSavePayload } from '@/types/api';

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const SETTINGS_URL = `${API_BASE}/api/settings`;

export async function getSettings(): Promise<SettingsResponse> {
  const res = await fetch(SETTINGS_URL, { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/settings ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as SettingsResponse;
}

export async function saveSettings(payload: SettingsSavePayload): Promise<{ ok: true; settings: SettingsPayload }> {
  const res = await fetch(SETTINGS_URL, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`PUT /api/settings ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as { ok: true; settings: SettingsPayload };
}