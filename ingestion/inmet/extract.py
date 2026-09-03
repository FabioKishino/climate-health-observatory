"""INMET ingestion: fetch hourly station readings, aggregate to daily
granularity, and persist as Parquet.

Raw hourly records from the INMET API use these fields (Portuguese
abbreviations, as returned by the API — kept as-is at the parsing boundary,
translated to English at the staging layer in dbt):

    CD_ESTACAO   station code
    DC_NOME      station name
    UF           station state (two-letter abbreviation)
    VL_LATITUDE  station latitude
    VL_LONGITUDE station longitude
    DT_MEDICAO   measurement date ("YYYY-MM-DD")
    HR_MEDICAO   measurement hour ("HHMM", UTC)
    TEM_INS      instant air temperature (deg C)
    TEM_MAX      hourly max air temperature (deg C)
    TEM_MIN      hourly min air temperature (deg C)
    UMD_INS      instant relative humidity (%)
    CHUVA        hourly accumulated precipitation (mm)

Station metadata (name, state, coordinates) is repeated on every hourly
record rather than served separately, so it's captured here rather than via
a second call to INMET's station-catalog endpoint.

Numeric fields are sometimes returned as `null`/empty strings when a sensor
reading is missing — this is a normal characteristic of the source, not a
bug, and is handled by treating missing values as `None` and excluding them
from aggregation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from ingestion.inmet import config
from ingestion.inmet.client import InmetClient
from ingestion.logging_utils import get_logger

logger = get_logger(__name__)


def _parse_float(value: Any) -> float | None:
    """Parses an INMET numeric field, tolerating None, empty strings, and
    comma-decimal formatting."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_hourly_readings(
    raw_records: list[dict[str, Any]], station_code: str
) -> list[dict[str, Any]]:
    """Normalizes raw INMET hourly JSON records into typed dicts.

    Records with an unparseable/missing measurement date are dropped (there
    is nothing to aggregate them by), with a warning logged.
    """
    parsed: list[dict[str, Any]] = []

    for record in raw_records:
        measurement_date = record.get("DT_MEDICAO")
        if not measurement_date:
            logger.warning(
                "Skipping INMET record with missing DT_MEDICAO",
                extra={"station_code": station_code},
            )
            continue

        parsed.append(
            {
                "station_code": station_code,
                "date": measurement_date,
                "station_name": record.get("DC_NOME") or None,
                "state": record.get("UF") or None,
                "latitude": _parse_float(record.get("VL_LATITUDE")),
                "longitude": _parse_float(record.get("VL_LONGITUDE")),
                "temp_instant": _parse_float(record.get("TEM_INS")),
                "temp_max": _parse_float(record.get("TEM_MAX")),
                "temp_min": _parse_float(record.get("TEM_MIN")),
                "humidity_instant": _parse_float(record.get("UMD_INS")),
                "precipitation": _parse_float(record.get("CHUVA")),
            }
        )

    return parsed


