"""Tests for the INMET ingestion module. No real HTTP calls are made —
`httpx.MockTransport` stands in for the network."""

from __future__ import annotations

import httpx
import pytest

from ingestion.inmet.client import InmetAPIError, InmetClient
from ingestion.inmet.extract import (
    _default_date_range,
    _parse_float,
    aggregate_daily,
    extract_daily_climate,
    parse_hourly_readings,
    write_daily_climate_parquet,
)

STATION_CODE = "A807"


def _make_client(handler, **kwargs) -> InmetClient:
    return InmetClient(transport=httpx.MockTransport(handler), **kwargs)


def _raw_hourly_record(**overrides) -> dict:
    record = {
        "CD_ESTACAO": STATION_CODE,
        "DC_NOME": "CURITIBA",
        "UF": "PR",
        "VL_LATITUDE": "-25.42",
        "VL_LONGITUDE": "-49.27",
        "DT_MEDICAO": "2024-05-01",
        "HR_MEDICAO": "1200",
        "TEM_INS": "18,4",
        "TEM_MAX": "19.0",
        "TEM_MIN": "17.5",
        "UMD_INS": "80",
        "CHUVA": "0.2",
    }
    record.update(overrides)
    return record


def _reading(**overrides) -> dict:
    reading = {
        "station_code": STATION_CODE,
        "date": "2024-05-01",
        "station_name": "CURITIBA",
        "state": "PR",
        "latitude": -25.42,
        "longitude": -49.27,
        "temp_instant": 18.4,
        "temp_max": 19.0,
        "temp_min": 17.5,
        "humidity_instant": 80.0,
        "precipitation": 0.2,
    }
    reading.update(overrides)
    return reading


# --- parse_hourly_readings ---


def test_parse_hourly_readings_valid():
    parsed = parse_hourly_readings([_raw_hourly_record()], STATION_CODE)

    assert parsed == [_reading()]


def test_parse_hourly_readings_handles_missing_values():
    raw = [
        _raw_hourly_record(
            DC_NOME=None,
            UF=None,
            VL_LATITUDE=None,
            VL_LONGITUDE=None,
            TEM_INS=None,
            TEM_MAX="",
            TEM_MIN=None,
            UMD_INS=None,
            CHUVA=None,
        )
    ]

    parsed = parse_hourly_readings(raw, STATION_CODE)

    assert parsed[0]["station_name"] is None
    assert parsed[0]["latitude"] is None
    assert parsed[0]["temp_instant"] is None
    assert parsed[0]["temp_max"] is None
    assert parsed[0]["precipitation"] is None


def test_parse_hourly_readings_skips_records_without_date():
    raw = [{"CD_ESTACAO": STATION_CODE, "DT_MEDICAO": "", "TEM_INS": "20"}]

    parsed = parse_hourly_readings(raw, STATION_CODE)

    assert parsed == []


def test_parse_hourly_readings_empty_response():
    assert parse_hourly_readings([], STATION_CODE) == []


# --- _parse_float ---


def test_parse_float_passes_through_numeric_types():
    assert _parse_float(18) == 18.0
    assert _parse_float(18.5) == 18.5


def test_parse_float_returns_none_for_unparseable_string():
    assert _parse_float("not-a-number") is None


# --- aggregate_daily ---


def test_aggregate_daily_computes_expected_metrics():
    readings = [
        _reading(temp_instant=15.0, temp_max=20.0, temp_min=10.0, humidity_instant=70.0, precipitation=1.0),
        _reading(temp_instant=25.0, temp_max=26.0, temp_min=12.0, humidity_instant=90.0, precipitation=None),
    ]

    [daily] = aggregate_daily(readings)

    assert daily["station_code"] == STATION_CODE
    assert daily["date"] == "2024-05-01"
    assert daily["station_name"] == "CURITIBA"
    assert daily["state"] == "PR"
    assert daily["latitude"] == -25.42
    assert daily["longitude"] == -49.27
    assert daily["avg_temp"] == 20.0
    assert daily["min_temp"] == 10.0
    assert daily["max_temp"] == 26.0
    assert daily["avg_relative_humidity"] == 80.0
    assert daily["total_precipitation"] == 1.0


def test_aggregate_daily_carries_forward_metadata_from_a_later_reading_if_first_is_missing_it():
    readings = [
        _reading(station_name=None, state=None, latitude=None, longitude=None),
        _reading(station_name="CURITIBA", state="PR", latitude=-25.42, longitude=-49.27),
    ]

    [daily] = aggregate_daily(readings)

    assert daily["station_name"] == "CURITIBA"
    assert daily["latitude"] == -25.42


