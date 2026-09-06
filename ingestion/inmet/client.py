"""Data client for INMET's official bulk historical data archives.

INMET's live REST API (apitempo.inmet.gov.br) was found to be unreliable
in production during this project's development — see docs/adr/0005 for
the full investigation. Across real attempts it silently dropped
connections, returned empty (204) responses, and timed out, with three
different symptoms across three separate runs; independent sources
confirm this is a known characteristic of that undocumented, WAF-fronted
API, not a bug in this client.

This client instead downloads INMET's official annual bulk archive
(https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip) — a
static file server, a fundamentally more reliable class of service than a
dynamic per-request API sitting behind a WAF. Each ZIP contains one
semicolon-delimited, Latin-1-encoded CSV per station, named like
"INMET_S_PR_A807_CURITIBA_01-01-2026_A_31-08-2026.CSV": the first 8 lines
are station metadata (region, state, name, WMO code, coordinates,
altitude, founding date), the 9th is the column header, and the rest are
hourly readings, one row per hour.

`get_station_readings` returns records shaped exactly like the old live
API's JSON records (CD_ESTACAO, DC_NOME, UF, VL_LATITUDE, VL_LONGITUDE,
DT_MEDICAO, TEM_INS, TEM_MAX, TEM_MIN, UMD_INS, CHUVA) — matching
extract.py's parse_hourly_readings exactly — so this rewrite is confined
entirely to this module; nothing downstream needed to change.
"""

from __future__ import annotations

import csv
import io
import time
import zipfile
from datetime import date
from typing import Any, Self

import httpx

from ingestion.inmet import config
from ingestion.logging_utils import get_logger

logger = get_logger(__name__)

# A browser-like User-Agent is required — INMET's static file host, like
# its live API, sits behind a WAF that appears to block default HTTP
# client User-Agents outright.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

# Column names as they appear in the CSV header, mapped to the JSON-API
# field names extract.py's parse_hourly_readings expects.
_COLUMN_MAP = {
    "TEM_INS": "TEMPERATURA DO AR - BULBO SECO, HORARIA (°C)",
    "TEM_MAX": "TEMPERATURA MÁXIMA NA HORA ANT. (AUT) (°C)",
    "TEM_MIN": "TEMPERATURA MÍNIMA NA HORA ANT. (AUT) (°C)",
    "UMD_INS": "UMIDADE RELATIVA DO AR, HORARIA (%)",
    "CHUVA": "PRECIPITAÇÃO TOTAL, HORÁRIO (mm)",
}


class InmetAPIError(Exception):
    """Raised when an INMET bulk archive can't be downloaded or parsed."""


class InmetClient:
    """Downloads and parses INMET's official annual bulk historical archives."""

    def __init__(
        self,
        archive_url_template: str = config.ARCHIVE_URL_TEMPLATE,
        timeout: float = config.REQUEST_TIMEOUT_SECONDS,
        max_retries: int = config.MAX_RETRIES,
        backoff_factor: float = config.BACKOFF_FACTOR_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.archive_url_template = archive_url_template
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._client = httpx.Client(
            timeout=timeout, headers=_HEADERS, transport=transport, follow_redirects=True
        )
        self._archive_cache: dict[int, zipfile.ZipFile | None] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_station_readings(
        self, station_code: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """Fetches hourly readings for a station between two dates (inclusive).

        Dates must be in "YYYY-MM-DD" format. Returns an empty list if no
        archive is published for the requested year(s), the station has no
        entry in it, or no rows fall within the requested range.
        """
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        records: list[dict[str, Any]] = []
        for year in range(start.year, end.year + 1):
            archive = self._get_archive(year)
            if archive is not None:
                records.extend(self._read_station_csv(archive, station_code, start, end))
        return records

    def _get_archive(self, year: int) -> zipfile.ZipFile | None:
        if year in self._archive_cache:
            return self._archive_cache[year]

        url = self.archive_url_template.format(year=year)
        response = self._request_with_retry(url, year=year)

        if response.status_code == 404:
            logger.warning("No INMET bulk archive published for year", extra={"year": year})
            self._archive_cache[year] = None
            return None

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self._archive_cache[year] = archive
        return archive

    def _request_with_retry(self, url: str, *, year: int) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "INMET archive request failed with a transport error",
                    extra={"year": year, "attempt": attempt, "error": str(exc)},
                )
                time.sleep(self.backoff_factor * attempt)
                continue

            if response.status_code in (200, 404):
                return response

            last_error = InmetAPIError(
                f"INMET archive download for {year} returned status {response.status_code}"
            )
            logger.warning(
                "INMET archive request returned an unexpected status",
                extra={"year": year, "attempt": attempt, "status_code": response.status_code},
            )
            time.sleep(self.backoff_factor * attempt)

        logger.error(
            "INMET archive request exhausted all retries",
            extra={"year": year, "max_retries": self.max_retries},
        )
        raise InmetAPIError(
            f"Failed to download the INMET archive for {year} after {self.max_retries} attempts"
        ) from last_error

    def _read_station_csv(
        self, archive: zipfile.ZipFile, station_code: str, start: date, end: date
    ) -> list[dict[str, Any]]:
        matches = [name for name in archive.namelist() if f"_{station_code}_" in name]
        if not matches:
            logger.warning(
                "No archive entry found for station", extra={"station_code": station_code}
            )
            return []

        with archive.open(matches[0]) as f:
            lines = f.read().decode("latin-1").splitlines()

        metadata = dict(line.split(";", 1) for line in lines[:8] if ";" in line)
        station_name = metadata.get("ESTACAO:", "").strip() or None
        state = metadata.get("UF:", "").strip() or None
        latitude = metadata.get("LATITUDE:", "").strip() or None
        longitude = metadata.get("LONGITUDE:", "").strip() or None

        header = [column.strip() for column in lines[8].split(";")]
        reader = csv.DictReader(lines[9:], fieldnames=header, delimiter=";")

        records: list[dict[str, Any]] = []
        for row in reader:
            raw_date = row.get("Data")
            if not raw_date:
                continue
            try:
                measurement_date = date(*(int(part) for part in raw_date.split("/")))
            except (TypeError, ValueError):
                continue
            if not (start <= measurement_date <= end):
                continue

            records.append(
                {
                    "CD_ESTACAO": station_code,
                    "DC_NOME": station_name,
                    "UF": state,
                    "VL_LATITUDE": latitude,
                    "VL_LONGITUDE": longitude,
                    "DT_MEDICAO": measurement_date.isoformat(),
                    **{
                        json_field: row.get(csv_column)
                        for json_field, csv_column in _COLUMN_MAP.items()
                    },
                }
            )

        return records
