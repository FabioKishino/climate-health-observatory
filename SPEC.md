# Technical Specification — Climate x Public Health Observatory

> **How to use this document:** each section in Part 3 (Claude Code Prompts) is written to be pasted as a whole into a Claude Code session, one at a time, in order. Review the output of each prompt before pasting the next one — especially the dbt data tests and schema. Parts 1 and 2 are reference context (paste them first, or keep as `CLAUDE.md`/`CONTEXT.md` in the repo root).
>
> **Language note:** all code, comments, docstrings, commit messages, README, and ADRs must be written in English. This is a portfolio project intended for an international audience, so English is the standard from the first line of code.

---

## PART 1 — Overview and Architecture Decisions

### 1.1 Project goal

Build a complete data pipeline (ingestion → transformation → modeling → observability → visualization) that correlates **daily climate data** (INMET, Brazil's National Institute of Meteorology) with **hospital admissions for respiratory causes** (DataSUS/SIH-RD, Brazil's public health system hospital information system), answering: *"Is there a correlation between climate variation and spikes in respiratory hospital admissions by region in Brazil?"*

This is not a "pipeline for the sake of a pipeline" project — it's an **operational data engineering** project: success isn't just "data reaches the dashboard," it's "the system behaves like something that would run in production" (tested, observable, documented, with justified trade-offs).

### 1.2 Assumed scope (adjustable)

To fit into 2-4 weeks, I've made two scope cuts. Flag it if you disagree before starting the prompts:

1. **Geographic scope:** start with the municipality of Curitiba (Paraná), given its dense INMET station coverage and its ~1.8M population providing enough SIH admission volume for meaningful analysis. Design the model with expansion to the wider Curitiba Metropolitan Region (RMC) or the full state of Paraná in mind as documented "future work" — don't implement it upfront.
2. **Time scope:** last 24 months of data. Enough to observe seasonality without dealing with SIH's full historical volume.

### 1.3 Stack and architecture decisions

| Layer | Choice | Alternative considered | Why |
|---|---|---|---|
| Ingestion | Python 3.11+, `httpx`, `pysus` | Raw `requests` for SIH | `pysus` already knows how to parse DataSUS's `.dbc` files — reimplementing that manually is rework with no portfolio value |
| Analytics storage | DuckDB local + **MotherDuck** (free tier) | Supabase (Postgres) | Columnar engine, integrates natively with dbt (`dbt-duckdb`), zero infra cost, and it's a tool gaining market traction — a good signal of technical currency |
| Transformation | **dbt-core** (`dbt-duckdb` adapter) | Plain SQL scripts | Industry standard, native data tests, automatic documentation (`dbt docs`) |
| Orchestration | GitHub Actions (cron) | Airflow/Dagster | Documented via ADR: volume and frequency (daily) don't justify a dedicated orchestrator at this stage |
| Observability | Telegram Bot API + healthchecks.io + Elementary (dbt package) | Slack, Grafana | 3 complementary layers (infra / silent failure / data quality) — see section 1.5 |
| Frontend | Next.js + React, deployed on Vercel | Streamlit | Uses your JS stack, and Vercel's free tier is enough for portfolio-level traffic |
| CI/CD | GitHub Actions | — | Lint, `dbt build`, tests, automatic deploy on push to `main` |

### 1.4 Data model (star schema)

```
fct_respiratory_admissions
├── fk_date (→ dim_date)
├── fk_municipality (→ dim_location)
├── admission_count
├── total_aih_value
├── avg_length_of_stay
└── icd_group (respiratory cause category)

fct_daily_climate
├── fk_date (→ dim_date)
├── fk_station (→ dim_weather_station)
├── avg_temp, min_temp, max_temp
├── avg_relative_humidity
└── total_precipitation

dim_date (date, year, month, day, day_of_week, season)
dim_location (municipality, state, region, ibge_code, lat, lon)
dim_weather_station (station_code, name, nearest_municipality, lat, lon)
```

The join between the two facts happens at `dim_date` level plus geographic proximity (`dim_location` ↔ `dim_weather_station`) — that alone is a modeling decision worth documenting in an ADR (not every municipality has its own weather station).

### 1.5 Observability — three-layer specification

| Layer | Tool | What it detects | Where it plugs into the pipeline |
|---|---|---|---|
| Operational failure | Telegram Bot API | Execution error (API down, exception in code) | Final step of each GitHub Actions job (`if: failure()`) |
| Silent failure | healthchecks.io | Pipeline that should have run and didn't | Success ping at the end of each run; alert if no ping within the expected window |
| Data quality failure | Elementary (dbt package) | Schema drift, volume anomalies, stale freshness | Runs as part of `dbt build` in the Action |

---

## PART 2 — Repository Structure

