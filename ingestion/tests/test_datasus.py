"""Tests for the DataSUS/SIH-RD ingestion module. No real pysus/network
calls are made — `DatasusClient.download_state_month` is monkeypatched to
return fixture DataFrames instead."""

from __future__ import annotations

import pandas as pd
import pytest

from ingestion.datasus.client import DatasusClient
from ingestion.datasus.extract import (
    _month_range,
    extract_respiratory_admissions,
    filter_by_municipality,
    filter_by_respiratory_diagnosis,
    select_and_rename_columns,
)

CURITIBA_CODE = "4106902"
OTHER_MUNICIPALITY_CODE = "4104808"  # Cascavel, PR — used to prove filtering excludes it


def _raw_admission(
    munic_res: str = CURITIBA_CODE,
    diag_princ: str = "J189",
    n_aih: str = "1234567890123",
    dt_inter: str = "20240115",
    val_tot: str = "1500.50",
    dias_perm: str = "5",
) -> dict:
    return {
        "N_AIH": n_aih,
        "MUNIC_RES": munic_res,
        "DT_INTER": dt_inter,
        "DIAG_PRINC": diag_princ,
        "VAL_TOT": val_tot,
        "DIAS_PERM": dias_perm,
    }


# --- filter_by_municipality ---


def test_filter_by_municipality_keeps_only_configured_codes():
    df = pd.DataFrame(
        [
            _raw_admission(munic_res=CURITIBA_CODE, n_aih="1"),
            _raw_admission(munic_res=OTHER_MUNICIPALITY_CODE, n_aih="2"),
        ]
    )

    filtered = filter_by_municipality(df, municipality_codes=[CURITIBA_CODE])

    assert list(filtered["N_AIH"]) == ["1"]


def test_filter_by_municipality_handles_empty_dataframe():
    df = pd.DataFrame(columns=["N_AIH", "MUNIC_RES"])
    assert filter_by_municipality(df, municipality_codes=[CURITIBA_CODE]).empty


# --- filter_by_respiratory_diagnosis ---


def test_filter_by_respiratory_diagnosis_keeps_j_codes():
    df = pd.DataFrame(
        [
            _raw_admission(diag_princ="J189", n_aih="1"),  # pneumonia — respiratory
            _raw_admission(diag_princ="I219", n_aih="2"),  # myocardial infarction — not respiratory
            _raw_admission(diag_princ="J449", n_aih="3"),  # COPD — respiratory
        ]
    )

    filtered = filter_by_respiratory_diagnosis(df)

    assert sorted(filtered["N_AIH"]) == ["1", "3"]


def test_filter_by_respiratory_diagnosis_handles_missing_diagnosis():
    df = pd.DataFrame([_raw_admission(diag_princ=None, n_aih="1")])
    filtered = filter_by_respiratory_diagnosis(df)
    assert filtered.empty


def test_filter_by_respiratory_diagnosis_handles_empty_dataframe():
    df = pd.DataFrame(columns=["N_AIH", "DIAG_PRINC"])
    assert filter_by_respiratory_diagnosis(df).empty


# --- select_and_rename_columns ---


def test_select_and_rename_columns_renames_and_types():
    df = pd.DataFrame(
        [_raw_admission(dt_inter="20240115", val_tot="1500.50", dias_perm="5")]
    )

    result = select_and_rename_columns(df)

    assert list(result.columns) == [
        "aih_number",
        "municipality_residence_code",
        "admission_date",
        "primary_diagnosis",
        "total_aih_value",
        "length_of_stay",
    ]
    assert str(result.loc[0, "admission_date"]) == "2024-01-15"
    assert result.loc[0, "total_aih_value"] == 1500.50
    assert result.loc[0, "length_of_stay"] == 5


def test_select_and_rename_columns_handles_empty_dataframe():
    df = pd.DataFrame(columns=["N_AIH", "MUNIC_RES", "DT_INTER", "DIAG_PRINC", "VAL_TOT", "DIAS_PERM"])
    result = select_and_rename_columns(df)
    assert result.empty
    assert "admission_date" in result.columns


# --- _month_range ---


def test_month_range_within_same_year():
    assert _month_range((2024, 1), (2024, 3)) == [(2024, 1), (2024, 2), (2024, 3)]


def test_month_range_spans_year_boundary():
    assert _month_range((2023, 11), (2024, 2)) == [
        (2023, 11),
        (2023, 12),
        (2024, 1),
        (2024, 2),
    ]


def test_month_range_rejects_inverted_range():
    with pytest.raises(ValueError):
        _month_range((2024, 3), (2024, 1))


# --- extract_respiratory_admissions (orchestration, client mocked) ---


def test_extract_respiratory_admissions_filters_and_combines_months(monkeypatch, tmp_path):
    responses = {
        (2024, 1): pd.DataFrame(
            [
                _raw_admission(munic_res=CURITIBA_CODE, diag_princ="J189", n_aih="1"),
                _raw_admission(munic_res=OTHER_MUNICIPALITY_CODE, diag_princ="J189", n_aih="2"),
            ]
        ),
        (2024, 2): pd.DataFrame(
            [_raw_admission(munic_res=CURITIBA_CODE, diag_princ="I219", n_aih="3")]
        ),
    }

    def fake_download(self, year, month):
        return responses.get((year, month), pd.DataFrame())

    monkeypatch.setattr(DatasusClient, "download_state_month", fake_download)

    row_count = extract_respiratory_admissions(
        start_year_month=(2024, 1),
        end_year_month=(2024, 2),
        output_dir=tmp_path,
    )

    # Only AIH "1" is both Curitiba and respiratory (J-code).
    assert row_count == 1

    import duckdb

    result = duckdb.connect().execute(
        f"SELECT aih_number FROM read_parquet('{tmp_path.as_posix()}/**/*.parquet')"
    ).fetchall()
    assert result == [("1",)]


def test_extract_respiratory_admissions_handles_no_matching_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        DatasusClient, "download_state_month", lambda self, year, month: pd.DataFrame()
    )

    row_count = extract_respiratory_admissions(
        start_year_month=(2024, 1),
        end_year_month=(2024, 1),
        output_dir=tmp_path,
    )

    assert row_count == 0
