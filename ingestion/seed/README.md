# INMET historical seed data

`inmet/` is a one-time backfill of daily climate readings for station A807
(Curitiba), covering 2024-05-22 through 2026-09-19 — the same Hive-partitioned
Parquet format `ingestion/inmet/extract.py` produces day-to-day. It's
committed to git deliberately, unlike the rest of `ingestion/data/` (which is
gitignored and ephemeral): this is finished history that will never change,
and INMET's own bulk archive only advances intermittently (it was still
capped at 2026-08-31 as of this backfill), so waiting for the daily pipeline
to re-accumulate it from scratch isn't practical.

The Daily Pipeline workflow copies this into `ingestion/data/raw/inmet/`
before running that day's ingestion (see `.github/workflows/daily-pipeline.yml`),
so `stg_inmet__daily_climate`'s `read_parquet()` glob always has at least this
much data to work with — DuckDB hard-errors on a glob matching zero files, so
without this seed, any gap in the GitHub Actions cache (eviction, a cold
cache on the first run after a change, etc.) would break every `dbt build`
until the cache happened to be warm again. The seed removes that single point
of failure; the cache on top of it is now purely a freshness optimization,
not a correctness requirement.

To refresh this seed with a later end date, regenerate it the same way it was
built:

```bash
python -m ingestion.inmet.extract --start-date 2024-05-22 --end-date <yesterday>
mv ingestion/data/raw/inmet/* ingestion/seed/inmet/
```
