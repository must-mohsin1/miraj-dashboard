"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { BenchmarkResponse } from "@/lib/types";

/**
 * BenchmarkComparison — Client Component.
 *
 * Renders a recharts dual-line chart comparing portfolio cumulative return
 * vs BTC buy-and-hold, both indexed to 0% at the start of the period.
 * Summary cards show total returns, alpha, and beta.
 */

interface BenchmarkComparisonProps {
  data: BenchmarkResponse | null;
  loading: boolean;
  error: string | null;
}

const TOOLTIP_STYLE = {
  backgroundColor: "#0f172a",
  border: "1px solid #1e293b",
  borderRadius: "0.5rem",
  color: "#e2e8f0",
  fontSize: "0.75rem",
} as const;

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

interface TooltipPayloadItem {
  payload: {
    date: string;
    btc_return_pct: number;
    portfolio_return_pct: number;
  };
}

function BenchmarkTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <div className="font-medium text-slate-100">
        {formatDate(point.date)}
      </div>
      <div className="mt-1 space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
          <span className="text-slate-400">BTC:</span>
          <span
            className={`font-semibold tabular-nums ${
              point.btc_return_pct >= 0 ? "text-amber-400" : "text-red-400"
            }`}
          >
            {point.btc_return_pct >= 0 ? "+" : ""}
            {point.btc_return_pct.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-slate-400">Portfolio:</span>
          <span
            className={`font-semibold tabular-nums ${
              point.portfolio_return_pct >= 0
                ? "text-emerald-400"
                : "text-red-400"
            }`}
          >
            {point.portfolio_return_pct >= 0 ? "+" : ""}
            {point.portfolio_return_pct.toFixed(2)}%
          </span>
        </div>
      </div>
    </div>
  );
}

export function BenchmarkComparison({
  data,
  loading,
  error,
}: BenchmarkComparisonProps) {
  const chartData = useMemo(() => {
    if (!data?.points) return [];
    return data.points.map((p) => ({
      date: p.date,
      BTC: p.btc_return_pct,
      Portfolio: p.portfolio_return_pct,
    }));
  }, [data]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        Loading benchmark data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
        {error}
      </div>
    );
  }

  if (!data || !data.points || data.points.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No benchmark data available. The chart will populate as portfolio data
        is recorded.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* ── Summary stat cards ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Portfolio Return"
          value={`${data.portfolio_return_pct >= 0 ? "+" : ""}${data.portfolio_return_pct.toFixed(2)}%`}
          positive={data.portfolio_return_pct >= 0}
        />
        <StatCard
          label="BTC Return"
          value={`${data.btc_return_pct >= 0 ? "+" : ""}${data.btc_return_pct.toFixed(2)}%`}
          positive={data.btc_return_pct >= 0}
        />
        <StatCard
          label="Alpha"
          value={`${data.alpha >= 0 ? "+" : ""}${data.alpha.toFixed(2)}%`}
          positive={data.alpha >= 0}
          tooltip="Portfolio return minus BTC return — positive means the portfolio outperformed"
        />
        <StatCard
          label="Beta"
          value={data.beta !== null ? data.beta.toFixed(2) : "N/A"}
          positive={
            data.beta !== null
              ? data.beta >= 0 && data.beta < 1.5
              : true
          }
          tooltip="Portfolio volatility vs BTC. 1.0 = moves in sync, <1 = less volatile, >1 = more volatile"
        />
      </div>

      {/* ── Chart ── */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-300">
          {data.symbol} Buy-and-Hold vs Portfolio
        </h3>
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#1e293b"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
                width={56}
                tickFormatter={(v: number) => `${v.toFixed(1)}%`}
              />
              <Tooltip content={<BenchmarkTooltip />} />
              <Line
                type="monotone"
                dataKey="Portfolio"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#10b981", stroke: "#0f172a", strokeWidth: 2 }}
              />
              <Line
                type="monotone"
                dataKey="BTC"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#f59e0b", stroke: "#0f172a", strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="mt-3 flex items-center justify-center gap-6 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" />
            <span className="text-slate-400">Portfolio</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-500" />
            <span className="text-slate-400">{data.symbol}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Small stat card shown in the summary grid. */
function StatCard({
  label,
  value,
  positive,
  tooltip,
}: {
  label: string;
  value: string;
  positive: boolean;
  tooltip?: string;
}) {
  return (
    <div
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
      title={tooltip}
    >
      <div className="text-xs text-slate-500">{label}</div>
      <div
        className={`mt-1 text-lg font-bold tabular-nums ${
          positive ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

export default BenchmarkComparison;