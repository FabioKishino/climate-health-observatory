"""DataSUS/SIH-RD ingestion: download hospital admission records for the
configured state, filter down to the target municipalities and respiratory
diagnoses, and persist as Parquet.

Publication lag: SIH-RD data is only finalized and published by DATASUS
with a lag of roughly two months relative to the admission date —
municipalities have a window to submit and correct AIH records before a
competence (year/month) is officially closed. This is a structural
characteristic of the source, not a bug: on any given run, the most recent
one to two months of the requested window will typically come back empty
or incomplete, and will backfill automatically on later runs once DATASUS
finalizes those competences. This is the reason the DataSUS ingestion job
runs less frequently (e.g. weekly) than the INMET job in the daily
pipeline — see .github/workflows/daily-pipeline.yml.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from ingestion.datasus import config
from ingestion.datasus.client import DatasusClient
from ingestion.logging_utils import get_logger

logger = get_logger(__name__)

_RESPIRATORY_ICD10_PATTERN = re.compile(config.RESPIRATORY_ICD10_REGEX)


def filter_by_municipality(
    df: pd.DataFrame, municipality_codes: list[str] | None = None
) -> pd.DataFrame:
    """Filters admissions to those whose residence municipality (MUNIC_RES)
    matches one of the configured IBGE codes."""
    if df.empty:
        return df
    codes = municipality_codes if municipality_codes is not None else config.MUNICIPALITY_IBGE_CODES
    return df[df["MUNIC_RES"].astype(str).isin(codes)].copy()


def filter_by_respiratory_diagnosis(df: pd.DataFrame) -> pd.DataFrame:
    """Filters admissions to those whose primary diagnosis (DIAG_PRINC)
    falls within the respiratory disease chapter of ICD-10 (J00-J99)."""
    if df.empty:
        return df
    return df[
        df["DIAG_PRINC"].astype(str).str.match(_RESPIRATORY_ICD10_PATTERN, na=False)
    ].copy()


def select_and_rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Selects the relevant raw SIH-RD columns and renames them per
    config.COLUMN_RENAME_MAP, parsing the admission date into a proper
    date type."""
    renamed_columns = list(config.COLUMN_RENAME_MAP.values())
    if df.empty:
        return pd.DataFrame(columns=renamed_columns)

    selected = df[list(config.COLUMN_RENAME_MAP.keys())].rename(columns=config.COLUMN_RENAME_MAP)
    selected["admission_date"] = pd.to_datetime(
        selected["admission_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    selected["total_aih_value"] = pd.to_numeric(selected["total_aih_value"], errors="coerce")
    selected["length_of_stay"] = pd.to_numeric(selected["length_of_stay"], errors="coerce")
    return selected


def write_admissions_parquet(
    admissions: pd.DataFrame, output_dir: Path = config.RAW_DATA_DIR
) -> int:
    """Writes admission rows as Parquet, partitioned by admission month.

    Idempotent: re-running for the same competence (year/month) overwrites
    the affected partitions in place rather than appending duplicate rows.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if admissions.empty:
        logger.info("No admission rows to write", extra={"output_dir": str(output_dir)})
        return 0

    con = duckdb.connect(database=":memory:")
    try:
        con.register("admissions_df", admissions)
        con.execute(
            """
            CREATE TABLE admissions AS
            SELECT
                *,
                date_trunc('month', admission_date)::DATE AS admission_month
            FROM admissions_df
            """
        )
        con.execute(
            f"""
            COPY admissions TO '{output_dir.as_posix()}'
            (FORMAT PARQUET, PARTITION_BY (admission_month), OVERWRITE TRUE)
            """
        )
    finally:
        con.close()

    logger.info(
        "Wrote SIH-RD admissions Parquet partitions",
        extra={"output_dir": str(output_dir), "row_count": len(admissions)},
    )
    return len(admissions)


def extract_respiratory_admissions(
    start_year_month: tuple[int, int],
    end_year_month: tuple[int, int],
    output_dir: Path = config.RAW_DATA_DIR,
) -> int:
    """Downloads, filters, and persists respiratory-cause hospital
    admissions for the configured municipalities, across an inclusive
    range of (year, month) competences. Returns the number of rows written.
    """
    logger.info(
        "Starting DataSUS/SIH-RD extraction",
        extra={
            "uf": config.UF,
            "start_year_month": start_year_month,
            "end_year_month": end_year_month,
            "municipality_codes": config.MUNICIPALITY_IBGE_CODES,
        },
    )

    client = DatasusClient()
    filtered_frames: list[pd.DataFrame] = []

    for year, month in _month_range(start_year_month, end_year_month):
        raw = client.download_state_month(year, month)
        if raw.empty:
            continue

        municipality_filtered = filter_by_municipality(raw)
        respiratory_filtered = filter_by_respiratory_diagnosis(municipality_filtered)
        logger.info(
            "Filtered SIH-RD competence",
            extra={
                "year": year,
                "month": month,
                "raw_row_count": len(raw),
                "municipality_row_count": len(municipality_filtered),
                "respiratory_row_count": len(respiratory_filtered),
            },
        )
        if not respiratory_filtered.empty:
            filtered_frames.append(respiratory_filtered)

    if not filtered_frames:
        logger.warning("No respiratory admissions found across the requested range")
        return write_admissions_parquet(pd.DataFrame(), output_dir=output_dir)

    combined = pd.concat(filtered_frames, ignore_index=True)
    admissions = select_and_rename_columns(combined)
    return write_admissions_parquet(admissions, output_dir=output_dir)


def _month_range(
    start_year_month: tuple[int, int], end_year_month: tuple[int, int]
) -> list[tuple[int, int]]:
    """Returns an inclusive list of (year, month) tuples between two
    (year, month) points."""
    start_year, start_month = start_year_month
    end_year, end_month = end_year_month
    start = start_year * 12 + (start_month - 1)
    end = end_year * 12 + (end_month - 1)
    if start > end:
        raise ValueError(f"start {start_year_month} is after end {end_year_month}")
    return [(m // 12, m % 12 + 1) for m in range(start, end + 1)]


def _default_24_month_range() -> tuple[tuple[int, int], tuple[int, int]]:
    """Defaults to the 24 months ending with the most recent fully-elapsed
    calendar month."""
    today = date.today()
    end_year, end_month = today.year, today.month - 1
    if end_month == 0:
        end_year, end_month = end_year - 1, 12

    start_total = end_year * 12 + (end_month - 1) - 23
    start_year, start_month = start_total // 12, start_total % 12 + 1
    return (start_year, start_month), (end_year, end_month)


def main() -> None:
    default_start, default_end = _default_24_month_range()

    parser = argparse.ArgumentParser(
        description="Run the DataSUS/SIH-RD respiratory admissions extraction."
    )
    parser.add_argument("--start-year", type=int, default=default_start[0])
    parser.add_argument("--start-month", type=int, default=default_start[1])
    parser.add_argument("--end-year", type=int, default=default_end[0])
    parser.add_argument("--end-month", type=int, default=default_end[1])
    args = parser.parse_args()

    row_count = extract_respiratory_admissions(
        start_year_month=(args.start_year, args.start_month),
        end_year_month=(args.end_year, args.end_month),
    )
    logger.info("DataSUS/SIH-RD extraction finished", extra={"row_count": row_count})


if __name__ == "__main__":
    # Run as a module from the repo root (`python -m ingestion.datasus.extract`),
    # not as a bare script path — the absolute `ingestion.*` imports above
    # only resolve when the repo root is on sys.path, which `-m` guarantees
    # and a direct `python ingestion/datasus/extract.py` invocation does not.
    main()
