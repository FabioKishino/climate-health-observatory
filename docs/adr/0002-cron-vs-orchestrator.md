# 0002 — GitHub Actions Cron Instead of a Dedicated Orchestrator

## Status

Accepted

## Context

The pipeline has two ingestion sources with very different update
frequencies and characteristics:

- **INMET (climate):** a REST API that publishes new daily readings
  reliably, roughly one day in arrears. Ingestion is a single-step job:
  fetch, aggregate to daily granularity, write Parquet.
- **DataSUS/SIH-RD (hospital admissions):** files published with a lag of
  roughly two months, downloaded and filtered via `pysus`. Because of the
  lag, this job only needs to run infrequently (e.g., weekly) to stay
  current.

After ingestion, both feed into a single `dbt build` step (staging →
intermediate → marts), followed by observability checks (Elementary,
healthchecks.io ping, Telegram alert on failure).

This gives the pipeline exactly two independent schedules and one shared
downstream transformation step — a small, linear dependency graph with no
branching logic, no dynamic task generation, no cross-pipeline backfills,
and a single consumer (this project's own dashboard).

## Decision

We will use **GitHub Actions with `cron` schedules** (`daily-pipeline.yml`)
for orchestration, instead of a dedicated workflow orchestrator such as
Airflow or Dagster.

Concretely: two scheduled triggers (daily for INMET, weekly for DataSUS)
within GitHub Actions, each running its ingestion step, followed by a shared
`dbt build` + observability step, using GitHub Secrets for credentials.

## Consequences

**Positive:**

- Zero additional infrastructure: no Airflow/Dagster instance to deploy,
  patch, or pay for (a scheduler service, metadata database, and web UI
  would all need hosting).
- The pipeline definition lives next to the code it runs, version-controlled
  in the same repository, reviewed through the same PR process as everything
  else.
- GitHub Actions' cron scheduling, manual dispatch, secrets management, and
  run history/logs already cover everything this pipeline's two schedules
  need.
- Lower learning curve to read and modify: a `.yml` workflow file is legible
  to any contributor familiar with GitHub Actions, without needing to learn
  a DAG-authoring framework.

**Negative / trade-offs accepted:**

- No built-in DAG visualization, task-level retry policies, or dependency
  graph UI beyond what a linear GitHub Actions job provides.
- No native backfill tooling — re-running a historical date range means
  manually triggering workflow_dispatch with parameters, rather than an
  orchestrator's built-in backfill command.
- Limited to GitHub Actions' scheduling guarantees (cron triggers on GitHub
  Actions are best-effort and can be delayed under platform load), which is
  acceptable for a daily/weekly cadence but would not suit latency-sensitive
  scheduling.
- No shared state/XCom-style data passing between jobs beyond artifacts and
  the database itself — fine for this pipeline's simple linear flow, but
  would become awkward for a pipeline with many interdependent tasks.

## Alternatives Considered

### Airflow

The de facto industry-standard workflow orchestrator, with rich DAG
authoring, retries, backfills, sensors, and a large ecosystem of operators.
Rejected for this project's current stage because:

- It requires a persistent service (scheduler, webserver, metadata DB) to be
  hosted somewhere, which conflicts with the project's zero-infrastructure,
  zero-cost constraint.
- Its core strengths — complex dependency graphs across many tasks, dynamic
  task generation, sophisticated backfill/retry semantics — are not needed
  by a pipeline with two independent schedules and one shared linear
  transformation step.

### Dagster

A more modern orchestrator with strong data-asset-centric modeling (closer
in philosophy to dbt itself) and a lighter local footprint than Airflow.
Rejected for the same core reason as Airflow: running it in a "serverless"
managed form still means either paying for Dagster Cloud or self-hosting,
neither of which is justified by this project's two-schedule, no-branching
dependency graph. It remains a strong candidate if the pipeline's
complexity grows (see below).

## When to Revisit

This decision should be reassessed if any of the following becomes true:

- The pipeline grows to more than a handful of jobs with real dependencies
  between them (e.g., N+ interdependent tasks where GitHub Actions'
  `needs:` graph becomes hard to reason about).
- Backfilling historical data becomes a recurring operational need rather
  than a rare, manual, one-off action — i.e., the pipeline needs first-class
  backfill tooling, not a scripted workaround.
- More than one team or project starts consuming or contributing to the same
  pipeline, at which point a shared orchestrator with proper task-level
  observability, ownership, and access control becomes valuable.

If any of these conditions is met, the recommended next step is to evaluate
Dagster first (given its asset-centric model aligns naturally with the dbt
models this project already has), with Airflow as the fallback if broader
ecosystem/operator support is needed.
