"""Tests for scripts/notify_telegram.py. No real HTTP calls are made."""

from __future__ import annotations

import httpx
import pytest

from scripts.notify_telegram import build_message, main, send_telegram_message


# --- build_message ---


def test_build_message_success_includes_checkmark_and_run_number():
    text = build_message("success", "dbt build passed", "42")

    assert text.startswith("✅")
    assert "dbt build passed" in text
    assert "#42" in text


def test_build_message_failure_includes_alarm_emoji():
    text = build_message("failure", "INMET extraction failed", "42")

    assert text.startswith("🚨")


def test_build_message_omits_run_number_when_not_set():
    text = build_message("success", "all good", None)

    assert "GitHub Actions run" not in text


# --- send_telegram_message ---


def test_send_telegram_message_posts_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("scripts.notify_telegram.httpx.post", fake_post)

    send_telegram_message("BOT_TOKEN", "CHAT_ID", "hello")

    assert captured["url"] == "https://api.telegram.org/botBOT_TOKEN/sendMessage"
    assert captured["json"] == {"chat_id": "CHAT_ID", "text": "hello"}


def test_send_telegram_message_raises_on_http_error(monkeypatch):
    def fake_post(url, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(401, request=request, json={"ok": False})

    monkeypatch.setattr("scripts.notify_telegram.httpx.post", fake_post)

    with pytest.raises(httpx.HTTPStatusError):
        send_telegram_message("BAD_TOKEN", "CHAT_ID", "hello")


# --- main ---


def test_main_fails_cleanly_when_env_vars_missing(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr("sys.argv", ["notify_telegram.py", "--status", "success", "--message", "hi"])

    exit_code = main()

    assert exit_code == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().err


def test_main_sends_notification_and_returns_0_on_success(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT_ID")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "7")
    monkeypatch.setattr("sys.argv", ["notify_telegram.py", "--status", "failure", "--message", "boom"])

    sent = {}

    def fake_send(bot_token, chat_id, text, **kwargs):
        sent["bot_token"] = bot_token
        sent["chat_id"] = chat_id
        sent["text"] = text

    monkeypatch.setattr("scripts.notify_telegram.send_telegram_message", fake_send)

    exit_code = main()

    assert exit_code == 0
    assert sent["bot_token"] == "BOT_TOKEN"
    assert sent["chat_id"] == "CHAT_ID"
    assert "boom" in sent["text"]
    assert "#7" in sent["text"]


def test_main_returns_1_when_send_fails(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT_ID")
    monkeypatch.setattr("sys.argv", ["notify_telegram.py", "--status", "success", "--message", "hi"])

    def fake_send(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("scripts.notify_telegram.send_telegram_message", fake_send)

    exit_code = main()

    assert exit_code == 1
    assert "Failed to send" in capsys.readouterr().err
