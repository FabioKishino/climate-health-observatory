"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ClimateHealthResponse } from "@/app/api/climate-health/route";

type Granularity = "weekly" | "monthly";

function formatPeriod(period: string, granularity: Granularity): string {
  const date = new Date(`${period}T00:00:00Z`);
  return granularity === "monthly"
    ? date.toLocaleDateString("en-US", { year: "numeric", month: "short", timeZone: "UTC" })
    : date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

interface RequestState {
  granularity: Granularity;
  data: ClimateHealthResponse | null;
  error: string | null;
}

export default function ClimateHealthDashboard() {
  const [granularity, setGranularity] = useState<Granularity>("monthly");
  // Tagged with the granularity it corresponds to, so "loading" can be
  // derived (granularity !== requestState.granularity) instead of tracked
  // as separate state set synchronously inside the effect below.
  const [requestState, setRequestState] = useState<RequestState>({
    granularity,
    data: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    fetch(`/api/climate-health?granularity=${granularity}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
        return res.json() as Promise<ClimateHealthResponse>;
      })
      .then((json) => {
        if (!cancelled) setRequestState({ granularity, data: json, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setRequestState({
            granularity,
            data: null,
            error: err instanceof Error ? err.message : "Failed to load data",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [granularity]);

  const loading = requestState.granularity !== granularity;
  const data = loading ? null : requestState.data;
  const error = loading ? null : requestState.error;

  const chartData =
    data?.points.map((point) => ({
      ...point,
      label: formatPeriod(point.period, granularity),
    })) ?? [];

  return (
    <section className="w-full max-w-4xl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="inline-flex rounded-md border border-black/10 dark:border-white/15 overflow-hidden text-sm">
          {(["weekly", "monthly"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setGranularity(option)}
              className={`px-3 py-1.5 capitalize transition-colors cursor-pointer ${
                granularity === option
                  ? "bg-foreground text-background"
                  : "bg-transparent hover:bg-black/5 dark:hover:bg-white/10"
              }`}
              aria-pressed={granularity === option}
            >
              {option}
            </button>
          ))}
        </div>

        <p className="text-sm text-black/60 dark:text-white/60">
          {data?.lastUpdated ? (
            <>
              Data current through{" "}
              <span className="font-medium text-foreground">{data.lastUpdated}</span>
            </>
          ) : (
            " "
          )}
        </p>
      </div>

      <div className="h-[420px] w-full rounded-lg border border-black/10 dark:border-white/15 p-4">
        {error ? (
          <div className="h-full flex items-center justify-center text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        ) : loading && !data ? (
          <div className="h-full flex items-center justify-center text-sm text-black/50 dark:text-white/50">
            Loading…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-black/10 dark:stroke-white/10" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 12 }}
                interval="preserveStartEnd"
                minTickGap={20}
              />
              <YAxis
                yAxisId="temp"
                orientation="left"
                tick={{ fontSize: 12 }}
                label={{ value: "Avg. temperature (°C)", angle: -90, position: "insideLeft", fontSize: 12 }}
                domain={["auto", "auto"]}
              />
              <YAxis
                yAxisId="admissions"
                orientation="right"
                tick={{ fontSize: 12 }}
                label={{
                  value: "Respiratory admissions",
                  angle: 90,
                  position: "insideRight",
                  fontSize: 12,
                }}
                allowDecimals={false}
              />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar
                yAxisId="admissions"
                dataKey="admissionCount"
                name="Respiratory admissions"
                fill="#60a5fa"
                radius={[2, 2, 0, 0]}
              />
              <Line
                yAxisId="temp"
                type="monotone"
                dataKey="avgTemp"
                name="Avg. temperature (°C)"
                stroke="#ef4444"
                strokeWidth={2}
                dot={{ r: 2, fill: "#ef4444", strokeWidth: 0 }}
                activeDot={{ r: 4 }}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
