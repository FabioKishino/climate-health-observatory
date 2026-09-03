"""HTTP client for INMET's public weather station API.

INMET (apitempo.inmet.gov.br) exposes hourly automatic weather station
readings at:

    GET /estacao/{startDate}/{endDate}/{stationCode}

This client wraps that endpoint with timeout handling, exponential backoff
retries (with jitter) on transient failures, and explicit handling of
HTTP 429 rate limiting via the `Retry-After` header.
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from ingestion.inmet import config
from ingestion.logging_utils import get_logger

logger = get_logger(__name__)

# Server errors and connection-level failures are considered transient and
# are retried. 4xx errors (other than 429) indicate a bad request and are
# not retried.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class InmetAPIError(Exception):
    """Raised when the INMET API request fails after all retries are exhausted."""


class InmetClient:
    """Thin HTTP client for the INMET automatic weather station API."""

    def __init__(
        self,
        base_url: str = config.BASE_URL,
        timeout: float = config.REQUEST_TIMEOUT_SECONDS,
        max_retries: int = config.MAX_RETRIES,
        backoff_factor: float = config.BACKOFF_FACTOR_SECONDS,
        max_backoff: float = config.MAX_BACKOFF_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def __enter__(self) -> "InmetClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_station_readings(
        self, station_code: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """Fetches hourly readings for a station between two dates (inclusive).

        Dates must be in "YYYY-MM-DD" format, matching the API's contract.
        Returns an empty list if the API returns no readings for the period.
        """
        url = f"{self.base_url}/estacao/{start_date}/{end_date}/{station_code}"
        response = self._request_with_retry(url, station_code=station_code)
        data = response.json()
        return data or []

    def _request_with_retry(self, url: str, *, station_code: str) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "INMET request failed with a transport error",
                    extra={"station_code": station_code, "attempt": attempt, "error": str(exc)},
                )
                self._sleep_before_retry(attempt)
                continue

            if response.status_code == 200:
                return response

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                logger.error(
                    "INMET request failed with a non-retryable error",
                    extra={
                        "station_code": station_code,
                        "status_code": response.status_code,
                    },
                )
                raise InmetAPIError(
                    f"INMET API returned non-retryable status "
                    f"{response.status_code} for station {station_code}"
                )

            last_error = InmetAPIError(
                f"INMET API returned status {response.status_code} "
                f"for station {station_code}"
            )
            logger.warning(
                "INMET request returned a retryable error",
                extra={
                    "station_code": station_code,
                    "attempt": attempt,
                    "status_code": response.status_code,
                },
            )
            self._sleep_before_retry(attempt, response=response)

        logger.error(
            "INMET request exhausted all retries",
            extra={"station_code": station_code, "max_retries": self.max_retries},
        )
        raise InmetAPIError(
            f"INMET API request failed after {self.max_retries} attempts "
            f"for station {station_code}"
        ) from last_error

    def _sleep_before_retry(self, attempt: int, response: httpx.Response | None = None) -> None:
        if response is not None and response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    time.sleep(float(retry_after))
                    return
                except ValueError:
                    pass

        # Exponential backoff with jitter, capped at max_backoff.
        delay = min(self.backoff_factor * (2 ** (attempt - 1)), self.max_backoff)
        delay += random.uniform(0, delay * 0.1)
        time.sleep(delay)
