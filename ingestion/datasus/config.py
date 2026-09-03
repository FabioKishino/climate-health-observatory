"""Configuration for the DataSUS/SIH-RD ingestion module.

All values can be overridden via environment variables so the same code
runs unchanged in local development, CI, and GitHub Actions.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Source scope ---
# SIH data is only available for download at the state level (there is no
# per-municipality download) — municipality-level filtering happens in
# extract.py, after the state-level download.
UF = os.getenv("DATASUS_UF", "PR")

# SIH-RD ("AIH Reduzida") is the reduced hospital admission record group —
# the one relevant to this project. SIH also publishes other groups (e.g.
# RJ, ER, SP) covering different AIH statuses, not needed here.
SIH_GROUP = os.getenv("DATASUS_SIH_GROUP", "RD")

# --- Filters ---
# Curitiba's IBGE municipality code. Kept as a list (not a single constant)
# so expanding to the Curitiba Metropolitan Region later is a one-line
# config change, not a code change.
MUNICIPALITY_IBGE_CODES: list[str] = [
    code.strip()
    for code in os.getenv("DATASUS_MUNICIPALITY_IBGE_CODES", "4106902").split(",")
    if code.strip()
]

# ICD-10 respiratory disease chapter (J00-J99). DIAG_PRINC values in SIH-RD
# are the ICD-10 code without punctuation (e.g. "J189"), so this pattern
# matches on the leading letter + two-digit chapter block.
RESPIRATORY_ICD10_REGEX = os.getenv("DATASUS_RESPIRATORY_ICD10_REGEX", r"^J\d{2}")

# --- Output ---
RAW_DATA_DIR = Path(
    os.getenv(
        "DATASUS_RAW_DATA_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "raw" / "datasus"),
    )
)

# --- Column selection/renaming ---
# Maps raw SIH-RD (DATASUS) column names to the descriptive names used
# downstream. N_AIH (the AIH record number) is kept as a natural key even
# though it wasn't explicitly requested, since it's needed to test/enforce
# row uniqueness in the dbt staging model.
COLUMN_RENAME_MAP: dict[str, str] = {
    "N_AIH": "aih_number",
    "MUNIC_RES": "municipality_residence_code",
    "DT_INTER": "admission_date",
    "DIAG_PRINC": "primary_diagnosis",
    "VAL_TOT": "total_aih_value",
    "DIAS_PERM": "length_of_stay",
}
