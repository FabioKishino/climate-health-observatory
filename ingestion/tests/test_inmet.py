"""Tests for the INMET ingestion module. No real HTTP calls are made —
`httpx.MockTransport` stands in for the network."""

from __future__ import annotations

import httpx
import pytest

from ingestion.inmet.client import InmetAPIError, InmetClient
from ingestion.inmet.extract import aggregate_daily, parse_hourly_readings

STATION_CODE = "A807"


def _make_client(handler, **kwargs) -> InmetClient:
    return InmetClient(transport=httpx.MockTransport(handler), **kwargs)


# --- parse_hourly_readings ---


def test_parse_hourly_readings_valid():
    raw = [
        {
            "CD_ESTACAO": STATION_CODE,
            "DT_MEDICAO": "2024-05-01",
            "HR_MEDICAO": "1200",
            "TEM_INS": "18,4",
            "TEM_MAX": "19.0",
            "TEM_MIN": "17.5",
            "UMD_INS": "80",
            "CHUVA": "0.2",
        }
    ]

    parsed = parse_hourly_readings(raw, STATION_CODE)

    assert parsed == [
        {
            "station_code": STATION_CODE,
            "date": "2024-05-01",
            "temp_instant": 18.4,
            "temp_max": 19.0,
            "temp_min": 17.5,
            "humidity_instant": 80.0,
            "precipitation": 0.2,
        }
    ]


def test_parse_hourly_readings_handles_missing_values():
    raw = [
        {
            "CD_ESTACAO": STATION_CODE,
            "DT_MEDICAO": "2024-05-01",
            "HR_MEDICAO": "1300",
            "TEM_INS": None,
            "TEM_MAX": "",
            "TEM_MIN": None,
            "UMD_INS": None,
            "CHUVA": None,
        }
    ]

    parsed = parse_hourly_readings(raw, STATION_CODE)

    assert parsed[0]["temp_instant"] is None
    assert parsed[0]["temp_max"] is None
    assert parsed[0]["precipitation"] is None


def test_parse_hourly_readings_skips_records_without_date():
    raw = [{"CD_ESTACAO": STATION_CODE, "DT_MEDICAO": "", "TEM_INS": "20"}]

    parsed = parse_hourly_readings(raw, STATION_CODE)

    assert parsed == []


def test_parse_hourly_readings_empty_response():
    assert parse_hourly_readings([], STATION_CODE) == []


# --- aggregate_daily ---


def test_aggregate_daily_computes_expected_metrics():
    readings = [
        {
            "station_code": STATION_CODE,
            "date": "2024-05-01",
            "temp_instant": 15.0,
            "temp_max": 20.0,
            "temp_min": 10.0,
            "humidity_instant": 70.0,
            "precipitation": 1.0,
        },
        {
            "station_code": STATION_CODE,
            "date": "2024-05-01",
            "temp_instant": 25.0,
            "temp_max": 26.0,
            "temp_min": 12.0,
            "humidity_instant": 90.0,
            "precipitation": None,
        },
    ]

    [daily] = aggregate_daily(readings)

    assert daily["station_code"] == STATION_CODE
    assert daily["date"] == "2024-05-01"
    assert daily["avg_temp"] == 20.0
    assert daily["min_temp"] == 10.0
    assert daily["max_temp"] == 26.0
    assert daily["avg_relative_humidity"] == 80.0
    assert daily["total_precipitation"] == 1.0


def test_aggregate_daily_falls_back_to_instant_temp_when_min_max_missing():
    readings = [
        {
            "station_code": STATION_CODE,
            "date": "2024-05-02",
            "temp_instant": 12.0,
            "temp_max": None,
            "temp_min": None,
            "humidity_instant": None,
            "precipitation": None,
        },
        {
            "station_code": STATION_CODE,
            "date": "2024-05-02",
            "temp_instant": 18.0,
            "temp_max": None,
            "temp_min": None,
            "humidity_instant": None,
            "precipitation": None,
        },
    ]

    [daily] = aggregate_daily(readings)

    assert daily["min_temp"] == 12.0
    assert daily["max_temp"] == 18.0
    assert daily["avg_relative_humidity"] is None
    assert daily["total_precipitation"] is None


def test_aggregate_daily_groups_by_station_and_date():
    readings = [
        {
            "station_code": "A807",
            "date": "2024-05-01",
            "temp_instant": 10.0,
            "temp_max": 10.0,
            "temp_min": 10.0,
            "humidity_instant": 50.0,
            "precipitation": 0.0,
        },
        {
            "station_code": "A999",
            "date": "2024-05-01",
            "temp_instant": 30.0,
            "temp_max": 30.0,
            "temp_min": 30.0,
            "humidity_instant": 50.0,
            "precipitation": 0.0,
        },
    ]

    daily = aggregate_daily(readings)

    assert len(daily) == 2
    assert {row["station_code"] for row in daily} == {"A807", "A999"}


def test_aggregate_daily_empty_input():
    assert aggregate_daily([]) == []


# --- InmetClient ---


def test_client_returns_parsed_json_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"CD_ESTACAO": STATION_CODE, "DT_MEDICAO": "2024-05-01"}])

    client = _make_client(handler)
    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == [{"CD_ESTACAO": STATION_CODE, "DT_MEDICAO": "2024-05-01"}]


def test_client_handles_empty_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == []


def test_client_raises_on_non_retryable_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "station not found"})

    client = _make_client(handler)

    with pytest.raises(InmetAPIError):
        client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")


def test_client_retries_transient_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"CD_ESTACAO": STATION_CODE}])

    client = _make_client(handler, max_retries=5)
    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == [{"CD_ESTACAO": STATION_CODE}]
    assert call_count["n"] == 3


def test_client_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _make_client(handler, max_retries=3)

    with pytest.raises(InmetAPIError):
        client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")


def test_client_respects_retry_after_header_on_429(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "ingestion.inmet.client.time.sleep", lambda seconds: sleep_calls.append(seconds)
    )

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=[])

    client = _make_client(handler, max_retries=3)
    client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert sleep_calls == [2.0]
