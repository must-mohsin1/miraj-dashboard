"use client";

import { useMemo } from "react";
import {
  ArrowUp,
  ArrowDown,
  TrendingUp,
  Minus,
  AlertTriangle,
} from "lucide-react";
import useSWR from "swr";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ScanDiffResponse, ScanDiffEntry, QqeSignals, StructureByTF } from "@/lib/types";

/**
 * MetricTrends — Client Component.
 *
 * Fetches `GET /api/v1/scan/{symbol}/diff` (last 2 scans) and renders a
 * compact card showing key metrics with trend arrows (↑ / ↓ / →).
 *
 * Each row shows the metric name, current value, and the direction of
 * change from the previous scan:
 *   - ↑ (green)  — improving (score up, QQE greener, structure more bullish)
 *   - ↓ (red)    — deteriorating
 *   - → (gray)   — no change
 *
 * Metrics tracked:
 *   - Confluence Score (with numeric delta)
 *   - QQE Daily / 4H / 1H (signal change)
 *   - Structure Daily (HH/HL/LH/LL change)
 *   - Direction (LONG / SHORT / NEUTRAL flip)
 *   - RSI Daily (cross or delta)
 *   - BB Squeeze Daily
 */

/** Fetcher used by SWR — attaches the Bearer token. */
async function fetcher<T>(url: string, token: string | null): Promise<T> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    const err = new Error(`GET ${url} failed: ${res.status}`) as Error & { status?: number };
    (err as { status?: number }).status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── Helpers ──────────────────────────────────────────────────────────────

/** Build a lookup map from field path → ScanDiffEntry. */
function buildChangeMap(changes: ScanDiffEntry[]): Map<string, ScanDiffEntry> {
  const map = new Map<string, ScanDiffEntry>();
  for (const c of changes) {
    map.set(c.field, c);
  }
  return map;
}

/** Direction of change: up=improved, down=worse, flat=no change. */
type TrendDir = "up" | "down" | "flat";

interface TrendStyle {
  icon: React.ReactNode;
  textColor: string;
  bgColor: string;
  borderColor: string;
}

const TREND_STYLES: Record<TrendDir, TrendStyle> = {
  up: {
    icon: <ArrowUp className="h-3.5 w-3.5" />,
    textColor: "text-emerald-400",
    bgColor: "bg-emerald-500/10",
    borderColor: "border-emerald-500/30",
  },
  down: {
    icon: <ArrowDown className="h-3.5 w-3.5" />,
    textColor: "text-red-400",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
  },
  flat: {
    icon: <Minus className="h-3.5 w-3.5" />,
    textColor: "text-slate-400",
    bgColor: "bg-slate-500/10",
    borderColor: "border-slate-600/30",
  },
};

interface MetricRow {
  /** Display name. */
  label: string;
  /** Current value string. */
  current: string;
  /** Optional detail (e.g. delta number, previous value). */
  detail: string | null;
  /** Direction of change. */
  trend: TrendDir;
  /** If true, this metric has a significant change worth highlighting. */
  highlight: boolean;
}

// ── Metric extractors ────────────────────────────────────────────────────

/** Extract the confluence score trend. */
function scoreMetric(
  changeMap: Map<string, ScanDiffEntry>,
  latestScore: number | null,
  previousScore: number | null,
): MetricRow {
  const entry = changeMap.get("score.total");
  const delta =
    latestScore != null && previousScore != null
      ? latestScore - previousScore
      : null;

  let trend: TrendDir = "flat";
  let detail: string | null = null;

  if (delta != null && Math.abs(delta) >= 0.05) {
    trend = delta > 0 ? "up" : "down";
    detail = `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`;
  } else if (!entry && previousScore != null) {
    detail = "unchanged";
  }

  return {
    label: "Confluence Score",
    current: latestScore != null ? latestScore.toFixed(1) : "—",
    detail: detail ?? (entry?.change ?? null),
    trend,
    highlight: entry?.severity === "major" || entry?.severity === "minor",
  };
}

