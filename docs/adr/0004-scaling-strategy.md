# 0004 — Scaling Strategy: All Brazilian States, 5+ Years of History

## Status

Accepted (as a forward-looking decision — not implemented; see Consequences)

## Context

This project is deliberately scoped to one municipality (Curitiba, PR) and
24 months of history (see SPEC.md's assumed scope, and ADR 0001/0002's own
"when to revisit" sections, both of which name this exact expansion —
"all Brazilian states and 5+ years of history" — as their trigger
condition). That's a reasonable scope for a portfolio project, but a
production version of this idea would eventually want national coverage:
every state, several years of history, to support real epidemiological
and climate research rather than a single-city demonstration.

This ADR exists to answer, in advance, "what would actually have to
change?" — recorded now, as a documented architectural decision, rather
than left as an implicit assumption or discovered under pressure later.
Four areas change materially: partitioning, storage, refresh strategy,
and orchestration.

## Decision

### Partitioning

Today's Parquet output is partitioned by date only (INMET) or admission
month only (DataSUS) — reasonable when the data belongs to a single
municipality and state. At national scope, every ingestion output and
every dbt model reading from it should additionally partition by `state`
(Hive-style: `state=PR/year=2026/month=08/...`), so that a query scoped to
one state or region can prune the other 26 states' partitions entirely
instead of scanning them. Concretely:

- `ingestion/inmet/extract.py` already downloads INMET's bulk archive one
  year at a time, and that archive already covers every station
  nationwide in a single file (see ADR 0005) — so INMET ingestion scales
  to "every station" for free today. What needs to change is persisting
  station output partitioned by state, not just by date, so downstream
  queries can prune to a region.
- `ingestion/datasus/extract.py` downloads one state at a time by design
  (SIH-RD is only published per-state) — this already produces a natural
  per-state partition; national scope just means running it once per
  state instead of once for PR, and keeping that state partition in the
  Parquet path.

### Storage: MotherDuck → a distributed warehouse

ADR 0001 named this exact scope change as its own revisit trigger,
specifically because DuckDB/MotherDuck's design center is
low-to-medium data volume with a single writer, not sustained
multi-state, multi-year, concurrently-queried analytical workloads at
national scale (tens of millions of SIH-RD rows nationally, multiplied
across 5+ years). At that volume, a distributed columnar warehouse
(BigQuery or Snowflake, per ADR 0001's own alternatives) is very likely
the better foundation: native partitioning and clustering, elastic
concurrent-query compute, and the access-control/governance features a
multi-consumer national dataset would need. **This ADR formally confirms
that threshold is crossed** under this hypothetical scope, and recommends
evaluating a warehouse migration as the first step of any real expansion
— everything else in this document assumes that migration has happened.

### Full refresh → incremental / CDC

Every dbt mart here is `materialized: table` — a full rebuild from
whatever local Parquet exists at run time — and staging models re-read
the entirety of the ingestion layer's Parquet output on every run. That's
fine at this project's volume; at national, multi-year scale it means
re-processing tens of millions of unchanged rows daily just to add a
day's or a week's worth of new admissions, which is both slow and
expensive on a usage-billed warehouse.

The fix is incremental models with real change-detection, not just a
config flag:

- `fct_respiratory_admissions` and `fct_daily_climate` should become
  `materialized: incremental` with `unique_key` (`aih_number`,
  `station_code, date_day`) and a `merge` incremental strategy, so a run
  only inserts/updates the rows that actually changed.
- That only works if the ingestion layer can tell dbt which rows are new
  or changed. SIH-RD is republished per (state, competence-month), and
  competences are occasionally reprocessed/corrected after their first
  publication (see `_drop_duplicate_admissions`'s docstring in
  `ingestion/datasus/extract.py` for a real example of this already
  happening at today's small scale) — so ingestion would need to track
  which (state, competence) pairs it has already processed and compare
  against a checksum or last-modified signal to detect a genuine change,
  not just presence, before deciding whether to re-pull a competence.
  This is a real CDC problem, not a trivial one, precisely because the
  source system allows a competence to be silently revised after the
  fact.

### Orchestration: GitHub Actions cron → a dedicated orchestrator

ADR 0002 named its own revisit triggers — more than a handful of jobs
with real dependencies, a recurring (not one-off) backfill need, or
multiple teams/consumers — and national scope hits more than one of
these directly. Ingestion becomes one job per state (27, not 1) with a
dependency into a national aggregation step; backfilling 5+ years across
27 states on introduction of a new column or a bug fix becomes a routine
operational task, not a rare exception; and a national dataset is far
more likely to have multiple downstream consumers with their own
scheduling and retry needs. **This ADR formally confirms ADR 0002's
threshold is crossed** too, and recommends Dagster specifically, per
ADR 0002's own reasoning — its asset-centric model maps naturally onto
the dbt models this project already has.

### Also worth naming: observability and the frontend

Two smaller but real consequences, out of scope for ADR 0003 and Prompt 9
respectively but worth recording here:

- **Observability** would need per-state (or per-job) granularity rather
  than one Telegram channel for the whole pipeline — a single state's
  ingestion failing shouldn't read the same as the whole national
  pipeline being down, and today's one-alert-fits-all design would cause
  alert fatigue at 27x the job count.
- **The frontend/API** currently aggregates `mart_climate_health_correlation`
  on every request (see `frontend/src/app/api/climate-health/route.ts`).
  At national, multi-year row counts, on-the-fly aggregation per request
  would likely need to become a pre-aggregated rollup table (e.g. a dbt
  mart already grouped to weekly/monthly grain per state/region) rather
  than aggregating the full detail table live on every dashboard load.

## Consequences

**Positive:** this ADR means the decision doesn't have to be re-derived
under time pressure if/when this project actually expands — the trade-offs
and the order of operations (warehouse migration first, since everything
else assumes it) are already thought through and recorded.

**Negative / trade-offs accepted:** none of this is implemented, and it
shouldn't be — building any of it now would be solving a scale problem
this project doesn't have, against SPEC.md's own explicit 2-4 week,
single-municipality scope. The risk this ADR accepts is the ordinary risk
of any forward-looking design doc: some of these specifics may need
revision once the actual expansion is scoped for real (e.g. the specific
choice of BigQuery vs. Snowflake, or Dagster vs. some other orchestrator,
would deserve its own dedicated ADR at that time, informed by whatever
constraints exist then).

## Alternatives Considered

**Design for this scale from day one.** Rejected, deliberately — this
would be premature optimization against a scope SPEC.md never asked for,
and every one of this project's other ADRs (0001, 0002) explicitly
reasons about staying simple until a concrete, named threshold is
crossed. This ADR *is* that reasoning, applied to the one remaining
scope dimension (state/time coverage) preemptively, precisely so it
doesn't need to be improvised later.

**Do nothing until asked.** Considered, but the project's own two other
ADRs already pointed at this exact scenario as their revisit trigger
without answering what the resulting change would actually look like —
leaving that unanswered would mean the "when to revisit" sections of
ADR 0001 and 0002 have a threshold but no plan.

## When to Revisit

When any real work toward this expansion actually begins. At that point,
this ADR should be treated as a starting brief, not a final spec — the
warehouse choice, the orchestrator choice, and the exact incremental/CDC
mechanics all deserve their own focused decision (and likely their own
ADRs) informed by whatever constraints are real at that time (budget,
team size, existing infrastructure).
