"use client";

import { useEffect, useState } from "react";
import { Loader2, Shield, Layers, ArrowLeftRight, AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import type { HealthScore } from "@/lib/types";

/**
 * HealthScorePanel — Client Component.
 *
 * Fetches `GET /api/v1/analytics/{exchange}/health` and renders:
 *  - Large letter-grade badge (A/B/C/D/F) colour-coded
 *  - Three bars: Diversification (green=good), Correlation Risk (red=high),
 *    Concentration Risk (red=high)
 *  - Actionable recommendations list
 *
 * Auto-refreshes every 5 minutes.
 */

interface HealthScorePanelProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

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
      const res = await fetch(`/api/v1/analytics/${exchange}/health`, { headers });
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

  // ── Render: loading ──────────────────────────────────────────────────
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading health score…
      </div>
    );
  }

  // ── Render: error ────────────────────────────────────────────────────
  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        Failed to load health score: {error}
      </div>
    );
  }

  if (!data) return null;

  if (data.grade === null || data.health_score === null) {
    return (
      <div className="border border-border bg-card/60 p-4">
        <div className="flex items-center gap-2 text-sm text-card-foreground">
          <Shield className="h-4 w-4 text-muted-foreground" />
          <span>Not applicable</span>
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {readableHealthReason(data.health_reason)}
        </div>
        {data.recommendations.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {data.recommendations.map((rec, i) => (
              <li key={i} className="text-sm text-card-foreground">{rec}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  // ── Colour helpers ───────────────────────────────────────────────────
  const gradeColors: Record<string, string> = {
    A: "bg-emerald-500 text-white",
    B: "bg-emerald-400/80 text-white",
    C: "bg-amber-500 text-white",
    D: "bg-orange-500 text-white",
    F: "bg-red-500 text-white",
  };
  const gradeRing: Record<string, string> = {
    A: "ring-emerald-500/40",
    B: "ring-emerald-400/30",
    C: "ring-amber-500/30",
    D: "ring-orange-500/30",
    F: "ring-red-500/40",
  };

  const grade = (data.grade || "F").toUpperCase();

  return (
    <div className="space-y-4">
      {/* ── Grade badge row ─────────────────────────────────────────── */}
      <div className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div
          className={cn(
            "flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl text-3xl font-bold ring-2 transition-all",
            gradeColors[grade] ?? gradeColors.F,
            gradeRing[grade] ?? gradeRing.F,
          )}
        >
          {grade}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <Shield className="h-4 w-4 text-emerald-400" />
            <span>
              Score: <strong className="text-slate-100">{data.health_score.toFixed(1)}</strong> / 100
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {data.open_positions} position{data.open_positions !== 1 ? "s" : ""} across{" "}
            {data.unique_assets} asset{data.unique_assets !== 1 ? "s" : ""}
          </div>
        </div>
        {refreshing && (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-slate-500" />
        )}
      </div>

      {/* ── Three metric bars ────────────────────────────────────────── */}
      <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        {/* Diversification */}
        <MetricBar
          label="Diversification"
          value={data.diversification_score}
          icon={<Layers className="h-4 w-4 text-emerald-400" />}
          goodDirection="higher"
          barColor="bg-emerald-500"
        />

        {/* Correlation Risk */}
        <MetricBar
          label="Correlation Risk"
          value={data.correlation_risk}
          icon={<ArrowLeftRight className="h-4 w-4 text-amber-400" />}
          goodDirection="lower"
          barColor="bg-amber-500"
        />

        {/* Concentration Risk */}
        <MetricBar
          label="Concentration Risk"
          value={data.concentration_risk}
          icon={<AlertTriangle className="h-4 w-4 text-red-400" />}
          goodDirection="lower"
          barColor="bg-red-500"
        />
      </div>

      {/* ── Recommendations ──────────────────────────────────────────── */}
      {data.recommendations.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Recommendations
          </h4>
          <ul className="space-y-1.5">
            {data.recommendations.map((rec, i) => (
              <li
                key={i}
                className="flex items-start gap-2 text-sm text-slate-300"
              >
                <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500/60" />
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Metric bar sub-component ──────────────────────────────────────────────

interface MetricBarProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  /** Whether a higher or lower value is considered good. */
  goodDirection: "higher" | "lower";
  barColor: string;
}

function MetricBar({ label, value, icon, goodDirection, barColor }: MetricBarProps) {
  const clamped = Math.min(100, Math.max(0, value));
  const isGood = goodDirection === "higher" ? value >= 60 : value < 40;
  const isWarning =
    goodDirection === "higher"
      ? value >= 30 && value < 60
      : value >= 40 && value < 70;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="flex items-center gap-1.5 text-slate-400">
          {icon}
          {label}
        </span>
        <span
          className={cn(
            "font-semibold tabular-nums",
            isGood ? "text-emerald-400" : isWarning ? "text-amber-400" : "text-red-400",
          )}
        >
          {clamped.toFixed(1)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className={cn("h-full rounded-full transition-all duration-500", barColor, {
            "bg-emerald-500": goodDirection === "higher" && isGood,
            "bg-amber-500": isWarning,
            "bg-red-500":
              (goodDirection === "higher" && !isGood && !isWarning) ||
              (goodDirection === "lower" && value >= 70),
          })}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

export default HealthScorePanel;

function readableHealthReason(reason?: string | null): string {
  if (reason === "no_open_positions") return "No open positions";
  if (reason === "no_snapshot_data") return "No snapshot data";
  return reason ? reason.replaceAll("_", " ") : "Unavailable";
}