"use client";

import { useEffect, useState } from "react";
import { Loader2, TrendingUp, TrendingDown, Activity, BarChart3 } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

import type { BenchmarkResponse } from "@/lib/types";

/**
 * BenchmarkComparison — Client Component.
 *
 * Fetches `GET /api/v1/analytics/benchmark?symbol=BTC-USD&days=30&exchange=...`
 * and renders:
 *  - Recharts line chart: portfolio vs BTC buy-and-hold (both indexed to 0% at start)
 *  - Summary stats: portfolio return %, BTC return %, alpha, beta
 *
 * Auto-refreshes every 5 minutes.
 */

interface BenchmarkComparisonProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

export function BenchmarkComparison({ token, exchange }: BenchmarkComparisonProps) {
  const [data, setData] = useState<BenchmarkResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchBenchmark() {
    setRefreshing(true);
    try {
      const res = await fetch(
        `/api/v1/analytics/benchmark?symbol=BTC-USD&days=30&exchange=${exchange}`,
        { headers },
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: BenchmarkResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    async function load() {
      if (cancelled) return;
      await fetchBenchmark();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchBenchmark();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  // ── Render: loading ──────────────────────────────────────────────────
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading benchmark comparison…
      </div>
    );
  }

  // ── Render: error ────────────────────────────────────────────────────
  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        Failed to load benchmark: {error}
      </div>
    );
  }

  if (!data) return null;

  const points = data.points ?? [];
  const portPositive = data.portfolio_return_pct >= 0;
  const btcPositive = data.btc_return_pct >= 0;
  const alphaPositive = data.alpha >= 0;

  // Thin date labels for the X axis
  const chartData = points.map((p) => ({
    date: p.date.slice(5), // "MM-DD"
    portfolio: Number(p.portfolio_return_pct.toFixed(2)),
    btc: Number(p.btc_return_pct.toFixed(2)),
  }));

  return (
    <div className="space-y-4">
      {/* ── Summary stat cards ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Portfolio Return"
          value={`${data.portfolio_return_pct.toFixed(2)}%`}
          positive={portPositive}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <StatCard
          label="BTC Return"
          value={`${data.btc_return_pct.toFixed(2)}%`}
          positive={btcPositive}
          icon={<BarChart3 className="h-4 w-4" />}
        />
        <StatCard
          label="Alpha"
          value={`${data.alpha.toFixed(2)}%`}
          positive={alphaPositive}
          icon={<Activity className="h-4 w-4" />}
          hint="Portfolio − BTC"
        />
        <StatCard
          label="Beta"
          value={data.beta !== null ? data.beta.toFixed(2) : "—"}
          positive={data.beta !== null && data.beta < 1}
          icon={<Activity className="h-4 w-4" />}
          hint="Cov / Var"
        />
      </div>

      {/* ── Chart ────────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-4 text-sm font-medium text-slate-300">
          Cumulative Return (Indexed to 0% at Start)
        </h3>
        <div className="h-72 w-full">
          {points.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              No overlapping data points available.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 8, right: 8, bottom: 4, left: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#1e293b"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: "#1e293b" }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                  formatter={(value, name) => [
                    `${Number(value).toFixed(2)}%`,
                    name === "portfolio" ? "Portfolio" : "BTC",
                  ]}
                  labelFormatter={(label) => `Date: ${label}`}
                />
                <Legend
                  wrapperStyle={{ fontSize: "12px", color: "#94a3b8" }}
                  formatter={(value: string) =>
                    value === "portfolio" ? "Portfolio" : "BTC (Buy & Hold)"
                  }
                />
                <Line
                  type="monotone"
                  dataKey="portfolio"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                  name="portfolio"
                />
                <Line
                  type="monotone"
                  dataKey="btc"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  strokeDasharray="4 3"
                  dot={false}
                  name="btc"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Footnote ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2.5 text-xs text-slate-500">
        <Activity className="h-3 w-3 shrink-0" />
        {data.days}-day comparison against {data.symbol}. BTC data via yfinance.
        {refreshing && " Refreshing…"}
      </div>
    </div>
  );
}

// ── Stat card sub-component ──────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string;
  positive: boolean;
  icon: React.ReactNode;
  hint?: string;
}

function StatCard({ label, value, positive, icon, hint }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs text-slate-500">
          {icon}
          {label}
        </span>
        {hint && (
          <span className="text-[10px] text-slate-600" title={hint}>
            {hint}
          </span>
        )}
      </div>
      <p
        className={`mt-1 text-lg font-semibold tabular-nums ${
          positive ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export default BenchmarkComparison;