"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ScanAccuracyResponse } from "@/lib/types";

/**
 * ScanAccuracyChart — Client Component.
 *
 * Fetches `GET /api/v1/analytics/{exchange}/scan-accuracy` and renders a
 * recharts bar chart of win rate per confluence-score band.
 *
 *  - X-axis: confluence-score bands (0-5, 5-10, …, 25-30)
 *  - Y-axis: win rate %
 *  - Green bars for high win rate (≥ 50%), red for low (< 50%)
 *
 * Below the chart, a caption shows "Based on N closed positions" where N is
 * the total number of trades linked to a pre-entry scan.
 */

interface ScanAccuracyChartProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const TOOLTIP_STYLE = {
  backgroundColor: "#0f172a",
  border: "1px solid #1e293b",
  borderRadius: "0.5rem",
  color: "#e2e8f0",
  fontSize: "0.75rem",
} as const;

/** Win-rate threshold above which a band is considered "high" (green). */
const HIGH_WIN_RATE = 50;

interface TooltipPayloadItem {
  payload: {
    score_band: string;
    win_rate: number;
    total_trades: number;
    winning_trades: number;
    avg_pnl: number;
  };
}

function AccuracyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <div className="font-medium text-slate-100">
        Score {p.score_band}
      </div>
      <div className="mt-0.5 text-emerald-400">
        Win rate: {p.win_rate.toFixed(1)}%
      </div>
      <div className="text-slate-400">
        {p.winning_trades} / {p.total_trades} trades won
      </div>
      <div
        className={
          p.avg_pnl >= 0 ? "text-emerald-400" : "text-red-400"
        }
      >
        Avg PnL: {p.avg_pnl >= 0 ? "+" : ""}
        {p.avg_pnl.toFixed(2)}
      </div>
    </div>
  );
}

export function ScanAccuracyChart({ token, exchange }: ScanAccuracyChartProps) {
  const [data, setData] = useState<ScanAccuracyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchData() {
    setRefreshing(true);
    try {
      const res = await fetch(
        `/api/v1/analytics/${exchange}/scan-accuracy`,
        { headers },
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: ScanAccuracyResponse = await res.json();
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
    (async () => {
      if (cancelled) return;
      await fetchData();
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Computing scan accuracy…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 p-4 text-sm text-red-400">
        Failed to load scan accuracy: {error}
      </div>
    );
  }

  const bands = data?.bands ?? [];
  const totalTrades = data?.total_trades ?? 0;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-slate-300">
            Scan Accuracy by Confluence Score
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Win rate of trades grouped by the confluence score of the scan
            that preceded entry.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchData}
          disabled={refreshing}
          className="inline-flex items-center gap-1 text-xs text-slate-400 transition hover:text-slate-200 disabled:opacity-50"
        >
          {refreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </button>
      </div>

      {bands.length === 0 || totalTrades === 0 ? (
        <div className="flex h-64 items-center justify-center rounded-lg border border-slate-800 bg-slate-900/40 text-sm text-slate-400">
          No closed positions linked to scans yet.
        </div>
      ) : (
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={bands}
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#1e293b"
                vertical={false}
              />
              <XAxis
                dataKey="score_band"
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fill: "#64748b", fontSize: 11 }}
                axisLine={{ stroke: "#1e293b" }}
                tickLine={false}
                width={40}
                tickFormatter={(v: number) => `${v}%`}
              />
              <Tooltip
                content={<AccuracyTooltip />}
                cursor={{ fill: "#1e293b50" }}
              />
              <Bar
                dataKey="win_rate"
                name="Win Rate"
                radius={[4, 4, 0, 0]}
                maxBarSize={80}
              >
                {bands.map((b, i) => (
                  <Cell
                    key={i}
                    fill={
                      b.total_trades === 0
                        ? "#1e293b" // empty band — slate
                        : b.win_rate >= HIGH_WIN_RATE
                          ? "#10b981" // emerald-500 (high win rate)
                          : "#f87171" // red-400 (low win rate)
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Per-band legend / detail row */}
      {bands.length > 0 && totalTrades > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
          <div className="flex flex-wrap gap-4 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" />
              ≥ {HIGH_WIN_RATE}% win rate
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-red-400" />
              &lt; {HIGH_WIN_RATE}% win rate
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-slate-800" />
              No trades
            </span>
          </div>
          <span className="text-xs text-slate-400">
            Based on{" "}
            <span className="font-semibold text-slate-200">{totalTrades}</span>{" "}
            closed {totalTrades === 1 ? "position" : "positions"}
          </span>
        </div>
      )}

      {error && (
        <p className="mt-2 text-xs text-amber-500">
          (refresh failed: {error})
        </p>
      )}
    </div>
  );
}

export default ScanAccuracyChart;
