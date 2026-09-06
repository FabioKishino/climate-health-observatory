# 0005 — INMET Bulk Historical Archive Instead of the Live API

## Status

Accepted

## Context

Prompt 3 (see SPEC.md) originally specified INMET's live REST API
(`https://apitempo.inmet.gov.br/estacao/{start}/{end}/{stationCode}`) as
the climate data source, and `ingestion/inmet/client.py` was built and
unit-tested against it (with mocked HTTP responses, since the API had
never actually been reachable from this project's development sandbox).

The first real end-to-end runs of the daily pipeline (GitHub Actions,
Prompt 8) exposed the API's actual behavior in production, across three
separate `workflow_dispatch` attempts against the same station (A807,
Curitiba) on the same day:

1. The connection was dropped outright with httpx's default User-Agent.
2. After adding a browser-like User-Agent (which did stop the dropped
   connections), the API returned an unexpected HTTP 204 (No Content)
   instead of the 200-with-empty-array this client had assumed.
3. On a third attempt, every request timed out after 30 seconds, five
   times in a row with backoff between them.

Three different failure symptoms from the same endpoint on the same day
is a pattern, not noise. Research into this confirmed it isn't specific
to this project's setup:

- `inmetpy`, a maintained third-party Python wrapper for this exact API,
  is now archived with the message *"The INMET has changed the access for
  the API. Therefore (and unfortunately) this package is no longer
  working."*
- An R package with a similar wrapper (`lhmet/inmetr`) has a long-unresolved,
  never-answered timeout issue against an INMET domain, and was archived
  shortly after.
- A comparable from-scratch project building an INMET-backed pipeline
  (`gregomelo/brazil_weather_data`) deliberately avoids calling any INMET
  API live in its serving path at all, instead doing local batch ingestion
  from pre-fetched files.
- The response headers observed when probing INMET's infrastructure carry
  the signature of a Citrix NetScaler AppFirewall/WAF — a class of system
  known for silently dropping, truncating, or delaying requests it
  doesn't like, with no documented or consistent pattern.
- No official rate-limit policy, SLA, or "manual de uso da API" exists for
  `apitempo.inmet.gov.br` — it presents as an internal/undocumented API
  that INMET's own website happens to use, not a supported public product.

## Decision

Switch `ingestion/inmet/client.py` to download INMET's official annual
bulk historical archive instead:

```
https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip
```

This is a static file server (confirmed via direct inspection: standard
`ETag`/`Last-Modified`/`Accept-Ranges` caching headers, `Content-Type:
application/zip`), a fundamentally more reliable class of service than a
dynamic per-request API sitting behind a WAF. Each ZIP contains one
semicolon-delimited, Latin-1-encoded CSV per station (e.g.
`INMET_S_PR_A807_CURITIBA_01-01-2026_A_31-08-2026.CSV`), at the same
hourly granularity the live API provided, with station metadata (name,
state, coordinates) in the file's first 8 lines.

`InmetClient.get_station_readings()` keeps its exact same signature and
return shape (records keyed like the old API's JSON:
`CD_ESTACAO`/`DC_NOME`/`UF`/`VL_LATITUDE`/`VL_LONGITUDE`/`DT_MEDICAO`/
`TEM_INS`/`TEM_MAX`/`TEM_MIN`/`UMD_INS`/`CHUVA`), so this change is
confined entirely to `client.py` — `extract.py`'s parsing, aggregation,
and Parquet-writing logic needed zero changes.

A browser-like `User-Agent` header is still required for this static file
host too — the same WAF-style blocking observed against the live API
applies here, just without the flakiness of a dynamic endpoint once past
that check.

## Consequences

**Positive:**

- Verified directly (not assumed): a real `python -m ingestion.inmet.extract`
  run against this archive completed in ~8 seconds and produced correct
  daily-aggregated Parquet output for Curitiba — the first fully successful
  real INMET extraction this project has had.
- A static file server is a much smaller, better-understood failure
  surface than an undocumented dynamic API — no more retry logic tuned
  around a specific WAF's inconsistent behavior (429 `Retry-After`
  handling, 204-as-empty-response, etc.), just a plain download with
  light retries for ordinary transient network issues.
- Archives are cached per `InmetClient` instance per year, so requesting
  multiple stations (e.g. future Curitiba Metropolitan Region expansion)
  in the same run downloads each year's ~64MB archive only once.

**Negative / trade-offs accepted:**

- Coarser publication lag than the live API's documented ~1-day claim.
  The observed `Last-Modified` on the 2026 archive was 4 days old at
  fetch time; some third-party documentation describes monthly-only
  updates for the current year's file. `_default_date_range()` still
  requests "yesterday" by default, so a request for very recent dates may
  legitimately return zero rows until the archive catches up — the
  pipeline already handles this gracefully (an empty result is not an
  error), but the practical freshness of "yesterday's climate data" is
  now closer to "within the last several days."
- Higher bandwidth per run: downloading a ~64MB yearly archive (all ~600+
  stations) to extract one station's data, once per day, versus a scoped
  single-station API query. Immaterial at this project's scale and
  GitHub Actions' free-tier bandwidth, but a real trade-off worth naming.
- If a request spans a year boundary (e.g. requesting Dec 31 and Jan 1
  together), two ~64MB archives are downloaded instead of one — rare in
  practice given the daily job's normal one-day request window.

## Alternatives Considered

**Keep the live API, harden the client further.** Rejected: three
different failure modes from the same endpoint in one day, corroborated
by independent reports of the same API breaking a maintained third-party
library entirely, indicates a reliability ceiling that better retry logic
can't reliably raise — the WAF behavior observed has no documented,
predictable pattern to engineer around.

**BDMEP (`bdmep.inmet.gov.br`).** This is a web portal in front of the
same underlying historical CSV data, oriented at interactive/manual
download rather than programmatic access — not a materially different
option from downloading the archive files directly.

**A different data source entirely (Open-Meteo, NOAA/GHCN).** Rejected:
these are reanalysis/model products, not INMET's actual station
observations. Reporting real Curitiba station data, not a modeled
estimate, is part of this project's stated value — a reanalysis product
would be a bigger scope change than the ingestion mechanism this ADR
is actually about.

## When to Revisit

If INMET's live API is ever confirmed stable over a sustained period (or
gains a documented, supported status), revisit whether its lower latency
is worth trading back for — the bulk archive's few-day lag is the main
cost of this decision. If the project expands to enough stations that
downloading a full yearly archive per station becomes wasteful, consider
downloading each year's archive once per run and extracting every needed
station from it in one pass (already how multi-station requests within a
single `InmetClient` instance behave, given per-year caching).
