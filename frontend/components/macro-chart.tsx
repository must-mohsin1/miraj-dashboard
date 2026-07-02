"use client";

import {
  Cell,
  Bar,
  BarChart,
  Label,
  Pie,
  PieChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { MacroData } from "@/lib/types";

/**
 * MacroChart — Client Component.
 *
 * Two recharts visualisations driven by the same `MacroData` block that the
 * stat cards consume:
 *
 * 1. A donut/pie chart showing BTC dominance vs. the rest of the crypto
 *    market ("Altcoins"). Uses the muted slate/emerald palette that the
 *    rest of the dashboard uses.
 * 2. A radial-bar "gauge" for the Fear & Greed index (0–100), coloured
 *    along the red → green sentiment axis.
 *
 * Both charts degrade gracefully: when a value is `null` (upstream source
 * failed) the chart renders a single placeholder slice/segment with a
 * "No data" label rather than throwing.
 */

const BTC_COLOR = "#10b981"; // emerald-500
const ALTCOIN_COLOR = "#475569"; // slate-600
const PLACEHOLDER_COLOR = "#1e293b"; // slate-800

/** Map a Fear & Greed numeric value to a sentiment colour. */
function fearGreedColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return PLACEHOLDER_COLOR;
  }
  if (value <= 24) return "#f87171"; // red-400 — Extreme Fear
  if (value <= 44) return "#fb923c"; // orange-400 — Fear
  if (value <= 55) return "#e2e8f0"; // slate-200 — Neutral
  if (value <= 74) return "#34d399"; // emerald-400 — Greed
  return "#6ee7b7"; // emerald-300 — Extreme Greed
}

interface MacroChartProps {
  /** Macro data block from the API. `null` renders empty placeholders. */
  data: MacroData | null;
}

/**
 * Donut chart: BTC dominance vs. altcoins. When `btc_dominance` is null the
 * chart renders a single placeholder slice so the visual layout is stable.
 */
function DominancePie({ data }: { data: MacroData | null }) {
  const btcDominance = data?.btc_dominance ?? null;
  const hasData =
    btcDominance !== null &&
    btcDominance !== undefined &&
    !Number.isNaN(btcDominance);

  const pieData = hasData
    ? [
        { name: "BTC", value: Number(btcDominance) },
        { name: "Altcoins", value: Math.max(0, 100 - Number(btcDominance)) },
      ]
    : [{ name: "No data", value: 100 }];

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={hasData ? 3 : 0}
            stroke="none"
          >
            {hasData ? (
              <>
                <Cell fill={BTC_COLOR} />
                <Cell fill={ALTCOIN_COLOR} />
              </>
            ) : (
              <Cell fill={PLACEHOLDER_COLOR} />
            )}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "0.5rem",
              color: "#e2e8f0",
              fontSize: "0.75rem",
            }}
            formatter={(value, name) => {
              const v = Number(value) || 0;
              return hasData ? [`${v.toFixed(2)}%`, String(name)] : ["N/A", String(name)];
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Radial-bar gauge for the Fear & Greed index (0–100). recharts'
 * `RadialBarChart` with a single bar and `domain={[0, 100]}` on the
 * PolarAngleAxis gives a clean semicircular gauge look.
 */
function FearGreedGauge({ data }: { data: MacroData | null }) {
  const value = data?.fear_greed_index ?? null;
  const hasData =
    value !== null && value !== undefined && !Number.isNaN(value);
  const numericValue = hasData ? Number(value) : 0;

  const gaugeData = [
    {
      name: "Fear & Greed",
      value: numericValue,
      fill: fearGreedColor(value),
    },
  ];

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart
          data={gaugeData}
          startAngle={90}
          endAngle={-270}
          innerRadius="70%"
          outerRadius="100%"
        >
          <PolarAngleAxis
            type="number"
            domain={[0, 100]}
            tick={false}
          />
          <RadialBar
            background={{ fill: "#1e293b" }}
            dataKey="value"
            cornerRadius={8}
          />
          <Label
            position="center"
            content={({ viewBox }) => {
              if (!viewBox || !("cx" in viewBox) || !("cy" in viewBox)) {
                return null;
              }
              const { cx, cy } = viewBox as { cx: number; cy: number };
              return (
                <text
                  x={cx}
                  y={cy}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-slate-100"
                  style={{ fontSize: "1.875rem", fontWeight: 700 }}
                >
                  {hasData ? numericValue : "—"}
                </text>
              );
            }}
          />
        </RadialBarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MacroChart({ data }: MacroChartProps) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* Dominance pie */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-2 text-sm font-medium text-slate-300">
          BTC vs. Altcoin Dominance
        </h3>
        <DominancePie data={data} />
        <div className="mt-2 flex items-center justify-center gap-4 text-xs text-slate-400">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: BTC_COLOR }}
            />
            BTC
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: ALTCOIN_COLOR }}
            />
            Altcoins
          </span>
        </div>
      </div>

      {/* Fear & Greed gauge */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-2 text-sm font-medium text-slate-300">
          Fear &amp; Greed Gauge
        </h3>
        <FearGreedGauge data={data} />
        <p className="mt-2 text-center text-xs text-slate-500">
          {data?.fear_greed_label ?? "—"}
        </p>
      </div>
    </div>
  );
}

/**
 * Bar-chart variant for the Fear & Greed index. Kept as a named export so it
 * can be used independently (e.g. in a compact report view) but also rendered
 * by the default `MacroChart` composition when a vertical bar gauge is
 * preferred over the radial dial.
 */
export function FearGreedBarChart({ data }: { data: MacroData | null }) {
  const value = data?.fear_greed_index ?? null;
  const hasData =
    value !== null && value !== undefined && !Number.isNaN(value);
  const numericValue = hasData ? Number(value) : 0;

  const barData = [{ name: "Fear & Greed", value: numericValue }];

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={barData}
          layout="vertical"
          margin={{ top: 16, right: 16, bottom: 16, left: 16 }}
        >
          <XAxis type="number" domain={[0, 100]} hide />
          <YAxis type="category" dataKey="name" hide />
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "0.5rem",
              color: "#e2e8f0",
              fontSize: "0.75rem",
            }}
            formatter={(value) => {
              const v = Number(value) || 0;
              return [`${v} / 100`, "Fear & Greed"];
            }}
          />
          <Bar
            dataKey="value"
            radius={[4, 4, 4, 4]}
            background={{ fill: "#1e293b" }}
          >
            <Cell fill={fearGreedColor(value)} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export { DominancePie, FearGreedGauge, fearGreedColor };

export default MacroChart;