```
climate-health-observatory/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── daily-pipeline.yml
├── ingestion/
│   ├── inmet/
│   │   ├── client.py
│   │   └── extract.py
│   ├── datasus/
│   │   ├── client.py
│   │   └── extract.py
│   └── tests/
├── dbt_project/
│   ├── models/
│   │   ├── staging/
│   │   ├── intermediate/
│   │   └── marts/
│   ├── tests/
│   ├── dbt_project.yml
│   └── packages.yml (elementary)
├── frontend/
│   └── (Next.js app)
├── docs/
│   └── adr/
│       ├── 0001-duckdb-motherduck-choice.md
│       ├── 0002-cron-vs-orchestrator.md
│       ├── 0003-three-layer-observability.md
│       └── 0004-scaling-strategy.md
├── .env.example
├── README.md
└── pyproject.toml
```

---

## PART 3 — Claude Code Prompts (paste in order)

### 🔹 PROMPT 1 — Initial project setup

```
Context: I'm building a data engineering portfolio project called
"Climate x Public Health Observatory," which correlates INMET (climate)
data with DataSUS/SIH-RD (respiratory hospital admissions) data for the
municipality of Curitiba, Paraná (PR), Brazil, over the last 24 months.

Stack: Python 3.11+, dbt-core with the dbt-duckdb adapter, DuckDB +
MotherDuck, Next.js for the frontend, GitHub Actions for CI/CD and
orchestration.

All code, comments, docstrings, and commit messages must be written in
English.

Task: create the initial repository structure with this folder tree:

climate-health-observatory/
├── .github/workflows/
├── ingestion/inmet/
├── ingestion/datasus/
├── ingestion/tests/
├── dbt_project/
├── frontend/
├── docs/adr/
├── .env.example
├── README.md (placeholder for now)
└── pyproject.toml

Configure pyproject.toml with Poetry, including these dependencies: httpx,
pysus, duckdb, dbt-core, dbt-duckdb, python-dotenv, pytest. Also set up a
.gitignore suited for Python + Node + dbt (include .env, __pycache__,
target/, dbt_packages/, node_modules/, .duckdb).

Don't implement business logic yet — just the structure and base
configuration. Then run git init, git add ., and create the first commit
with the message "chore: initial project structure".
```

### 🔹 PROMPT 2 — Foundational architecture ADR

```
Create the file docs/adr/0001-duckdb-motherduck-choice.md following the
standard Architecture Decision Record format (Context / Decision /
Consequences / Alternatives Considered).

The content should justify choosing DuckDB local + MotherDuck (free tier)
as the analytics storage layer, instead of a traditional cloud data
warehouse (Snowflake, BigQuery) or managed Postgres (Supabase).

Points to cover:
- Expected data volume (low-to-medium: 1 state, 24 months)
- Zero cost as a personal project requirement
- Native compatibility with dbt via dbt-duckdb
- Trade-off: this wouldn't be the right choice if the project needed
  concurrent multi-user write access, or volume in the hundreds-of-GB range
- When this decision should be revisited (objective criterion, e.g.
  "if the project expands to all Brazilian states and 5+ years of
  history, reassess for a distributed warehouse")

Then also create docs/adr/0002-cron-vs-orchestrator.md with the same
structure, justifying the use of GitHub Actions with cron instead of
Airflow/Dagster for daily orchestration, and an objective criterion for
when to migrate (e.g. more than N dependencies between jobs, need for
complex backfills, or multiple teams consuming the same pipeline).
```

### 🔹 PROMPT 3 — INMET ingestion

```
Implement the INMET data ingestion module in ingestion/inmet/.

Technical context: INMET's public API (https://apitempo.inmet.gov.br)
exposes automatic weather station data at:
https://apitempo.inmet.gov.br/estacao/{startDate}/{endDate}/{stationCode}
returning JSON with hourly readings (temperature, humidity, precipitation,
etc).

I need you to:

1. In client.py: build an HTTP client (using httpx) with exponential
   backoff retry (use tenacity or a manual implementation), configurable
   timeout, and rate-limit handling.

2. In extract.py: create a function that:
   - Takes a list of station codes (I'll provide Curitiba's station codes
     later after you help me identify them — for now, leave it as a
     configurable parameter in a config.py file)
   - Extracts hourly data and aggregates it to daily granularity
     (avg_temp, min_temp, max_temp, avg_relative_humidity,
     total_precipitation)
   - Saves the result as Parquet, partitioned by date, in
     ingestion/data/raw/inmet/
   - Is idempotent: running it twice for the same period doesn't
     duplicate data

3. Add structured logging (use the standard logging module, JSON format)
   so I can trace each run.

4. Create tests in ingestion/tests/test_inmet.py covering: parsing a
   valid response, handling an empty response, handling an HTTP error,
   and the daily aggregation logic.

Don't hit the real API in tests — use mocks via httpx.MockTransport or the
responses library.
```