def test_aggregate_daily_falls_back_to_instant_temp_when_min_max_missing():
    readings = [
        _reading(date="2024-05-02", temp_instant=12.0, temp_max=None, temp_min=None,
                  humidity_instant=None, precipitation=None),
        _reading(date="2024-05-02", temp_instant=18.0, temp_max=None, temp_min=None,
                  humidity_instant=None, precipitation=None),
    ]

    [daily] = aggregate_daily(readings)

    assert daily["min_temp"] == 12.0
    assert daily["max_temp"] == 18.0
    assert daily["avg_relative_humidity"] is None
    assert daily["total_precipitation"] is None


def test_aggregate_daily_groups_by_station_and_date():
    readings = [
        _reading(station_code="A807", temp_instant=10.0, temp_max=10.0, temp_min=10.0),
        _reading(station_code="A999", temp_instant=30.0, temp_max=30.0, temp_min=30.0),
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


def test_client_falls_back_to_backoff_when_retry_after_is_not_numeric(monkeypatch):
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "ingestion.inmet.client.time.sleep", lambda seconds: sleep_calls.append(seconds)
    )

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Per HTTP spec, Retry-After may be an HTTP-date instead of seconds.
            return httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        return httpx.Response(200, json=[])

    client = _make_client(handler, max_retries=3, backoff_factor=1.0)
    client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= 1.0  # fell back to exponential backoff, not a parsed date


def test_client_retries_transport_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=[])

    client = _make_client(handler, max_retries=3)
    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == []
    assert call_count["n"] == 2


def test_client_context_manager_closes_underlying_httpx_client():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with _make_client(handler) as client:
        assert client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01") == []

    assert client._client.is_closed


# --- write_daily_climate_parquet ---


def test_write_daily_climate_parquet_writes_partitioned_and_idempotent(tmp_path):
    import duckdb

    rows = [
        {
            "station_code": STATION_CODE,
            "date": "2024-05-01",
            "station_name": "CURITIBA",
            "state": "PR",
            "latitude": -25.42,
            "longitude": -49.27,
            "avg_temp": 18.0,
            "min_temp": 12.0,
            "max_temp": 24.0,
            "avg_relative_humidity": 80.0,
            "total_precipitation": 1.5,
        }
    ]

    write_daily_climate_parquet(rows, output_dir=tmp_path)
    row_count = write_daily_climate_parquet(rows, output_dir=tmp_path)  # rerun: idempotency check

    assert row_count == 1
    assert list(tmp_path.glob("date=2024-05-01/*.parquet"))

    result = duckdb.connect().execute(
        f"SELECT station_code, station_name, avg_temp FROM read_parquet('{tmp_path.as_posix()}/**/*.parquet')"
    ).fetchall()
    assert result == [(STATION_CODE, "CURITIBA", 18.0)]


def test_write_daily_climate_parquet_handles_empty_rows(tmp_path):
    assert write_daily_climate_parquet([], output_dir=tmp_path) == 0


# --- extract_daily_climate (orchestration, client faked) ---


class _FakeInmetClient:
    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self._responses = responses

    def __enter__(self) -> "_FakeInmetClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def get_station_readings(self, station_code, start_date, end_date):
        return self._responses.get(station_code, [])


def test_extract_daily_climate_orchestrates_fetch_aggregate_and_write(monkeypatch, tmp_path):
    responses = {
        "A807": [
            {
                "CD_ESTACAO": "A807",
                "DC_NOME": "CURITIBA",
                "UF": "PR",
                "VL_LATITUDE": "-25.42",
                "VL_LONGITUDE": "-49.27",
                "DT_MEDICAO": "2024-05-01",
                "TEM_INS": "20.0",
                "TEM_MAX": "25.0",
                "TEM_MIN": "15.0",
                "UMD_INS": "70",
                "CHUVA": "0.0",
            }
        ],
        "A999": [],  # empty response for a second station: should not break the run
    }
    monkeypatch.setattr(
        "ingestion.inmet.extract.InmetClient", lambda: _FakeInmetClient(responses)
    )

    row_count = extract_daily_climate(
        station_codes=["A807", "A999"],
        start_date="2024-05-01",
        end_date="2024-05-01",
        output_dir=tmp_path,
    )

    assert row_count == 1
    [parquet_file] = tmp_path.glob("date=2024-05-01/*.parquet")

    import duckdb

    result = duckdb.connect().execute(
        f"SELECT station_name, latitude FROM read_parquet('{parquet_file.as_posix()}')"
    ).fetchall()
    assert result == [("CURITIBA", -25.42)]


def test_extract_daily_climate_raises_without_station_codes(tmp_path):
    with pytest.raises(ValueError):
        extract_daily_climate(
            station_codes=[],
            start_date="2024-05-01",
            end_date="2024-05-01",
            output_dir=tmp_path,
        )


# --- _default_date_range ---


def test_default_date_range_is_yesterday():
    from datetime import date, timedelta

    start, end = _default_date_range()
    expected = (date.today() - timedelta(days=1)).isoformat()

    assert start == end == expected
