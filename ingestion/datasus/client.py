"""Data client wrapping `pysus.ftp.sih` for SIH-RD (hospital admissions)
downloads.

`pysus` handles locating, downloading, and parsing DataSUS's SIH files
(originally distributed as `.dbc` files) and returns them as a pandas
DataFrame. SIH data is only published at the state level — there is no
per-municipality download — so this client always fetches an entire state
for one (year, month) competence; `extract.py` is responsible for filtering
down to specific municipalities and diagnoses.
"""

from __future__ import annotations

import pandas as pd

from ingestion.datasus import config
from ingestion.logging_utils import get_logger

logger = get_logger(__name__)

# Raw SIH-RD columns requested from pysus, kept minimal to reduce memory and
# network usage. See config.COLUMN_RENAME_MAP for what each column means.
RAW_COLUMNS = list(config.COLUMN_RENAME_MAP.keys())


class DatasusClientError(Exception):
    """Raised when a SIH-RD download via pysus fails."""


class DatasusClient:
    """Thin wrapper around pysus's SIH-RD (`group="RD"`) fetcher."""

    def __init__(self, uf: str = config.UF, group: str = config.SIH_GROUP) -> None:
        self.uf = uf
        self.group = group

    def download_state_month(self, year: int, month: int) -> pd.DataFrame:
        """Downloads one (year, month) competence of SIH-RD records for the
        configured state. Returns an empty DataFrame (not an error) if the
        competence has no published data yet — this is expected for recent
        months, given SIH's ~2-month publication lag."""
        import pysus  # imported lazily: importing pysus triggers cache setup on disk

        try:
            result = pysus.ftp.sih(
                state=self.uf,
                year=year,
                month=[month],
                group=self.group,
                columns=RAW_COLUMNS,
                as_dataframe=True,
                show_progress=False,
            )
        except Exception as exc:  # pysus surfaces assorted network/parsing errors
            logger.error(
                "SIH-RD download failed",
                extra={"uf": self.uf, "year": year, "month": month, "error": str(exc)},
            )
            raise DatasusClientError(
                f"Failed to download SIH-RD data for {self.uf} {year}-{month:02d}"
            ) from exc

        df = result if isinstance(result, pd.DataFrame) else pd.DataFrame(columns=RAW_COLUMNS)

        if df.empty:
            logger.warning(
                "SIH-RD download returned no records",
                extra={"uf": self.uf, "year": year, "month": month},
            )
        else:
            logger.info(
                "Downloaded SIH-RD records",
                extra={"uf": self.uf, "year": year, "month": month, "row_count": len(df)},
            )

        return df
