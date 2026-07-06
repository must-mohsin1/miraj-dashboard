"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Loader2, RefreshCw } from "lucide-react";

import type { HealthScore } from "@/lib/types";

/**
 * HealthScorePanel — Client Component.
 *
 * Fetches `GET /api/v1/analytics/{exchange}/health` and renders the
 * portfolio health score: a large colored grade badge (A/B/C/D/F),
 * three metric bars (diversification, correlation risk, concentration
 * risk), and a list of actionable recommendations.
 *
 * Auto-refreshes every 5 minutes.
 */

interface HealthScorePanelProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc" or "binance"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

/** Grade → color + label. */
const GRADE_COLORS: Record<string, { bg: string; text: string; ring: string }> = {
  A: { bg: "bg-emerald-500/15", text: "text-emerald-400", ring: "border-emerald-500/40" },
  B: { bg: "bg-lime-500/15", text: "text-lime-400", ring: "border-lime-500/40" },
  C: { bg: "bg-amber-500/15", text: "text-amber-400", ring: "border-amber-500/40" },
  D: { bg: "bg-orange-500/15", text: "text-orange-400", ring: "border-orange-500/40" },
  F: { bg: "bg-red-500/15", text: "text-red-400", ring: "border-red-500/40" },
};

export function HealthScorePanel({ token, exchange }: HealthScorePanelProps) {
  const [data, setData] = useState<HealthScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchHealth() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/analytics/${exchange}/health`, {
        headers,
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: HealthScore = await res.json();
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
      await fetchHealth();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchHealth();
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
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-8 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading portfolio health…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-4 py-8 text-sm text-red-400">
        Failed to load portfolio health: {error}
      </div>
    );
  }

  if (!data) return null;

  const gradeColors =
    GRADE_COLORS[data.grade] ?? GRADE_COLORS.F;

  // For diversification: higher = better (green = high).
  // For correlation_risk & concentration_risk: higher = worse (red = high).
  const diversicolor =
    data.diversification_score >= 70
      ? "#22c55e"
      : data.diversification_score >= 40
        ? "#f97316"
        : "#ef4444";

  const corrColor =
    data.correlation_risk >= 70
      ? "#ef4444"
      : data.correlation_risk >= 40
        ? "#f97316"
        : "#22c55e";

  const concColor =
    data.concentration_risk >= 70
      ? "#ef4444"
      : data.concentration_risk >= 40
        ? "#f97316"
        : "#22c55e";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-emerald-400" />
          <h3 className="text-sm font-semibold text-slate-300">
            Portfolio Health
          </h3>
        </div>
        <button
          type="button"
          onClick={fetchHealth}
          className="text-slate-500 transition hover:text-slate-300"
          title="Refresh health score"
        >
          {refreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* ── Grade badge + score ── */}
        <div className="flex flex-col items-center justify-center rounded-lg border border-slate-800/60 bg-slate-950/40 p-4">
          <div
            className={`flex h-20 w-20 items-center justify-center rounded-full border-2 ${gradeColors.ring} ${gradeColors.bg}`}
          >
            <span
              className={`text-3xl font-bold ${gradeColors.text}`}
            >
              {data.grade}
            </span>
          </div>
          <div className="mt-3 text-center">
            <p className="text-2xl font-bold tabular-nums text-slate-100">
              {data.health_score.toFixed(1)}
            </p>
            <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
              Health Score / 100
            </p>
          </div>
          <div className="mt-2 flex gap-3 text-[10px] text-slate-500">
            <span>
              {data.open_positions} pos
            </span>
            <span>·</span>
            <span>{data.unique_assets} assets</span>
          </div>
        </div>

        {/* ── Metric bars ── */}
        <div className="space-y-4 lg:col-span-2">
          <MetricBar
            label="Diversification"
            value={data.diversification_score}
            max={100}
            color={diversicolor}
            higherIsBetter
          />
          <MetricBar
            label="Correlation Risk"
            value={data.correlation_risk}
            max={100}
            color={corrColor}
            higherIsBetter={false}
          />
          <MetricBar
            label="Concentration Risk"
            value={data.concentration_risk}
            max={100}
            color={concColor}
            higherIsBetter={false}
          />
        </div>
      </div>

      {/* ── Recommendations ── */}
      {data.recommendations.length > 0 && (
        <div className="mt-4 rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            <h4 className="text-xs font-semibold text-slate-300">
              Recommendations
            </h4>
          </div>
          <ul className="space-y-1.5">
            {data.recommendations.map((rec, i) => (
              <li
                key={i}
                className="flex gap-2 text-xs text-slate-400"
              >
                <span className="mt-1 inline-block h-1 w-1 flex-shrink-0 rounded-full bg-slate-600" />
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="mt-2 text-xs text-amber-500">
          (refresh failed: {error})
        </div>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface MetricBarProps {
  label: string;
  value: number;
  max: number;
  color: string;
  higherIsBetter: boolean;
}

function MetricBar({
  label,
  value,
  max,
  color,
  higherIsBetter,
}: MetricBarProps) {
  const pct = Math.min(100, (value / max) * 100);
  // Hint text: which end is good.
  const hint = higherIsBetter ? "higher = better" : "lower = better";

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
          {label}
        </span>
        <span
          className="text-sm font-bold tabular-nums"
          style={{ color }}
        >
          {value.toFixed(1)}
        </span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${pct}%`,
            backgroundColor: color,
          }}
        />
      </div>
      <div className="mt-0.5 text-right text-[9px] text-slate-600">
        {hint}
      </div>
    </div>
  );
}

export default HealthScorePanel;