/** Extract QQE signal trends per timeframe. */
function qqeMetrics(
  changeMap: Map<string, ScanDiffEntry>,
  currentSignals: QqeSignals | null,
): MetricRow[] {
  const tfs: Array<{ key: "daily" | "4h" | "1h"; label: string }> = [
    { key: "daily", label: "QQE Daily" },
    { key: "4h", label: "QQE 4H" },
    { key: "1h", label: "QQE 1H" },
  ];

  return tfs.map(({ key, label }) => {
    const entry = changeMap.get(`qqe_signals.${key}`);
    const current = currentSignals?.[key];
    const currentStr = current
      ? `${current.trend}${current.strength === "STRONG" ? "-STRONG" : ""}`
      : "—";

    let trend: TrendDir = "flat";
    let detail: string | null = null;
    let highlight = false;

    if (entry) {
      // Determine direction: green-ish is bullish, red-ish is bearish
      const oldVal = String(entry.old_value ?? "");
      const newVal = String(entry.new_value ?? "");
      const oldIsGreen = oldVal.includes("GREEN");
      const newIsGreen = newVal.includes("GREEN");

      if (oldIsGreen === newIsGreen) {
        trend = "flat"; // same side, just strength change
      } else if (newIsGreen && !oldIsGreen) {
        trend = "up"; // improved to green
      } else {
        trend = "down"; // worsened to red
      }
      detail = `was ${oldVal}`;
      highlight = entry.severity === "major";
    }

    return { label, current: currentStr, detail, trend, highlight };
  });
}

/** Extract market structure trend for a single timeframe. */
function structureMetric(
  changeMap: Map<string, ScanDiffEntry>,
  currentStructure: StructureByTF | null,
  tf: keyof StructureByTF,
  label: string,
): MetricRow {
  const entry = changeMap.get(`structure.${tf}`);
  const current = currentStructure?.[tf]?.label ?? "—";

  let trend: TrendDir = "flat";
  let detail: string | null = null;
  let highlight = false;

  if (entry) {
    const oldVal = String(entry.old_value ?? "");
    const newVal = String(entry.new_value ?? "");
    // HH/HL = bullish, LH/LL = bearish
    const oldBull = oldVal === "HH" || oldVal === "HL";
    const newBull = newVal === "HH" || newVal === "HL";

    if (oldBull === newBull) {
      trend = "flat";
    } else if (newBull && !oldBull) {
      trend = "up";
    } else {
      trend = "down";
    }
    detail = `was ${oldVal}`;
    highlight = true; // structure changes are always major
  }

  return { label, current, detail, trend, highlight };
}

/** Extract direction trend. */
function directionMetric(
  changeMap: Map<string, ScanDiffEntry>,
  currentDirection: string | null,
): MetricRow {
  const entry = changeMap.get("trade_plan.direction");
  const current = currentDirection ?? "—";

  let trend: TrendDir = "flat";
  let detail: string | null = null;
  let highlight = false;

  if (entry) {
    const oldVal = String(entry.old_value ?? "").toUpperCase();
    detail = `was ${oldVal}`;
    highlight = true;

    // LONG = bullish, SHORT = bearish, NEUTRAL = flat
    const newVal = current.toUpperCase();
    if (newVal === oldVal) {
      trend = "flat";
    } else if (newVal === "LONG" && oldVal !== "LONG") {
      trend = "up";
    } else if (newVal === "SHORT") {
      trend = "down";
    } else {
      trend = "flat";
    }
  }

  return { label: "Direction", current, detail, trend, highlight };
}

/** Extract indicator (RSI / BB squeeze) trends. */
function indicatorMetric(
  changeMap: Map<string, ScanDiffEntry>,
  field: string,
  label: string,
): MetricRow | null {
  const entry = changeMap.get(field);
  if (!entry) return null;

  let trend: TrendDir = "flat";
  let detail: string | null = entry.change ?? null;

  if (field.includes("rsi")) {
    const oldVal = Number(entry.old_value);
    const newVal = Number(entry.new_value);
    if (!isNaN(oldVal) && !isNaN(newVal)) {
      trend = newVal > oldVal ? "up" : "down";
    }
  } else if (field.includes("bb_squeeze")) {
    // squeeze → released = up (expansion), released → squeeze = down
    const change = entry.change ?? "";
    if (change.includes("→ released")) trend = "up";
    else if (change.includes("→ squeezing")) trend = "down";
  }

  return {
    label,
    current: String(entry.new_value ?? "—"),
    detail,
    trend,
    highlight: false,
  };
}

// ── Component ────────────────────────────────────────────────────────────

interface MetricTrendsProps {
  symbol: string;
  token: string | null;
  /** Current confluence score from the scan result. */
  currentScore?: number | null;
  /** Current QQE signals from the scan result. */
  currentQqe?: QqeSignals | null;
  /** Current market structure from the scan result. */
  currentStructure?: StructureByTF | null;
  /** Current trade direction from the scan result. */
  currentDirection?: string | null;
}

