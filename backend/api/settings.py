"""Settings API — read/write ~/.tradingagents/settings.json.

Mirrors web/components/settings_panel.py — exposes the same 4 logical fields
(provider / deepModel / quickModel / baseUrl) plus API key status banner data.

Storage convention (跟 portfolio_store / scheduler / log_store 一致):
  ~/.tradingagents/settings.json — JSON object { provider, deepModel,
                                          quickModel, baseUrl, apiKeySet? }

API key 自身仍只在 .env 文件里 (process env), 这里只把 env 中对应
``<PROVIDER>_API_KEY`` 是否存在以及 masked 字符串返回给前端。
写入时不影响 .env; 只切 session_state / settings.json 默认值。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── paths ──────────────────────────────────────────────────────────────────
_TRADINGAGENTS_DIR: Path = Path.home() / ".tradingagents"
SETTINGS_DIR: Path = _TRADINGAGENTS_DIR
SETTINGS_FILE: Path = SETTINGS_DIR / "settings.json"

# ── single-writer lock (避免并发 PUT 半写) ─────────────────────────────────
_io_lock = threading.RLock()


# ── provider env-var lookup ────────────────────────────────────────────────
# 跟 tradingagents.llm_clients.* 的 .env 约定保持一致: <PROVIDER>_API_KEY。
# 见 .env.example + web/components/settings_panel.py 的 LLM 供应商清单。
_PROVIDER_KEYS: List[str] = [
    "minimax",
    "deepseek",
    "qwen",
    "glm",
    "openai",
    "anthropic",
    "google",
    "xai",
    "ollama",
]


def _provider_env_var(provider: str) -> str:
    return f"{provider.upper()}_API_KEY"


def _mask_key(raw: str) -> str:
    """Mask an API key for display: keep first 3 + last 4, replace middle with ***."""
    if not raw:
        return ""
    if len(raw) <= 8:
        return "***"
    return f"{raw[:3]}...{raw[-4:]}"


# ── IO helpers ─────────────────────────────────────────────────────────────
def _read_settings_file() -> Dict[str, Any]:
    """Return on-disk settings dict, or {} if absent / corrupt."""
    with _io_lock:
        if not SETTINGS_FILE.exists():
            return {}
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                return {}
        except (json.JSONDecodeError, OSError):
            return {}


def _write_settings_file(payload: Dict[str, Any]) -> None:
    """Atomic write: tmp + replace, ensures directory exists."""
    with _io_lock:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        tmp.replace(SETTINGS_FILE)


# ── pydantic schemas ──────────────────────────────────────────────────────
class Settings(BaseModel):
    """Persisted user settings — round-trips through ~/.tradingagents/settings.json.

    Extra fields are allowed (forward-compat) — they pass through verbatim.
    """
    provider: str = Field(default="minimax", description="LLM provider key")
    deepModel: str = Field(default="", description="Deep reasoning model id")
    quickModel: str = Field(default="", description="Quick reasoning model id")
    baseUrl: str = Field(default="", description="Custom OpenAI-compatible base URL")

    model_config = {"extra": "allow"}


class SettingsResponse(BaseModel):
    """API response envelope for GET /api/settings.

    Mirrors frontend/src/types/api.ts — SettingsPayload + providers list.
    """
    settings: "SettingsPayload"
    providers: List["ProviderOption"]


class SettingsPayload(BaseModel):
    """Resolved settings (with apiKey status from env) sent to the UI."""
    provider: str
    deepModel: str
    quickModel: str
    apiKey: str = Field(default="", description="Masked key from env (or empty)")
    apiKeySet: bool = Field(default=False, description="True if env var exists")
    baseUrl: str


class ProviderOption(BaseModel):
    key: str
    label: str
    deep: List[Dict[str, str]]
    quick: List[Dict[str, str]]


# ── provider catalog ──────────────────────────────────────────────────────
# Local mirror of MODEL_OPTIONS so we don't import the heavy LLM client
# machinery at module-load time (keeps the API lightweight). Falls back to
# the real catalog if importable.
def _load_provider_catalog() -> List[ProviderOption]:
    try:
        from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
        catalog = MODEL_OPTIONS
    except Exception:
        catalog = {}

    out: List[ProviderOption] = []
    for key in _PROVIDER_KEYS:
        provider_models = catalog.get(key) or {}
        out.append(
            ProviderOption(
                key=key,
                label=_PROVIDER_LABEL.get(key, key),
                deep=[
                    {"label": lbl, "value": val}
                    for lbl, val in provider_models.get("deep", [])
                ],
                quick=[
                    {"label": lbl, "value": val}
                    for lbl, val in provider_models.get("quick", [])
                ],
            )
        )
    return out


_PROVIDER_LABEL: Dict[str, str] = {
    "minimax": "MiniMax（推荐·国内直连）",
    "deepseek": "DeepSeek",
    "qwen": "通义千问 Qwen",
    "glm": "智谱 GLM",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "xai": "xAI Grok",
    "ollama": "Ollama（本地）",
}


# ── payload assembly ──────────────────────────────────────────────────────
def _assemble_payload(saved: Dict[str, Any]) -> SettingsPayload:
    """Merge on-disk settings + env-derived API key status."""
    import os

    provider = str(saved.get("provider", "minimax") or "minimax")
    deep = str(saved.get("deepModel", "") or "")
    quick = str(saved.get("quickModel", "") or "")
    base_url = str(saved.get("baseUrl", "") or "")

    env_var = _provider_env_var(provider)
    raw_key = os.getenv(env_var, "")
    api_key_set = bool(raw_key)
    masked = _mask_key(raw_key) if raw_key else ""

    return SettingsPayload(
        provider=provider,
        deepModel=deep,
        quickModel=quick,
        apiKey=masked,
        apiKeySet=api_key_set,
        baseUrl=base_url,
    )


# ── router ────────────────────────────────────────────────────────────────
router = APIRouter()


@router.get("/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """Read current settings + provider catalog.

    Returns 200 + empty settings if settings.json doesn't exist yet.
    """
    saved = _read_settings_file()
    payload = _assemble_payload(saved)
    return SettingsResponse(
        settings=payload,
        providers=_load_provider_catalog(),
    )


@router.put("/settings")
def put_settings(payload: Settings) -> Dict[str, Any]:
    """Persist settings to ~/.tradingagents/settings.json and return 200."""
    # Round-trip through the on-disk dict so unknown fields are preserved.
    saved = _read_settings_file()
    saved.update(
        {
            "provider": payload.provider,
            "deepModel": payload.deepModel,
            "quickModel": payload.quickModel,
            "baseUrl": payload.baseUrl,
        }
    )
    _write_settings_file(saved)
    return {"ok": True, "settings": _assemble_payload(saved).model_dump()}