### 🔹 PROMPT 4 — DataSUS/SIH-RD ingestion

```
Implement the DataSUS ingestion module in ingestion/datasus/.

Technical context: I'll use the `pysus` library to download SIH-RD
(Sistema de Informações Hospitalares - Reduzida) files, which contain
Brazilian public health system (SUS) hospital admission data. The library
already knows how to download and convert the .dbc files into a DataFrame.

I need you to:

1. In client.py: wrap the pysus calls (`pysus.online_data.SIH` module) to
   download data for the state of Paraná (UF: PR) for the last 24 months.
   Note: SIH data is only available for download at the state level, not
   per municipality — the municipality-level filter happens in extract.py.

2. In extract.py: create a function that:
   - Downloads the raw state-level data via pysus
   - Filters to admissions where the residence municipality (MUNIC_RES
     field) matches Curitiba's IBGE code (4106902) — implement this as a
     configurable constant in config.py, not hardcoded inline, so it's
     easy to swap for a list of codes later (e.g. to expand to the
     Curitiba Metropolitan Region)
   - Filters to admissions where the primary diagnosis (DIAG_PRINC field)
     belongs to the respiratory disease chapter of ICD-10 (codes J00-J99)
     — implement this filter with a configurable list/regex in config.py,
     not hardcoded
   - Selects and renames the relevant columns: municipality of residence,
     admission date, primary diagnosis, total AIH value, length of stay
   - Saves as Parquet, partitioned by month, in
     ingestion/data/raw/datasus/
   - Is idempotent

3. Add the same structured logging pattern used in the INMET module.

4. Create tests in ingestion/tests/test_datasus.py mocking the pysus
   response and covering: correct filtering by municipality code, correct
   filtering by respiratory ICD codes, handling of missing data, and the
   column selection/renaming logic.

Document in the module docstring that SIH data has a publication lag of
roughly 2 months — this is a real characteristic of the source, not a
bug, and should be reflected in the code comments.
```

### 🔹 PROMPT 5 — dbt project: staging

```
Set up the dbt project in dbt_project/ using the dbt-duckdb adapter,
connecting to a MotherDuck database (I'll provide the connection string
via a MOTHERDUCK_TOKEN environment variable).

Structure the models in three layers: staging/, intermediate/, marts/.

For the staging layer, create:
- stg_inmet__daily_climate.sql: reads the Parquet files from
  ingestion/data/raw/inmet/ (via a duckdb external table or source),
  doing only column renaming to consistent snake_case and type casting —
  no business logic.
- stg_datasus__admissions.sql: same logic for the admissions data.

For each staging model, create the corresponding schema.yml with:
- Column descriptions
- Tests: not_null on keys, unique where applicable, accepted_values for
  categorical fields (e.g. ICD group)

Follow standard dbt naming conventions (stg_ prefix, intermediate without
a special prefix, marts with fct_/dim_ prefixes).
```

### 🔹 PROMPT 6 — dbt project: marts (star schema)

```
Now build the marts/ layer of dbt_project implementing the star schema
specified below:

dim_date: generated via a seed or the dbt_utils date_spine macro, covering
the available data period, with columns year, month, day, day_of_week,
month_name, season (calculated from month, southern hemisphere).

dim_location: derived from the municipalities present in
stg_datasus__admissions, enriched with region (derived from state, which
will always be PR at this stage, but model the region column as if it
could vary, anticipating future expansion).

dim_weather_station: derived from the stations present in
stg_inmet__daily_climate, with code, name, and coordinates.

fct_respiratory_admissions: grain = 1 row per admission, with foreign keys
to dim_date and dim_location, and the metrics admission_count (always 1,
to allow SUM), total_aih_value, length_of_stay, icd_group.

fct_daily_climate: grain = 1 row per station per day, with a foreign key
to dim_date and dim_weather_station, and the temperature/humidity/
precipitation metrics.

For each mart, create schema.yml with robust data tests: relationships
(valid foreign keys), not_null, and at least one custom test using
dbt_utils (e.g. expression_is_true to validate that min_temp <= max_temp).

Finally, create an additional model mart_climate_health_correlation.sql
that joins the two facts via dim_date, and a simple geographic proximity
approximation between municipality and nearest station (this can be a
manual mapping via a seed CSV for this phase — document this limitation).
```

### 🔹 PROMPT 7 — Observability

