"""Configuration for the INMET ingestion module.

All values can be overridden via environment variables so the same code
runs unchanged in local development, CI, and GitHub Actions.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Data source ---
# INMET's official annual bulk historical archive (one ZIP per year, one
# CSV per station inside). See docs/adr/0005 for why this is used instead
# of INMET's live REST API (apitempo.inmet.gov.br), which was found to be
# unreliable in production.
ARCHIVE_URL_TEMPLATE = os.getenv(
    "INMET_ARCHIVE_URL_TEMPLATE",
    "https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip",
)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("INMET_TIMEOUT_SECONDS", "120"))
MAX_RETRIES = int(os.getenv("INMET_MAX_RETRIES", "3"))
BACKOFF_FACTOR_SECONDS = float(os.getenv("INMET_BACKOFF_FACTOR_SECONDS", "2"))

# --- Stations ---
# A807 is Curitiba's INMET automatic weather station. Kept as a
# comma-separated, overridable default (not hardcoded inline) so it's
# trivial to add more stations later (e.g. to cover the Curitiba
# Metropolitan Region) without a code change.
STATION_CODES: list[str] = [
    code.strip()
    for code in os.getenv("INMET_STATION_CODES", "A807").split(",")
    if code.strip()
]

# --- Output ---
RAW_DATA_DIR = Path(
    os.getenv(
        "INMET_RAW_DATA_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "raw" / "inmet"),
    )
)
