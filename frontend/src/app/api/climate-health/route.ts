import { NextRequest, NextResponse } from "next/server";
import { withClient } from "@/lib/motherduck";

type Granularity = "weekly" | "monthly";

export interface ClimateHealthPoint {
  period: string;
  avgTemp: number | null;
  admissionCount: number;
}

export interface ClimateHealthResponse {
  granularity: Granularity;
  points: ClimateHealthPoint[];
  lastUpdated: string | null;
}

function parseGranularity(value: string | null): Granularity {
  return value === "weekly" ? "weekly" : "monthly";
}

export async function GET(request: NextRequest) {
  const granularity = parseGranularity(request.nextUrl.searchParams.get("granularity"));
  // Never interpolate the raw query param into SQL — truncUnit only ever
  // takes one of these two hardcoded literals, chosen by our own code.
  const truncUnit = granularity === "weekly" ? "week" : "month";

  try {
    const { points, lastUpdated } = await withClient(async (client) => {
      // date_trunc() on a DATE returns a TIMESTAMP, so it's cast back to
      // DATE before ::VARCHAR — casting straight to VARCHAR would include
      // a spurious "00:00:00" time component. Casting to a plain string
      // (rather than letting node-postgres parse a DATE into a JS Date)
      // sidesteps that parsing's implicit dependence on the runtime's
      // system timezone entirely — verified directly against MotherDuck.
      const seriesResult = await client.query(
        `SELECT
          date_trunc('${truncUnit}', date_day)::DATE::VARCHAR AS period,
          avg(avg_temp) AS avg_temp,
          sum(daily_admission_count)::INTEGER AS admission_count
        FROM main.mart_climate_health_correlation
        GROUP BY 1
        ORDER BY 1`
      );

      const lastUpdatedResult = await client.query(
        `SELECT max(date_day)::VARCHAR AS last_updated
         FROM main.mart_climate_health_correlation`
      );

      const points: ClimateHealthPoint[] = seriesResult.rows.map((row) => ({
        period: row.period,
        avgTemp: row.avg_temp === null ? null : Number(row.avg_temp),
        admissionCount: Number(row.admission_count ?? 0),
      }));

      return {
        points,
        lastUpdated: (lastUpdatedResult.rows[0]?.last_updated as string | undefined) ?? null,
      };
    });

    return NextResponse.json({ granularity, points, lastUpdated } satisfies ClimateHealthResponse);
  } catch (error) {
    console.error("Failed to fetch climate/health data:", error);
    return NextResponse.json({ error: "Failed to fetch climate/health data" }, { status: 500 });
  }
}
