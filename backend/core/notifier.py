"""Multi-channel notifier for scheduler completion events.

设计要点：
  * 4 channel：WeCom (webhook POST) / Email (SMTP) / Desktop (notify-send) / Log (logger.info)
  * Jinja2 模板渲染，默认摘要式
  * 单 channel 失败不影响其它 channel，也不让 scheduler 异常
  * 配置：~/.tradingagents/schedules/channels.yaml（可选）

非目标：
  * 不做重试 / 退避（v0.7.0 加）
  * 不做幂等 / 速率限制（channel 端可能限流，但 v0.6.0 不做服务端保护）
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


# ── 路径 / 默认模板 ───────────────────────────────────────────────────────────

CHANNELS_CONFIG_FILE = Path.home() / ".tradingagents" / "schedules" / "channels.yaml"

DEFAULT_TEMPLATE = (
    "⏰ {{ schedule_name }} {{ status_emoji }} {{ status_text }}\n"
    "- 开始: {{ started_at }}\n"
    "- 耗时: {{ duration }}s\n"
    "- 摘要: {{ summary }}\n"
    "- batch_id: {{ batch_id }}\n"
    "- 详情: {{ detail_link }}\n"
)

STATUS_EMOJI = {"ok": "✅", "partial": "⚠️", "error": "❌", "skipped": "⏭️", "never": "⏳"}
STATUS_TEXT = {
    "ok": "全部成功",
    "partial": "部分成功",
    "error": "全部失败",
    "skipped": "已跳过",
    "never": "尚未运行",
}


# ── Enums / Config ──────────────────────────────────────────────────────────


class Channel(str, Enum):
    """支持的通知渠道。"""

    WECOM = "wecom"
    EMAIL = "email"
    DESKTOP = "desktop"
    LOG = "log"


@dataclass
class ChannelConfig:
    """用户从 channels.yaml 加载的渠道配置。

    所有字段可选 —— 缺哪个渠道则 `send()` 时该渠道直接 skip + 返回 False。
    YAML 用最小手写解析 (key: value 行 + `key:` 嵌套) 避免引入 PyYAML 依赖。
    """

    wecom_webhook: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_to: str | None = None
    smtp_use_tls: bool = True
    enabled_channels: list[str] = field(default_factory=lambda: ["log"])

    def is_configured(self, channel: str) -> bool:
        """检查某 channel 是否在 `enabled_channels` 且配置完整。"""
        if channel not in self.enabled_channels:
            return False
        if channel == Channel.WECOM.value:
            return bool(self.wecom_webhook)
        if channel == Channel.EMAIL.value:
            return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_to)
        if channel in (Channel.DESKTOP.value, Channel.LOG.value):
            return True
        return False


# ── Notifier ─────────────────────────────────────────────────────────────────


class Notifier:
    """单例多 channel 通知器。

    用法：
        notifier = Notifier.get_instance()
        results = notifier.send(["log", "desktop"], "schedule_name", {
            "status": "ok", "started_at": ..., "duration": ..., "summary": ...,
            "batch_id": ..., "run_id": ..., "ticker_count": ...,
        })
        # results = {"log": True, "desktop": False}
    """

    _instance: "Notifier | None" = None
    _init_lock = __import__("threading").Lock()

    def __init__(self) -> None:
        from jinja2 import Environment
        self._env = Environment()
        self._template = self._env.from_string(DEFAULT_TEMPLATE)
        self._config = self._load_config()

    @classmethod
    def get_instance(cls) -> "Notifier":
        """双检锁获取单例。"""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_singleton(cls) -> None:
        """测试用：清空单例缓存。"""
        with cls._init_lock:
            cls._instance = None

    def reload_config(self) -> None:
        """重新读取 channels.yaml（测试 + 运行时改配置用）。"""
        self._config = self._load_config()

    def config(self) -> ChannelConfig:
        """返回当前配置（只读快照）。"""
        return self._config

    # ── Public send API ───────────────────────────────────────────────────

    def send(self, channels: list[str], schedule_name: str, run_data: dict) -> dict[str, bool]:
        """对 channels 列表里的每个渠道发送通知。

        任一渠道失败 → results[ch] = False，但不影响其他渠道。
        返回 {channel: success_bool}。
        """
        results: dict[str, bool] = {}
        for ch in channels:
            try:
                self._send_one(ch, schedule_name, run_data)
                results[ch] = True
            except Exception as exc:  # noqa: BLE001 —— 通知必须隔离异常
                logger.warning(
                    "notifier channel %s 失败 (schedule=%s): %s",
                    ch, schedule_name, exc,
                )
                results[ch] = False
        return results

    def _send_one(self, channel: str, schedule_name: str, run_data: dict) -> None:
        """单渠道发送。缺少配置则 raise（上层 send 捕获）。"""
        text = self._render(schedule_name, run_data)
        if channel == Channel.WECOM.value:
            self._send_wecom(text)
        elif channel == Channel.EMAIL.value:
            self._send_email(schedule_name, text)
        elif channel == Channel.DESKTOP.value:
            self._send_desktop(schedule_name, text)
        elif channel == Channel.LOG.value:
            self._send_log(schedule_name, text)
        else:
            raise ValueError(f"未知 channel: {channel!r}")

    def _render(self, schedule_name: str, run_data: dict) -> str:
        """Jinja2 渲染默认模板。提供默认值避免缺失字段报错。"""
        status = run_data.get("status", "never")
        started_ts = run_data.get("started_at")
        started_str = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_ts))
            if isinstance(started_ts, (int, float))
            else "N/A"
        )
        run_id = run_data.get("run_id", "")
        detail_link = (
            f"~/.tradingagents/schedules/runs/{run_id}.json"
            if run_id else "N/A"
        )
        return self._template.render(
            schedule_name=schedule_name,
            status_emoji=STATUS_EMOJI.get(status, "❓"),
            status_text=STATUS_TEXT.get(status, status),
            started_at=started_str,
            duration=int(run_data.get("duration", 0.0)),
            summary=run_data.get("summary", ""),
            batch_id=run_data.get("batch_id", ""),
            run_id=run_id,
            detail_link=detail_link,
        )

    # ── Channel implementations ───────────────────────────────────────────

    def _send_wecom(self, text: str) -> None:
        """WeCom webhook POST。HTTP 4xx/5xx 都 raise。"""
        if not self._config.wecom_webhook:
            raise ValueError("wecom_webhook 未配置")
        payload = json.dumps(
            {"msgtype": "markdown", "markdown": {"content": text}}
        ).encode("utf-8")
        req = urllib.request.Request(
            self._config.wecom_webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # urllib 是 stdlib，无 requests 依赖
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()  # 触发实际请求

    def _send_email(self, subject: str, body: str) -> None:
        """SMTP 发送纯文本邮件。需要 smtp_host/user/password/to 全部配置。"""
        from email.mime.text import MIMEText

        if not (
            self._config.smtp_host
            and self._config.smtp_user
            and self._config.smtp_password
            and self._config.smtp_to
        ):
            raise ValueError("SMTP 配置不完整")
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._config.smtp_user
        msg["To"] = self._config.smtp_to
        with smtplib.SMTP(
            self._config.smtp_host, int(self._config.smtp_port), timeout=15
        ) as smtp:
            if self._config.smtp_use_tls:
                smtp.starttls()
            smtp.login(self._config.smtp_user, self._config.smtp_password)
            smtp.sendmail(self._config.smtp_user, [self._config.smtp_to], msg.as_string())

    def _send_desktop(self, title: str, body: str) -> None:
        """Linux 桌面通知 via notify-send。失败不抛（check=False）。"""
        if not sys.platform.startswith("linux"):
            # macOS / Windows —— v0.6.0 不支持
            raise NotImplementedError(
                f"Desktop 通知仅支持 Linux，当前平台: {sys.platform}"
            )
        subprocess.run(
            ["notify-send", title, body],
            check=False,
            timeout=5,
            capture_output=True,
        )

    def _send_log(self, schedule_name: str, text: str) -> None:
        """最基础 channel：写 logger.info。"""
        logger.info("[notify] %s\n%s", schedule_name, text)

    # ── YAML 加载（无 PyYAML 依赖） ──────────────────────────────────────

    def _load_config(self) -> ChannelConfig:
        """手写解析 channels.yaml。缺文件 → 返回默认 (仅 log 启用)。

        支持 2 级 YAML：
            channel_name:
              key: value
            enabled_channels: [wecom, log]
        """
        cfg = ChannelConfig()
        if not CHANNELS_CONFIG_FILE.exists():
            return cfg
        try:
            raw = CHANNELS_CONFIG_FILE.read_text(encoding="utf-8")
        except OSError:
            return cfg
        if not raw.strip():
            return cfg
        try:
            parsed = self._parse_yaml(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析 channels.yaml 失败: %s", exc)
            return cfg
        return self._apply_to_config(cfg, parsed)

    def _parse_yaml(self, raw: str) -> dict:
        """非常小的 YAML 解析 —— 2 级嵌套 + 列表。"""
        result: dict = {}
        current_section: str | None = None
        for line in raw.splitlines():
            stripped = line.rstrip()
            if not stripped.strip() or stripped.lstrip().startswith("#"):
                continue
            if not stripped.startswith((" ", "\t")):
                # top-level key
                if ":" not in stripped:
                    continue
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "":
                    # 新 section
                    current_section = key
                    result[key] = {}
                elif val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if not inner:
                        result[key] = []
                    else:
                        items = [
                            self._coerce(item.strip().strip('"').strip("'"))
                            for item in inner.split(",")
                        ]
                        result[key] = items
                    current_section = None
                else:
                    # 标量（top-level）
                    current_section = None
                    result[key] = self._coerce(val)
            else:
                # 嵌套 key
                content = stripped.lstrip()
                if current_section is None or ":" not in content:
                    continue
                key, _, val = content.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "":
                    result[current_section][key] = {}
                elif val.startswith("[") and val.endswith("]"):
                    inner = val[1:-1].strip()
                    if not inner:
                        result[current_section][key] = []
                    else:
                        items = [
                            self._coerce(item.strip().strip('"').strip("'"))
                            for item in inner.split(",")
                        ]
                        result[current_section][key] = items
                else:
                    result[current_section][key] = self._coerce(val)
        return result

    def _coerce(self, val: str):
        """把字符串值转成 int / bool / str（保留引号去除）。"""
        v = val.strip().strip('"').strip("'")
        if v.lower() in ("true", "yes"):
            return True
        if v.lower() in ("false", "no"):
            return False
        if v.lower() in ("null", "~", ""):
            return None
        try:
            if "." in v:
                return float(v)
            return int(v)
        except ValueError:
            return v

    def _apply_to_config(self, cfg: ChannelConfig, parsed: dict) -> ChannelConfig:
        if "wecom" in parsed and isinstance(parsed["wecom"], dict):
            wh = parsed["wecom"].get("webhook")
            if wh:
                cfg.wecom_webhook = str(wh)
        if "email" in parsed and isinstance(parsed["email"], dict):
            em = parsed["email"]
            for k, attr in (
                ("host", "smtp_host"),
                ("port", "smtp_port"),
                ("user", "smtp_user"),
                ("password", "smtp_password"),
                ("to", "smtp_to"),
            ):
                if k in em and em[k] is not None:
                    setattr(cfg, attr, em[k])
            if "use_tls" in em:
                cfg.smtp_use_tls = bool(em["use_tls"])
        top_enabled = parsed.get("enabled_channels")
        if isinstance(top_enabled, list):
            cfg.enabled_channels = [str(c) for c in top_enabled]
        elif isinstance(top_enabled, str) and top_enabled:
            cfg.enabled_channels = [c.strip() for c in top_enabled.split(",")]
        return cfg


def get_notifier() -> Notifier:
    """模块级便捷访问。"""
    return Notifier.get_instance()
