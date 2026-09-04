# 0003 — Three-Layer Observability

## Status

Accepted

## Context

A daily pipeline that nobody is watching is a pipeline that fails silently.
For this project to behave like something that would run in production —
not just "data reaches the dashboard" — it needs to answer three distinct
questions about its own health, each of which a different class of failure
can violate independently of the other two:

1. **Did the code that was supposed to run, run without crashing?** (e.g.
   INMET's API is down, `pysus` throws on a malformed `.dbc` file, a bug in
   the extraction logic raises an unhandled exception.)
2. **Did the pipeline run at all?** (e.g. the GitHub Actions cron trigger
   never fires, a workflow is accidentally disabled, a billing issue stops
   Actions from running.) This is the failure mode that (1) structurally
   cannot detect, because if the pipeline never starts, there is no running
   code left to report the error.
3. **Did the pipeline run, complete without crashing, and still produce
   wrong or low-quality data?** (e.g. INMET silently changes a field name
   and every row lands as `NULL`, a source table's row count drops to zero
   without erroring, `admission_date` values start arriving stale.) This is
   the failure mode that (1) and (2) both miss, because from their
   perspective everything "succeeded."

No single tool answers all three questions well, which is why this project
uses three purpose-built, complementary layers rather than trying to make
one tool cover everything.

## Decision

Three layers, each wired into a different point of the pipeline:

| Layer | Tool | Detects | Wired into |
|---|---|---|---|
| Operational failure | Telegram Bot API (`scripts/notify_telegram.py`) | An exception/non-zero exit in a pipeline step | `if: failure()` on each GitHub Actions job |
| Silent failure | healthchecks.io (`scripts/ping_healthcheck.py`) | The pipeline not running when it should have | A ping sent only at the end of a fully successful run |
| Data quality failure | Elementary (dbt package + `edr` CLI) | Schema drift, volume anomalies, stale freshness, test failures | Runs as part of `dbt build`, reported via `edr report` |

Concretely:

- **Telegram** — `scripts/notify_telegram.py` posts a message with a ✅ or
  🚨 emoji depending on `--status`, including the GitHub Actions run number
  when `GITHUB_RUN_NUMBER` is set. Called with `if: failure()` after any
  pipeline step, so a crash anywhere in the run produces an immediate,
  specific alert.
- **healthchecks.io** — `scripts/ping_healthcheck.py` sends one GET request
  to the check's ping URL, called only at the very end of a fully
  successful run. healthchecks.io alerts independently if that ping
  doesn't arrive within the expected window — it doesn't need the pipeline
  to tell it something is wrong, because the absence of a signal *is* the
  signal.
- **Elementary** — the `elementary-data/elementary` dbt package hooks into
  `dbt build`, capturing test results, freshness, and run metadata into its
  own tables; `edr report` (the separate `elementary-data[duckdb]` CLI)
  reads those tables and renders an HTML observability report. This is the
  only layer of the three that looks at the *data itself* rather than at
  whether code executed.

## Consequences

**Positive:**

- Each layer's blind spot is exactly another layer's strength: Telegram
  can't see a pipeline that never started; healthchecks.io can't see *why*
  a run failed or whether the data it produced was correct; Elementary
  can't see a pipeline that crashed before `dbt build` even ran. Together
  they cover the full failure surface.
- Each tool is used for the one thing it's actually good at, rather than
  stretching one general-purpose tool (e.g. trying to make Telegram alerts
  cover data-quality checks by parsing dbt output) to do a job it wasn't
  designed for.
- All three are free at this project's scale (Telegram Bot API, and the
  free tiers of healthchecks.io and Elementary OSS).

**Negative / trade-offs accepted:**

- Three separate systems to configure and keep working, versus one
  unified dashboard — acceptable at this project's size, but is exactly
  the kind of operational overhead that would need revisiting (e.g.
  consolidating into a platform like Datadog or a paid Elementary/dbt
  Cloud plan with built-in alerting) if the pipeline or team grew
  significantly.
- Elementary on `dbt-duckdb` needed two non-obvious local fixes, both now
  documented inline where they're configured: (1) dbt-core 1.8+ requires
  overriding the `test` materialization via
  `macros/elementary_materialization.sql`, or Elementary's result tables
  stay empty even though `dbt test` reports no errors; (2) `edr` expects
  Elementary's tables in the target's *default* schema — a custom
  `+schema: elementary` override in `dbt_project.yml` causes `edr report`
  to fail because dbt-duckdb prefixes custom schemas (e.g.
  `main_elementary`) but `edr`'s own queries don't look there.

## Alternatives Considered

### A single monitoring tool for everything (e.g. Slack + Grafana)

Rejected for this project's stage: Grafana needs a metrics/log backend to
be worth deploying, which is infrastructure this project's volume doesn't
justify (the same reasoning as ADR 0001 and 0002). Slack-only alerting
would cover the same ground as Telegram here, but not the silent-failure or
data-quality cases — a single channel that only knows "success" or
"failure" as a boolean cannot distinguish "pipeline is fine but the data
looks wrong" from either of those, which is precisely the case Elementary
exists to catch.

### Only two layers (drop Elementary)

Considered, since it's the most complex of the three to set up. Rejected
because operational + silent-failure monitoring only proves the pipeline
*ran*, not that it produced correct output — and "the pipeline ran
successfully but every admission count is now zero because a filter
regressed" is a realistic, high-value failure mode for exactly this
project's ETL-heavy shape.

## When to Revisit

This decision should be reassessed if the operational burden of running
three separate systems stops being worth it relative to the project's
size — for example, if alert volume grows enough that a unified
on-call/alerting platform becomes worth the cost, or if the project moves
to a paid dbt Cloud or Elementary Cloud plan that already bundles this
kind of monitoring.