def aggregate_daily(readings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregates parsed hourly readings to one row per (station_code, date).

    - avg_temp: mean of the hourly instant temperature readings
    - min_temp: min of the hourly TEM_MIN readings (falls back to the
      instant readings if TEM_MIN was never reported that day)
    - max_temp: max of the hourly TEM_MAX readings (same fallback)
    - avg_relative_humidity: mean of the hourly instant humidity readings
    - total_precipitation: sum of the hourly precipitation readings
      (missing hourly readings contribute 0, since no reading typically
      means no precipitation was recorded, not that the sensor failed)

    Station metadata (name, state, coordinates) is constant across a
    station's hourly readings, so it's carried forward from the first
    reading in the group that actually has it set.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for reading in readings:
        groups[(reading["station_code"], reading["date"])].append(reading)

    daily_rows: list[dict[str, Any]] = []
    for (station_code, measurement_date), group in groups.items():
        temp_instants = [r["temp_instant"] for r in group if r["temp_instant"] is not None]
        temp_maxes = [r["temp_max"] for r in group if r["temp_max"] is not None]
        temp_mins = [r["temp_min"] for r in group if r["temp_min"] is not None]
        humidity_instants = [
            r["humidity_instant"] for r in group if r["humidity_instant"] is not None
        ]
        precipitations = [r["precipitation"] for r in group if r["precipitation"] is not None]

        daily_rows.append(
            {
                "station_code": station_code,
                "date": measurement_date,
                "station_name": _first_non_null(r["station_name"] for r in group),
                "state": _first_non_null(r["state"] for r in group),
                "latitude": _first_non_null(r["latitude"] for r in group),
                "longitude": _first_non_null(r["longitude"] for r in group),
                "avg_temp": _mean(temp_instants),
                "min_temp": min(temp_mins) if temp_mins else _min_or_none(temp_instants),
                "max_temp": max(temp_maxes) if temp_maxes else _max_or_none(temp_instants),
                "avg_relative_humidity": _mean(humidity_instants),
                "total_precipitation": sum(precipitations) if precipitations else None,
            }
        )

    return daily_rows


def _first_non_null(values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _min_or_none(values: list[float]) -> float | None:
    return min(values) if values else None


def _max_or_none(values: list[float]) -> float | None:
    return max(values) if values else None


def write_daily_climate_parquet(
    daily_rows: list[dict[str, Any]], output_dir: Path = config.RAW_DATA_DIR
) -> int:
    """Writes daily climate rows as Parquet, partitioned by date.

    Idempotent: re-running for the same period overwrites the affected
    date partitions in place rather than appending duplicate files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not daily_rows:
        logger.info("No daily climate rows to write", extra={"output_dir": str(output_dir)})
        return 0

    con = duckdb.connect(database=":memory:")
    try:
        con.execute(
            """
            CREATE TABLE daily_climate (
                station_code VARCHAR,
                date DATE,
                station_name VARCHAR,
                state VARCHAR,
                latitude DOUBLE,
                longitude DOUBLE,
                avg_temp DOUBLE,
                min_temp DOUBLE,
                max_temp DOUBLE,
                avg_relative_humidity DOUBLE,
                total_precipitation DOUBLE
            )
            """
        )
        con.executemany(
            """
            INSERT INTO daily_climate
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["station_code"],
                    row["date"],
                    row["station_name"],
                    row["state"],
                    row["latitude"],
                    row["longitude"],
                    row["avg_temp"],
                    row["min_temp"],
                    row["max_temp"],
                    row["avg_relative_humidity"],
                    row["total_precipitation"],
                )
                for row in daily_rows
            ],
        )
        con.execute(
            f"""
            COPY daily_climate TO '{output_dir.as_posix()}'
            (FORMAT PARQUET, PARTITION_BY (date), OVERWRITE TRUE)
            """
        )
    finally:
        con.close()

    logger.info(
        "Wrote daily climate Parquet partitions",
        extra={"output_dir": str(output_dir), "row_count": len(daily_rows)},
    )
    return len(daily_rows)


def extract_daily_climate(
    station_codes: list[str],
    start_date: str,
    end_date: str,
    output_dir: Path = config.RAW_DATA_DIR,
) -> int:
    """Fetches, aggregates, and persists daily climate data for the given
    stations and date range. Returns the number of daily rows written."""
    if not station_codes:
        raise ValueError(
            "No INMET station codes configured. Set the INMET_STATION_CODES "
            "environment variable (see ingestion/inmet/config.py)."
        )

    logger.info(
        "Starting INMET extraction",
        extra={
            "station_codes": station_codes,
            "start_date": start_date,
            "end_date": end_date,
        },
    )

    all_readings: list[dict[str, Any]] = []
    with InmetClient() as client:
        for station_code in station_codes:
            raw_records = client.get_station_readings(station_code, start_date, end_date)
            if not raw_records:
                logger.warning(
                    "No readings returned for station",
                    extra={"station_code": station_code},
                )
                continue

            parsed = parse_hourly_readings(raw_records, station_code)
            all_readings.extend(parsed)
            logger.info(
                "Fetched hourly readings for station",
                extra={"station_code": station_code, "reading_count": len(parsed)},
            )

    daily_rows = aggregate_daily(all_readings)
    return write_daily_climate_parquet(daily_rows, output_dir=output_dir)


def _default_date_range() -> tuple[str, str]:
    """Defaults to yesterday only, matching INMET's ~1-day publication lag."""
    yesterday = date.today() - timedelta(days=1)
    return yesterday.isoformat(), yesterday.isoformat()


def main() -> None:
    default_start, default_end = _default_date_range()

    parser = argparse.ArgumentParser(description="Run the INMET daily climate extraction.")
    parser.add_argument("--start-date", default=default_start, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end-date", default=default_end, help="YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    row_count = extract_daily_climate(
        station_codes=config.STATION_CODES,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    logger.info("INMET extraction finished", extra={"row_count": row_count})


if __name__ == "__main__":
    main()
