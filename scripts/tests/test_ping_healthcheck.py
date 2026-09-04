"""Tests for scripts/ping_healthcheck.py. No real HTTP calls are made."""

from __future__ import annotations

import httpx
import pytest

from scripts.ping_healthcheck import main, ping


def test_ping_gets_the_configured_url(monkeypatch):
    captured = {}

    def fake_get(url, timeout):
        captured["url"] = url
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr("scripts.ping_healthcheck.httpx.get", fake_get)

    ping("https://hc-ping.com/abc123")

    assert captured["url"] == "https://hc-ping.com/abc123"


def test_ping_raises_on_http_error(monkeypatch):
    def fake_get(url, timeout):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr("scripts.ping_healthcheck.httpx.get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        ping("https://hc-ping.com/abc123")


def test_main_fails_cleanly_when_env_var_missing(monkeypatch, capsys):
    monkeypatch.delenv("HEALTHCHECK_URL", raising=False)

    exit_code = main()

    assert exit_code == 1
    assert "HEALTHCHECK_URL" in capsys.readouterr().err


def test_main_returns_0_on_success(monkeypatch, capsys):
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc123")
    monkeypatch.setattr("scripts.ping_healthcheck.ping", lambda url: None)

    exit_code = main()

    assert exit_code == 0
    assert "sent" in capsys.readouterr().out


def test_main_returns_1_when_ping_fails(monkeypatch, capsys):
    monkeypatch.setenv("HEALTHCHECK_URL", "https://hc-ping.com/abc123")

    def fake_ping(url):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("scripts.ping_healthcheck.ping", fake_ping)

    exit_code = main()

    assert exit_code == 1
    assert "Failed to ping" in capsys.readouterr().err
