// API types — shared by frontend (React Query) and mirrored in backend Pydantic.
// When in doubt, the BACKEND is source of truth — backend/api/settings.py owns schema.

export interface SettingsPayload {
  provider: string;
  deepModel: string;
  quickModel: string;
  apiKey: string;        // masked when read (e.g. "sk-...xxxx")
  apiKeySet: boolean;    // true if a real key exists in .env
  baseUrl: string;
}

export interface SettingsSavePayload {
  provider: string;
  deepModel: string;
  quickModel: string;
  baseUrl: string;
}

export interface ProviderOption {
  key: string;
  label: string;
  deep: Array<{ label: string; value: string }>;
  quick: Array<{ label: string; value: string }>;
}

export interface SettingsResponse {
  settings: SettingsPayload;
  providers: ProviderOption[];
}