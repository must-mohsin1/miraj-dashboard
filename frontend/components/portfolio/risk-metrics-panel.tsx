"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import type { RiskMetrics } from "@/lib/types";

/**
 * RiskMetricsPanel — Client Component.
 *
 * Fetches `GET /api/v1/analytics/{exchange}/risk` and renders a summary of
 * portfolio risk: total/net exposure, average liquidation distance, margin
 * usage, and a 0–100 risk-score gauge (green < 30, amber 30–60, red > 60).
 *
 * Auto-refreshes every 5 minutes alongside the dashboard auto-refresh.
 */

interface RiskMetricsPanelProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

export function RiskMetricsPanel({ token, exchange }: RiskMetricsPanelProps) {
  const [data, setData] = useState<RiskMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchRisk() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/analytics/${exchange}/risk`, { headers });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: RiskMetrics = await res.json();
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
      await fetchRisk();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchRisk();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  // ── Render states ─────────────────────────────────────────────────
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading risk metrics…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        Failed to load risk metrics: {error}
      </div>
    );
  }

  if (!data) return null;

  const risk = data.risk_score;
  const riskColor = risk >= 60 ? "#ef4444" : risk >= 30 ? "#f97316" : "#22c55e";
  const riskLabel = risk >= 60 ? "High" : risk >= 30 ? "Moderate" : "Low";

  const netIsLong = data.net_exposure_usd >= 0;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">Risk Metrics</h3>
        <button
          type="button"
          onClick={fetchRisk}
          className="text-slate-500 transition hover:text-slate-300"
          title="Refresh risk metrics"
        >
          {refreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {/* Risk score bar + metrics grid */}
      <div className="space-y-4">
        {/* Risk score horizontal bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Risk Score
              </span>
              <span
                className="text-sm font-bold tabular-nums"
                style={{ color: riskColor }}
              >
                {risk.toFixed(0)} / 100 — {riskLabel}
              </span>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${Math.min(100, risk)}%`,
                  backgroundColor: riskColor,
                }}
              />
            </div>
            {/* Zone markers */}
            <div className="mt-1 flex justify-between text-[9px] text-slate-600">
              <span>0 (Safe)</span>
              <span>30</span>
              <span>60</span>
              <span>100 (Danger)</span>
            </div>
          </div>
        </div>

        {/* Metric grid */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <MetricCard
            label="Total Exposure"
            value={usd(data.total_exposure_usd)}
            sublabel={`${data.open_positions} position${data.open_positions === 1 ? "" : "s"}`}
          />
          <MetricCard
            label="Net Exposure"
            value={usd(Math.abs(data.net_exposure_usd))}
            sublabel={netIsLong ? "Net Long" : "Net Short"}
            sublabelColor={netIsLong ? "text-emerald-400" : "text-red-400"}
          />
          <MetricCard
            label="Long / Short"
            value={usd(data.long_exposure_usd)}
            sublabel={`Short: ${usd(data.short_exposure_usd)}`}
          />
          <MetricCard
            label="Avg Liq Distance"
            value={
              data.avg_liquidation_distance_pct != null
                ? `${data.avg_liquidation_distance_pct.toFixed(2)}%`
                : "—"
            }
            sublabel="from mark price"
            sublabelColor={
              data.avg_liquidation_distance_pct != null
                ? data.avg_liquidation_distance_pct < 5
                  ? "text-red-400"
                  : data.avg_liquidation_distance_pct < 10
                    ? "text-amber-400"
                    : "text-emerald-400"
                : "text-slate-500"
            }
          />
          <MetricCard
            label="Margin Usage"
            value={`${data.margin_usage_pct.toFixed(1)}%`}
            sublabel={usd(data.total_margin_used)}
            sublabelColor={
              data.margin_usage_pct > 80
                ? "text-red-400"
                : data.margin_usage_pct > 50
                  ? "text-amber-400"
                  : "text-slate-400"
            }
          />
          <MetricCard
            label="Total Balance"
            value={data.total_balance_usd != null ? usd(data.total_balance_usd) : "—"}
            sublabel="est. USD"
          />
        </div>
      </div>

      {error && (
        <div className="mt-2 text-xs text-amber-500">
          (refresh failed: {error})
        </div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────


interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
  sublabelColor?: string;
}

function MetricCard({ label, value, sublabel, sublabelColor = "text-slate-500" }: MetricCardProps) {
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-bold tabular-nums text-slate-100">
        {value}
      </p>
      {sublabel && (
        <p className={`text-[10px] tabular-nums ${sublabelColor}`}>{sublabel}</p>
      )}
    </div>
  );
}

/** Format a USD amount compactly (e.g. $12.3K, $1.2M). */
function usd(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

export default RiskMetricsPanel;
