"""Configuration for the INMET ingestion module.

All values can be overridden via environment variables so the same code
runs unchanged in local development, CI, and GitHub Actions.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- API ---
BASE_URL = os.getenv("INMET_BASE_URL", "https://apitempo.inmet.gov.br")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("INMET_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("INMET_MAX_RETRIES", "5"))
BACKOFF_FACTOR_SECONDS = float(os.getenv("INMET_BACKOFF_FACTOR_SECONDS", "1"))
MAX_BACKOFF_SECONDS = float(os.getenv("INMET_MAX_BACKOFF_SECONDS", "60"))

# --- Stations ---
# Curitiba's INMET automatic weather station code(s) — to be confirmed and
# filled in once identified (candidates include A807 - Curitiba). Provided
# as a comma-separated env var so it's trivial to add more stations later
# (e.g. to cover the Curitiba Metropolitan Region) without a code change.
STATION_CODES: list[str] = [
    code.strip()
    for code in os.getenv("INMET_STATION_CODES", "").split(",")
    if code.strip()
]

# --- Output ---
RAW_DATA_DIR = Path(
    os.getenv(
        "INMET_RAW_DATA_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "raw" / "inmet"),
    )
)
