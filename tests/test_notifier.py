"""Tests for backend.core.notifier — 4 channels + 模板 + 失败隔离."""

from __future__ import annotations

import logging
import smtplib
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.core.notifier import (
    CHANNELS_CONFIG_FILE,
    DEFAULT_TEMPLATE,
    STATUS_EMOJI,
    STATUS_TEXT,
    Channel,
    ChannelConfig,
    Notifier,
    get_notifier,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_channels_config(tmp_path, monkeypatch):
    """重定向 CHANNELS_CONFIG_FILE 到 tmp_path + 重置单例。"""
    path = tmp_path / "channels.yaml"
    monkeypatch.setattr("backend.core.notifier.CHANNELS_CONFIG_FILE", path)
    Notifier._reset_singleton()
    yield path
    Notifier._reset_singleton()


@pytest.fixture
def notifier(tmp_channels_config):
    return Notifier()


def _run_data(**over):
    base = {
        "status": "ok",
        "started_at": 1700000000.0,  # 固定 ts 便于断言
        "duration": 42.0,
        "summary": "ok=3 error=0 cancelled=0 total=3",
        "batch_id": "batch_abc",
        "run_id": "run_xyz",
        "ticker_count": 3,
    }
    base.update(over)
    return base


# ── Channel enum ────────────────────────────────────────────────────────────


class TestChannelEnum:
    def test_four_values(self):
        assert Channel.WECOM.value == "wecom"
        assert Channel.EMAIL.value == "email"
        assert Channel.DESKTOP.value == "desktop"
        assert Channel.LOG.value == "log"
        assert {c.value for c in Channel} == {"wecom", "email", "desktop", "log"}


# ── ChannelConfig ───────────────────────────────────────────────────────────


class TestChannelConfig:
    def test_default_only_log(self):
        c = ChannelConfig()
        assert c.enabled_channels == ["log"]
        assert c.is_configured("log") is True
        assert c.is_configured("desktop") is False
        assert c.is_configured("wecom") is False
        assert c.is_configured("email") is False

    def test_is_configured_wecom(self):
        c = ChannelConfig(wecom_webhook="https://example.com", enabled_channels=["wecom"])
        assert c.is_configured("wecom") is True
        c2 = ChannelConfig(wecom_webhook=None, enabled_channels=["wecom"])
        assert c2.is_configured("wecom") is False

    def test_is_configured_email(self):
        full = ChannelConfig(
            smtp_host="smtp.example", smtp_port=587,
            smtp_user="u", smtp_password="p", smtp_to="a@b",
            enabled_channels=["email"],
        )
        assert full.is_configured("email") is True
        # 任一缺 → False
        no_to = ChannelConfig(smtp_host="x", smtp_user="u", smtp_password="p")
        no_to.enabled_channels = ["email"]
        assert no_to.is_configured("email") is False


# ── 模板渲染 ─────────────────────────────────────────────────────────────────


class TestRender:
    def test_render_ok(self, notifier):
        text = notifier._render("my_schedule", _run_data(status="ok"))
        assert "⏰ my_schedule ✅ 全部成功" in text
        assert "batch_id: batch_abc" in text
        assert "batch_abc" in text
        assert "ok=3 error=0 cancelled=0 total=3" in text
        assert "42" in text  # duration

    def test_render_partial(self, notifier):
        text = notifier._render("my", _run_data(status="partial"))
        assert "⚠️" in text
        assert "部分成功" in text

    def test_render_error(self, notifier):
        text = notifier._render("my", _run_data(status="error"))
        assert "❌" in text
        assert "全部失败" in text

    def test_render_status_unknown_falls_back(self, notifier):
        text = notifier._render("my", _run_data(status="weird"))
        assert "❓" in text
        assert "weird" in text

    def test_render_missing_started_at(self, notifier):
        text = notifier._render("my", _run_data(started_at=None))
        assert "N/A" in text

    def test_render_short_yaml_uses_default_template_text(self):
        assert "schedule_name" in DEFAULT_TEMPLATE
        assert "status_emoji" in DEFAULT_TEMPLATE


# ── 单 channel 发送 ─────────────────────────────────────────────────────────


class TestSendLog:
    def test_log_writes_to_logger(self, notifier, caplog):
        with caplog.at_level(logging.INFO, logger="backend.core.notifier"):
            res = notifier.send(["log"], "sched_name", _run_data())
        assert res["log"] is True
        joined = "\n".join(r.message for r in caplog.records)
        assert "sched_name" in joined


class TestSendWeCom:
    def test_wecom_no_config_raises(self, notifier):
        """未配置 webhook → _send_wecom 抛 ValueError。"""
        with pytest.raises(ValueError, match="wecom_webhook"):
            notifier._send_wecom("hi")

    def test_wecom_posts_to_url(self, notifier, tmp_channels_config):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                captured["read"] = True
                return b"{}"

        def fake_urlopen(req, timeout=10):
            captured["url"] = req.full_url
            captured["data"] = req.data.decode("utf-8")
            captured["timeout"] = timeout
            return FakeResp()

        # 写配置
        tmp_channels_config.write_text(
            "wecom:\n  webhook: https://qyapi.example.com/hook\nenabled_channels: [wecom]\n",
            encoding="utf-8",
        )
        notifier.reload_config()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            notifier.send(["wecom"], "sched", _run_data())
        assert "https://qyapi.example.com/hook" in captured["url"]
        assert "msgtype" in captured["data"]
        assert "markdown" in captured["data"]


class TestSendEmail:
    def test_email_incomplete_config_raises(self, notifier):
        with pytest.raises(ValueError, match="SMTP"):
            notifier._send_email("subject", "body")

    def test_email_smtp_called(self, notifier, tmp_channels_config):
        tmp_channels_config.write_text(
            "email:\n"
            "  host: smtp.example\n"
            "  port: 587\n"
            "  user: u@x\n"
            "  password: p\n"
            "  to: a@b\n"
            "  use_tls: true\n"
            "enabled_channels: [email]\n",
            encoding="utf-8",
        )
        notifier.reload_config()

        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        with patch("smtplib.SMTP", mock_smtp_class):
            notifier.send(["email"], "sched", _run_data())

        mock_smtp_class.assert_called_once_with(
            "smtp.example", 587, timeout=15
        )
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("u@x", "p")
        sent = mock_smtp_instance.sendmail.call_args[0]
        assert sent[0] == "u@x"
        assert sent[1] == ["a@b"]


class TestSendDesktop:
    def test_desktop_skipped_on_non_linux(self, notifier, monkeypatch):
        monkeypatch.setattr("sys.platform", "darwin")
        with pytest.raises(NotImplementedError, match="Linux"):
            notifier._send_desktop("title", "body")

    def test_desktop_linux_runs_notify_send(self, notifier, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        with patch("subprocess.run") as mock_run:
            notifier._send_desktop("title", "body")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "notify-send"
        assert args[1] == "title"
        assert args[2] == "body"


# ── 多 channel / 失败隔离 / singleton ────────────────────────────────────────


class TestNotifierBehavior:
    def test_send_unknown_channel_returns_false(self, notifier):
        res = notifier.send(["unknown"], "sched", _run_data())
        assert res == {"unknown": False}

    def test_one_channel_failure_does_not_break_others(self, notifier, tmp_channels_config):
        """wecom 未配置 → False，但 log 仍 True。"""
        res = notifier.send(["wecom", "log"], "sched", _run_data())
        assert res["wecom"] is False
        assert res["log"] is True

    def test_multi_channel_runs_all(self, notifier, tmp_channels_config):
        tmp_channels_config.write_text(
            "wecom:\n  webhook: https://x.example\n"
            "enabled_channels: [log, wecom]\n",
            encoding="utf-8",
        )
        notifier.reload_config()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            res = notifier.send(["log", "wecom"], "sched", _run_data())
        assert res["log"] is True
        assert res["wecom"] is True

    def test_singleton(self, tmp_channels_config):
        a = Notifier.get_instance()
        b = Notifier.get_instance()
        assert a is b
        assert get_notifier() is a

    def test_load_config_missing_file(self, notifier):
        """CHANNELS_CONFIG_FILE 不存在 → 不抛，只用默认。"""
        # 触发 reload（fixture 已 monkeypatch 到 tmp_path 不存在）
        Notifier._reset_singleton()
        n = Notifier()
        cfg = n.config()
        assert cfg.enabled_channels == ["log"]
        assert cfg.wecom_webhook is None


# ── YAML 解析 ──────────────────────────────────────────────────────────────


class TestYamlParser:
    def test_parse_wecom_block(self, notifier):
        yaml = """
wecom:
  webhook: https://x.com/hook
enabled_channels: [wecom, log]
"""
        parsed = notifier._parse_yaml(yaml)
        assert parsed["wecom"]["webhook"] == "https://x.com/hook"
        assert parsed["enabled_channels"] == ["wecom", "log"]

    def test_parse_email_block(self, notifier):
        yaml = """
email:
  host: smtp.x
  port: 25
  user: me@x
  password: pw
  to: a@b
  use_tls: false
"""
        parsed = notifier._parse_yaml(yaml)
        em = parsed["email"]
        assert em["host"] == "smtp.x"
        assert em["port"] == 25  # int
        assert em["use_tls"] is False  # bool

    def test_parse_skips_comments(self, notifier):
        yaml = """
# this is comment
wecom:
  webhook: https://x  # inline comment ok
"""
        parsed = notifier._parse_yaml(yaml)
        assert "https://x" in parsed["wecom"]["webhook"]

    def test_load_config_corrupt_recovers(self, notifier, tmp_channels_config):
        tmp_channels_config.write_text(":\nnot yaml:\n  bad", encoding="utf-8")
        Notifier._reset_singleton()
        n = Notifier()
        cfg = n.config()
        # 解析失败 → 默认配置（enabled_channels = ["log"]）
        assert cfg.enabled_channels == ["log"]
