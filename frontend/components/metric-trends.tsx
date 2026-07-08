"use client";

import { ArrowDown, ArrowUp, Minus, TrendingUp, TrendingDown } from "lucide-react";
import useSWR from "swr";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ScanDiffResponse, Severity } from "@/lib/types";

/**
 * MetricTrends — shows compact directional trend arrows for key metrics
 * derived from the signal diff endpoint.
 *
 * Displays a horizontal row of metric "chips" each showing:
 *   - metric name (score, QQE daily, structure daily, direction)
 *   - up/down/flat arrow reflecting the current diff state
 *   - colour coding matching the change severity
 *
 * Props:
 *   - symbol: the trading pair (e.g. "BTC-USD")
 *   - token:  the signed-in user's JWT
 *   - currentScore: current confluence score from the latest scan
 *   - currentQqe: current QQE data from the latest scan
 *   - currentStructure: current structure data from the latest scan
 *   - currentDirection: current trade direction (LONG/SHORT)
 */

interface MetricTrendsProps {
  symbol: string;
  token: string | null;
  currentScore: number;
  currentQqe: unknown;
  currentStructure: unknown;
  currentDirection: string | null;
}

/** Fetcher used by SWR. */
async function fetcher<T>(url: string, token: string | null): Promise<T> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    const err = new Error(`GET ${url} failed: ${res.status} ${res.statusText}`) as Error & { status?: number };
    (err as { status?: number }).status = res.status;
    throw err;
  }
  return (await res.json()) as T;
}

/** Pick a trend icon and colour based on the change text. */
function trendForChange(change: string, severity: Severity) {
  const up = change.includes("▲") || change.includes("bullish") || change.includes("GREEN");
  const down = change.includes("▼") || change.includes("bearish") || change.includes("RED");
  const isMajor = severity === "major";

  if (up) {
    return {
      icon: <ArrowUp className="h-3 w-3" />,
      color: isMajor ? "text-emerald-400" : "text-emerald-400/70",
    };
  }
  if (down) {
    return {
      icon: <ArrowDown className="h-3 w-3" />,
      color: isMajor ? "text-red-400" : "text-red-400/70",
    };
  }
  return {
    icon: <Minus className="h-3 w-3" />,
    color: "text-slate-500",
  };
}

/** Extract the best trend indicator for a given field prefix. */
function extractTrend(
  changes: ScanDiffResponse["changes"],
  fieldPrefix: string,
): { change: string; severity: Severity } | null {
  for (const c of changes) {
    if (c.field.startsWith(fieldPrefix)) {
      return { change: c.change, severity: c.severity };
    }
  }
  return null;
}

export function MetricTrends({
  symbol,
  token,
  currentScore,
  currentQqe: currentQqe,
  currentStructure: currentStructure,
  currentDirection,
}: MetricTrendsProps) {
  const { data, error, isLoading } = useSWR<ScanDiffResponse>(
    token ? [`/api/v1/scan/${encodeURIComponent(symbol)}/diff`, token] : null,
    ([url, tok]: [string, string | null]) => fetcher<ScanDiffResponse>(url, tok),
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-3">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-6 w-20 rounded-full" />
        ))}
      </div>
    );
  }

  if (error || !data || data.changes.length === 0) {
    return null; // No diff available — hide
  }

  // Extract signals from the diff response
  const scoreTrend = extractTrend(data.changes, "score.total");
  const qqeDailyTrend = extractTrend(data.changes, "qqe_signals.daily");
  const structDailyTrend = extractTrend(data.changes, "structure.daily");
  const volDailyTrend = extractTrend(data.changes, "volume.daily");
  const macdTrend = extractTrend(data.changes, "indicators.daily.macd_cross");

  const metrics: Array<{
    label: string;
    icon: React.ReactNode;
    color: string;
    value: string;
  }> = [];

  // Score
  if (scoreTrend) {
    const t = trendForChange(scoreTrend.change, scoreTrend.severity);
    metrics.push({
      label: "Score",
      icon: t.icon,
      color: t.color,
      value: currentScore.toFixed(1),
    });
  }

  // QQE daily
  if (qqeDailyTrend) {
    const t = trendForChange(qqeDailyTrend.change, qqeDailyTrend.severity);
    metrics.push({
      label: "QQE D",
      icon: t.icon,
      color: t.color,
      value: qqeDailyTrend.change.split(" → ")[1] ?? qqeDailyTrend.change,
    });
  }

  // Structure daily
  if (structDailyTrend) {
    const t = trendForChange(structDailyTrend.change, structDailyTrend.severity);
    metrics.push({
      label: "Struct D",
      icon: t.icon,
      color: t.color,
      value: structDailyTrend.change.split(" → ")[1] ?? structDailyTrend.change,
    });
  }

  // Volume
  if (volDailyTrend) {
    const isUp = volDailyTrend.change.includes("spike");
    const isDown = volDailyTrend.change.includes("drop");
    metrics.push({
      label: "Vol",
      icon: isUp ? <TrendingUp className="h-3 w-3" /> : isDown ? <TrendingDown className="h-3 w-3" /> : <Minus className="h-3 w-3" />,
      color: isUp ? "text-blue-400" : isDown ? "text-orange-400" : "text-slate-500",
      value: volDailyTrend.change.includes("×")
        ? volDailyTrend.change.split(" ")[1] ?? "—"
        : "—",
    });
  }

  // MACD
  if (macdTrend) {
    const t = trendForChange(macdTrend.change, macdTrend.severity);
    metrics.push({
      label: "MACD",
      icon: t.icon,
      color: t.color,
      value: macdTrend.change.split(" → ")[1]?.split(" ")[0] ?? macdTrend.change,
    });
  }

  // Direction
  if (currentDirection) {
    const dirTrend = extractTrend(data.changes, "trade_plan.direction");
    if (dirTrend) {
      metrics.push({
        label: "Dir",
        icon: currentDirection === "LONG" ? (
          <TrendingUp className="h-3 w-3 text-emerald-400" />
        ) : (
          <TrendingDown className="h-3 w-3 text-red-400" />
        ),
        color: currentDirection === "LONG" ? "text-emerald-400" : "text-red-400",
        value: currentDirection,
      });
    }
  }

  if (metrics.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {metrics.map((m) => (
        <span
          key={m.label}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border border-slate-700/50 bg-slate-800/30 px-2 py-0.5 text-[11px] font-medium",
            m.color,
          )}
        >
          {m.icon}
          <span>{m.label}</span>
          <span className="font-semibold text-slate-200">{m.value}</span>
        </span>
      ))}
    </div>
  );
}

export default MetricTrends;