```
Implement the project's 3 observability layers:

1. Telegram: create a scripts/notify_telegram.py script that takes a
   message and status (success/failure) via command-line arguments, and
   POSTs to the Telegram API using the TELEGRAM_BOT_TOKEN and
   TELEGRAM_CHAT_ID environment variables. It should work for both
   success and failure notifications, with different emojis (✅/🚨), and
   include the GitHub Actions run number in the message (via the
   GITHUB_RUN_NUMBER environment variable).

2. healthchecks.io: create a scripts/ping_healthcheck.py script that
   makes a simple GET request to the ping URL configured in
   HEALTHCHECK_URL, called at the end of a successful full pipeline run.

3. Elementary: add the elementary-data package to dbt_project's
   packages.yml, configure the required profile, and add the `edr report`
   command at the end of the dbt workflow (we'll cover this in the
   GitHub Actions prompt) to generate the data observability report.

Also create docs/adr/0003-three-layer-observability.md explaining the
conceptual difference between the 3 layers (operational failure vs.
silent failure vs. data quality failure), and why one layer doesn't
replace the others.
```

### 🔹 PROMPT 8 — GitHub Actions (CI/CD + orchestration)

```
Create two GitHub Actions workflows:

1. .github/workflows/ci.yml — runs on every pull request to main:
   - Sets up Python + Poetry, installs dependencies
   - Runs lint (ruff) and the unit tests in ingestion/tests/
   - Runs dbt parse and dbt compile to validate that the dbt project is
     valid (without executing against the real database)

2. .github/workflows/daily-pipeline.yml — runs on a daily cron schedule
   (set the time considering that INMET data usually becomes available
   in the early hours of the following day) and also supports manual
   dispatch:
   - Runs the INMET ingestion (ingestion/inmet/extract.py)
   - Runs the DataSUS ingestion (consider that this can run less
     frequently, e.g. weekly, since it has a multi-month lag — implement
     as a separate job with its own schedule)
   - Runs dbt build (models + tests) against MotherDuck
   - Runs edr report (Elementary)
   - On success: calls scripts/ping_healthcheck.py
   - On failure of any step: calls scripts/notify_telegram.py with a
     failure status (use "if: failure()" with appropriate "always()"
     handling to ensure the notification runs even if an earlier step
     fails)
   - Use GitHub Secrets for all credentials (MOTHERDUCK_TOKEN,
     TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HEALTHCHECK_URL)

Document at the top of daily-pipeline.yml, in a comment, the reasoning
behind running DataSUS ingestion at a different frequency than INMET.
```

### 🔹 PROMPT 9 — Frontend (Next.js)

```
Create a Next.js app (App Router) in frontend/ that consumes data from
mart_climate_health_correlation via an API route that reads directly from
MotherDuck (use the duckdb JS client or an API route running a query via
duckdb-node).

Required pages/components:
1. Home page: a dual-axis time series chart (left Y axis: average
   temperature; right Y axis: respiratory admission count) over time,
   using Recharts.
2. A granularity selector (monthly vs. weekly view).
3. An "About this project" section explaining the methodology and linking
   to the GitHub repository and the ADRs.
4. A "last data update" indicator (read the most recent timestamp from
   the mart).

Design: minimalist, focused on data readability, no need for elaborate
visual components — this is a data engineering project, not a product
design showcase. Use Tailwind for basic styling.

Don't implement authentication or write functionality — it's a read-only,
public dashboard.
```

### 🔹 PROMPT 10 — README and final ADRs

```
Write the project's main README.md containing:

1. Title and a one-line purpose statement (the project's "why")
2. Link to the live dashboard (placeholder for now)
3. A Mermaid architecture diagram showing the full flow: sources →
   ingestion → storage → dbt → observability → frontend
4. An "Architecture Decisions" section linking to the ADRs in docs/adr/
5. A "Running locally" section
6. A "How this would scale" section — briefly discuss what would change
   if the scope were all Brazilian states and 5+ years of history
   (partitioning, storage swap, CDC instead of full refresh, need for a
   dedicated orchestrator)
7. A "Stack" section with badges for the technologies used

Then create docs/adr/0004-scaling-strategy.md formalizing the answer from
section 6 above in full ADR format (even without implementing it, it's a
documented architectural decision — treat it as "a decision for the
future, recorded now").
```

---

## Definition of Done per phase

| Phase | Done when... |
|---|---|
| Ingestion | Scripts run locally, produce valid idempotent Parquet output, with passing tests |
| dbt staging/marts | `dbt build` runs with no errors, all data tests pass, `dbt docs generate` produces browsable documentation |
| Observability | A forced error (e.g. deliberately breaking the API URL) correctly triggers the Telegram alert |
| CI/CD | A test PR triggers the CI workflow and blocks merge if lint/tests fail |
| Frontend | Dashboard live on Vercel, consuming real data from MotherDuck |
| Documentation | All 4 ADRs written, README complete with diagram |

---

## Suggested next steps after the MVP

Don't do these in the initial 2-4 weeks — they're for later, if you want to go deeper:
- Expand to more states (test the decision documented in ADR 0004)
- Add a simple forecasting model (a good hook to connect with the Data Science postgrad)
- Replace the manual geographic proximity mapping with actual haversine distance calculation between coordinates
