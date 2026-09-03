# 0001 — DuckDB + MotherDuck as the Analytics Storage Layer

## Status

Accepted

## Context

The Climate x Public Health Observatory needs an analytics storage layer to
hold the transformed climate (INMET) and hospital admissions (DataSUS/SIH-RD)
data that dbt models will read from and write to, and that the frontend
dashboard will query.

The initial scope is deliberately narrow:

- **Geographic scope:** a single municipality (Curitiba, PR), with the data
  model designed to allow expansion to the Curitiba Metropolitan Region or
  the full state of Paraná, but that expansion is not implemented yet.
- **Time scope:** the last 24 months of data.
- **Write concurrency:** a single daily (or weekly, for DataSUS) batch job
  writes the data. There are no concurrent writers, and the only readers are
  the dbt build process and a read-only public dashboard.
- **Budget:** this is a personal portfolio project with a hard constraint of
  $0/month in infrastructure cost.

Given this profile, the expected data volume is low-to-medium: daily
aggregated climate readings for a handful of weather stations, and monthly
batches of hospital admission records for one municipality, over 24 months.
This is a dataset in the tens-of-thousands-of-rows range, not the
hundreds-of-millions range.

## Decision

We will use **DuckDB** as the local/embedded analytical engine and
**MotherDuck** (free tier) as the hosted counterpart, so that:

- dbt runs (via the `dbt-duckdb` adapter) can execute locally against a
  DuckDB file during development, and against the MotherDuck-hosted database
  in CI/CD and production, using the same SQL and the same adapter — no
  query rewriting between environments.
- The frontend and any ad-hoc analysis can query the same MotherDuck database
  directly, without standing up a separate query service.
- No infrastructure needs to be provisioned, patched, or paid for: MotherDuck's
  free tier is sufficient for this project's storage and compute footprint.

## Consequences

**Positive:**

- Zero infrastructure cost, matching the project's budget constraint.
- `dbt-duckdb` is a first-class, actively maintained adapter — no custom
  integration work needed.
- DuckDB's columnar, vectorized execution engine is well suited to the
  analytical (aggregate-heavy, read-mostly) workload this project has,
  despite the small data volume — it's a genuinely fast engine, not just a
  "good enough for a toy project" choice.
- Local development is simple: a single `.duckdb` file, no Docker container
  or cloud credentials required to iterate on dbt models.
- MotherDuck is a technology that has been gaining real market traction, so
  using it is a relevant signal of technical currency for a portfolio
  project, beyond being merely the cheapest option.

**Negative / trade-offs accepted:**

- **No concurrent multi-writer support.** DuckDB is designed around a
  single-writer model (one process holds the write lock on a given
  database). This is a non-issue for a pipeline with one scheduled batch
  writer, but it would be a real limitation for a system with multiple
  services writing concurrently.
- **Not built for very large volumes.** DuckDB comfortably handles datasets
  from megabytes up to tens of gigabytes on a single node, but it is not a
  distributed engine. A dataset in the hundreds-of-GB-or-larger range, or a
  workload requiring horizontal scale-out, would outgrow this architecture.
- **MotherDuck free tier limits.** The free tier caps storage and compute;
  if usage grows (more states, longer history, heavier dashboard traffic),
  the project would need to move to a paid MotherDuck tier or reconsider the
  storage layer entirely.
- **Less "enterprise-standard" than a cloud data warehouse.** Snowflake and
  BigQuery are more common in large-scale production environments, so this
  choice trades some resume-keyword familiarity for a simpler, cheaper, and
  arguably more interesting-to-discuss architecture for this project's
  actual scale.

## Alternatives Considered

### Snowflake / BigQuery

Industry-standard cloud data warehouses with strong dbt support and native
elastic scaling. Rejected for this project because:

- Both require either a credit card / billing account or careful usage caps
  to stay within a free tier, adding operational overhead disproportionate
  to a low-volume personal project.
- Their key strength — elastic scale for large concurrent workloads — is
  not exercised at all by this project's volume and single-writer access
  pattern, so the added complexity would not be justified.

### Supabase (managed Postgres)

Considered as a lower-cost, still fully-managed alternative. Rejected
because:

- Postgres is a row-oriented OLTP engine; it is not optimized for the
  aggregate-heavy analytical queries (time series joins, groupings across
  the star schema) that this project's dbt models and dashboard perform.
  DuckDB's columnar engine is a better technical fit for that access
  pattern.
- dbt support for DuckDB (`dbt-duckdb`) is equally mature for this project's
  needs, and using DuckDB/MotherDuck keeps local development and hosted
  production on the exact same engine, whereas a Postgres-based setup would
  still likely use a local DuckDB or SQLite file for fast local dbt
  iteration, introducing an engine mismatch between environments.

## When to Revisit

This decision should be reassessed if any of the following becomes true:

- The project expands beyond a single Brazilian state and/or beyond 5 years
  of historical data (i.e., data volume grows from tens of thousands of rows
  toward the hundreds-of-millions range).
- The pipeline needs concurrent multi-writer access (e.g., multiple ingestion
  jobs writing to the same tables at the same time, or multiple teams/services
  owning different parts of the pipeline).
- MotherDuck's free tier storage or compute limits are consistently exceeded
  by normal operation.

If any of these conditions is met, the recommended next step is to evaluate
a distributed cloud data warehouse (BigQuery or Snowflake), since at that
point their elastic scaling and multi-writer concurrency would justify their
added cost and operational complexity.