export function MetricTrends({
  symbol,
  token,
  currentScore,
  currentQqe,
  currentStructure,
  currentDirection,
}: MetricTrendsProps) {
  const { data, error, isLoading } = useSWR<ScanDiffResponse>(
    token ? [`/api/v1/scan/${encodeURIComponent(symbol)}/diff`, token] : null,
    ([url, tok]: [string, string | null]) => fetcher<ScanDiffResponse>(url, tok),
  );

  const rows = useMemo<MetricRow[]>(() => {
    if (!data) return [];

    const changeMap = buildChangeMap(data.changes);
    const rows: MetricRow[] = [];

    // 1. Confluence Score
    rows.push(
      scoreMetric(changeMap, data.latest_score, data.previous_score),
    );

    // 2. QQE signals (daily, 4h, 1h)
    rows.push(...qqeMetrics(changeMap, currentQqe ?? null));

    // 3. Market Structure (daily)
    if (currentStructure) {
      rows.push(structureMetric(changeMap, currentStructure, "daily", "Structure Daily"));
    }

    // 4. Direction
    rows.push(directionMetric(changeMap, currentDirection ?? null));

    // 5. Optional indicator diffs (RSI, BB squeeze)
    const rsiDaily = indicatorMetric(changeMap, "indicators.daily.rsi", "RSI Daily");
    if (rsiDaily) rows.push(rsiDaily);

    const bbSqueeze = indicatorMetric(changeMap, "indicators.daily.bb_squeeze", "BB Squeeze Daily");
    if (bbSqueeze) rows.push(bbSqueeze);

    return rows;
  }, [data, currentQqe, currentStructure, currentDirection]);

  // ── Loading state ─────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="h-4 w-4 text-emerald-400" />
          <h3 className="text-sm font-medium text-slate-300">Metric Trends</h3>
        </div>
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error / empty state ────────────────────────────────────────────────
  if (error) {
    const status = (error as Error & { status?: number }).status;
    if (status === 404) {
      return (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="h-4 w-4 text-slate-500" />
            <h3 className="text-sm font-medium text-slate-400">Metric Trends</h3>
          </div>
          <p className="text-xs text-slate-500">
            Not enough scans yet — run at least two scans for {symbol} to see trends.
          </p>
        </div>
      );
    }
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <h3 className="text-sm font-medium text-slate-400">Metric Trends</h3>
        </div>
        <p className="text-xs text-slate-500">Could not load trends for {symbol}.</p>
      </div>
    );
  }

  if (!data || rows.length === 0) {
    return null;
  }

  // ── Data state ─────────────────────────────────────────────────────────
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-emerald-400" />
          <h3 className="text-sm font-medium text-slate-300">Metric Trends</h3>
        </div>
        <span className="text-[10px] text-slate-500">
          vs previous scan
        </span>
      </div>

      <div className="space-y-1.5">
        {rows.map((row, i) => {
          const styles = TREND_STYLES[row.trend];
          return (
            <div
              key={`${row.label}-${i}`}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm",
                styles.bgColor,
                row.highlight && styles.borderColor,
                row.highlight ? "border" : "border border-transparent",
              )}
            >
              {/* Trend arrow */}
              <span className={cn("shrink-0", styles.textColor)}>
                {styles.icon}
              </span>

              {/* Metric label */}
              <span className="min-w-0 shrink-0 font-medium text-slate-300">
                {row.label}
              </span>

              {/* Spacer */}
              <span className="flex-1" />

              {/* Current value */}
              <span className={cn("font-semibold tabular-nums", styles.textColor)}>
                {row.current}
              </span>

              {/* Detail (delta / previous value) */}
              {row.detail && (
                <span className="text-xs text-slate-500 truncate max-w-[200px]">
                  {row.detail}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Score delta summary */}
      {data.previous_score != null && data.latest_score != null && (
        <div className="mt-3 pt-2 border-t border-slate-800 flex items-center justify-between text-xs">
          <span className="text-slate-500">
            {data.previous_scan_at
              ? new Date(data.previous_scan_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "Previous"}
          </span>
          <span className="text-slate-600">→</span>
          <span className="text-slate-500">
            {data.latest_scan_at
              ? new Date(data.latest_scan_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "Latest"}
          </span>
        </div>
      )}
    </div>
  );
}

export default MetricTrends;
