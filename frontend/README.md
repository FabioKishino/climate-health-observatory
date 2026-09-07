# Climate x Public Health Observatory — dashboard

Read-only Next.js dashboard for the [Climate x Public Health Observatory](../README.md)
project: a dual-axis time series of average temperature vs. respiratory hospital
admissions for Curitiba, PR, plus a weekly/monthly granularity toggle and an "about"
section linking back to the project's source and ADRs.

## Running locally

```bash
npm install
cp .env.local.example .env.local   # fill in MOTHERDUCK_TOKEN
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `MOTHERDUCK_TOKEN` | Yes | Read access is enough — this app never writes. |
| `MOTHERDUCK_HOST` | No | Defaults to `pg.us-east-1-aws.motherduck.com`. |
| `MOTHERDUCK_DB` | No | Defaults to `climate_health_observatory`. |

## How it connects to the data

`src/app/api/climate-health/route.ts` queries `mart_climate_health_correlation` in
MotherDuck over the Postgres wire protocol (the `pg` npm package), not a DuckDB client
library — MotherDuck's own recommended approach for serverless functions, since it needs
no native binary to bundle. See `src/lib/motherduck.ts`.

## Deploying

Deploy this directory (`frontend/`) to Vercel as the project root, with the three
environment variables above set in the Vercel project settings.
