"""Tests for the INMET ingestion module. No real HTTP calls are made —
`httpx.MockTransport` stands in for the network."""

from __future__ import annotations

import io
import zipfile
from typing import Self

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

_CSV_HEADER = (
    "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);"
    "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);"
    "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C);"
    "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C);"
    "UMIDADE RELATIVA DO AR, HORARIA (%);"
)


def _build_archive_bytes(
    *,
    station_code: str = STATION_CODE,
    station_name: str = "CURITIBA",
    state: str = "PR",
    latitude: str = "-25,4486111",
    longitude: str = "-49,23055554",
    rows: tuple[tuple[str, ...], ...] = (("2024/05/01", "1200", "0,2", "18,4", "19,0", "17,5", "80"),),
) -> bytes:
    """Builds an in-memory ZIP matching INMET's real bulk archive format:
    one CSV per station, 8 metadata lines, a header, then hourly rows."""
    lines = [
        "REGIAO:;S",
        f"UF:;{state}",
        f"ESTACAO:;{station_name}",
        f"CODIGO (WMO):;{station_code}",
        f"LATITUDE:;{latitude}",
        f"LONGITUDE:;{longitude}",
        "ALTITUDE:;900,00",
        "DATA DE FUNDACAO:;01/01/03",
        _CSV_HEADER,
        *(";".join(row) + ";" for row in rows),
    ]
    csv_bytes = "\n".join(lines).encode("latin-1")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            f"INMET_S_{state}_{station_code}_{station_name}_01-01-2024_A_31-12-2024.CSV",
            csv_bytes,
        )
    return buffer.getvalue()


def _archive_handler(archives_by_year: dict[int, bytes | None], call_counts: dict[int, int] | None = None):
    """Builds a MockTransport handler serving different archive bytes (or a
    404) per year, based on the year embedded in the request URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        year = int(str(request.url).rstrip(".zip").split("/")[-1])
        if call_counts is not None:
            call_counts[year] = call_counts.get(year, 0) + 1
        content = archives_by_year.get(year)
        if content is None:
            return httpx.Response(404)
        return httpx.Response(200, content=content)

    return handler


def test_client_downloads_and_parses_station_readings():
    archive = _build_archive_bytes(
        rows=(
            ("2024/05/01", "1200", "0,2", "18,4", "19,0", "17,5", "80"),
            ("2024/05/02", "1200", "0,0", "20,0", "21,0", "19,0", "70"),
        )
    )
    client = _make_client(_archive_handler({2024: archive}))

    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-02")

    assert result == [
        {
            "CD_ESTACAO": STATION_CODE,
            "DC_NOME": "CURITIBA",
            "UF": "PR",
            "VL_LATITUDE": "-25,4486111",
            "VL_LONGITUDE": "-49,23055554",
            "DT_MEDICAO": "2024-05-01",
            "TEM_INS": "18,4",
            "TEM_MAX": "19,0",
            "TEM_MIN": "17,5",
            "UMD_INS": "80",
            "CHUVA": "0,2",
        },
        {
            "CD_ESTACAO": STATION_CODE,
            "DC_NOME": "CURITIBA",
            "UF": "PR",
            "VL_LATITUDE": "-25,4486111",
            "VL_LONGITUDE": "-49,23055554",
            "DT_MEDICAO": "2024-05-02",
            "TEM_INS": "20,0",
            "TEM_MAX": "21,0",
            "TEM_MIN": "19,0",
            "UMD_INS": "70",
            "CHUVA": "0,0",
        },
    ]


def test_client_filters_rows_outside_the_requested_date_range():
    archive = _build_archive_bytes(
        rows=(
            ("2024/04/30", "1200", "0", "10,0", "10,0", "10,0", "50"),
            ("2024/05/01", "1200", "0", "18,4", "19,0", "17,5", "80"),
            ("2024/05/03", "1200", "0", "15,0", "15,0", "15,0", "60"),
        )
    )
    client = _make_client(_archive_handler({2024: archive}))

    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert [r["DT_MEDICAO"] for r in result] == ["2024-05-01"]


def test_client_returns_empty_list_when_station_not_in_archive():
    archive = _build_archive_bytes(station_code="A999")
    client = _make_client(_archive_handler({2024: archive}))

    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == []


def test_client_returns_empty_list_when_year_not_published():
    client = _make_client(_archive_handler({2024: None}))

    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert result == []


def test_client_spans_a_year_boundary():
    archive_2023 = _build_archive_bytes(rows=(("2023/12/31", "1200", "0", "10,0", "10,0", "10,0", "50"),))
    archive_2024 = _build_archive_bytes(rows=(("2024/01/01", "1200", "0", "12,0", "12,0", "12,0", "55"),))
    client = _make_client(_archive_handler({2023: archive_2023, 2024: archive_2024}))

    result = client.get_station_readings(STATION_CODE, "2023-12-31", "2024-01-01")

    assert [r["DT_MEDICAO"] for r in result] == ["2023-12-31", "2024-01-01"]


def test_client_caches_the_archive_across_calls_for_the_same_year():
    archive = _build_archive_bytes()
    call_counts: dict[int, int] = {}
    client = _make_client(_archive_handler({2024: archive}, call_counts))

    client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")
    client.get_station_readings(STATION_CODE, "2024-05-02", "2024-05-02")

    assert call_counts == {2024: 1}


def test_client_retries_transport_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)
    archive = _build_archive_bytes()
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, content=archive)

    client = _make_client(handler, max_retries=3)
    result = client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")

    assert len(result) == 1
    assert call_count["n"] == 2


def test_client_raises_after_exhausting_retries_on_unexpected_status(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _make_client(handler, max_retries=3)

    with pytest.raises(InmetAPIError):
        client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")


def test_client_raises_after_exhausting_retries_on_transport_errors(monkeypatch):
    monkeypatch.setattr("ingestion.inmet.client.time.sleep", lambda *_args, **_kwargs: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _make_client(handler, max_retries=3)

    with pytest.raises(InmetAPIError):
        client.get_station_readings(STATION_CODE, "2024-05-01", "2024-05-01")


def test_client_context_manager_closes_underlying_httpx_client():
    with _make_client(_archive_handler({2024: None})) as client:
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

    def __enter__(self) -> Self:
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


def test_default_date_range_is_a_trailing_10_day_window_ending_yesterday():
    from datetime import UTC, datetime, timedelta

    start, end = _default_date_range()
    today = datetime.now(UTC).date()

    assert end == (today - timedelta(days=1)).isoformat()
    assert start == (today - timedelta(days=10)).isoformat()
