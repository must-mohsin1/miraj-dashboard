"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  BarChart3,
  FlipHorizontal,
  Layers,
  LineChart,
  Minus,
  TrendingUp,
  Volume2,
} from "lucide-react";
import useSWR from "swr";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ScanDiffResponse, ScanDiffEntry, Severity } from "@/lib/types";

/**
 * SignalChangesPanel — Client Component.
 *
 * Fetches `GET /api/v1/scan/{symbol}/diff` (last 2 scans) and renders a
 * timeline of changes with colour coding by severity:
 *   - major → red    (QQE flip, structure change, score drop >5)
 *   - minor → amber  (score change 1–5, indicator tweaks)
 *   - info  → blue   (rationale text, confirmation flips)
 *
 * Each change shows the field name, an old → new transition, and a
 * severity badge. Score changes render an up/down arrow.
 *
 * Props:
 *   - symbol: the trading pair (e.g. "BTC-USD")
 *   - token:  the signed-in user's JWT (passed from the Server Component
 *             parent, used to attach a Bearer header to the SWR fetch).
 *   - limit?: max number of changes to show (default 5 — compact view)
 *   - variant?: "compact" (default) shows up to `limit` most-recent changes;
 *               "full" shows all changes from the diff.
 */

/** Fetcher used by SWR — attaches the Bearer token. */
async function fetcher<T>(url: string, token: string | null): Promise<T> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    const err = new Error(`GET ${url} failed: ${res.status} ${res.statusText}`) as Error & { status?: number };
    (err as { status?: number }).status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

interface SignalChangesPanelProps {
  symbol: string;
  token: string | null;
  /** Max changes to render in the compact view. Default 5. */
  limit?: number;
  /** "compact" (default) or "full". */
  variant?: "compact" | "full";
}

/** Tailwind classes for each severity. */
const SEVERITY_STYLES: Record<Severity, { dot: string; badge: string; row: string; text: string }> = {
  major: {
    dot: "bg-red-500",
    badge: "bg-red-500/10 text-red-400 border-red-500/30",
    row: "border-red-500/30 bg-red-500/5",
    text: "text-red-400",
  },
  minor: {
    dot: "bg-amber-500",
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    row: "border-amber-500/30 bg-amber-500/5",
    text: "text-amber-400",
  },
  info: {
    dot: "bg-blue-500",
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/30",
    row: "border-blue-500/30 bg-blue-500/5",
    text: "text-blue-400",
  },
};

/** Map a change's field path to a display category label. */
function categoryLabel(field: string): string {
  if (field.startsWith("score.")) return "Score";
  if (field.startsWith("qqe_signals.")) return "QQE";
  if (field.startsWith("structure.")) return "Structure";
  if (field.startsWith("trade_plan.")) return "Trade Plan";
  if (field.startsWith("patterns.")) return "Patterns";
  if (field.startsWith("volume.")) return "Volume";
  if (field.startsWith("indicators.")) return "Indicators";
  return "Other";
}

/** Sort key for ordering categories in the UI. */
function categoryOrder(field: string): number {
  const order: Record<string, number> = {
    "Score": 0,
    "QQE": 1,
    "Structure": 2,
    "Volume": 3,
    "Indicators": 4,
    "Patterns": 5,
    "Trade Plan": 6,
  };
  return order[categoryLabel(field)] ?? 99;
}

/** Pick an icon for a change based on its field/severity. */
function changeIcon(entry: ScanDiffEntry) {
  const f = entry.field;
  if (f.startsWith("score.total") || f.startsWith("score.")) {
    // Score change: arrow up/down
    const isUp = entry.change.includes("▲");
    const isDown = entry.change.includes("▼");
    if (isUp) return <ArrowUp className="h-3.5 w-3.5 text-emerald-400" />;
    if (isDown) return <ArrowDown className="h-3.5 w-3.5 text-red-400" />;
  }
  if (f.startsWith("qqe_signals.") || f.startsWith("structure.")) {
    return <FlipHorizontal className="h-3.5 w-3.5 text-amber-400" />;
  }
  if (f.startsWith("trade_plan.direction") || f.startsWith("trade_plan.trade_decision")) {
    return <FlipHorizontal className="h-3.5 w-3.5 text-amber-400" />;
  }
  if (f.startsWith("volume.")) {
    return <BarChart3 className="h-3.5 w-3.5 text-blue-400" />;
  }
  if (f.startsWith("indicators.")) {
    if (f.includes("macd_cross")) return <TrendingUp className="h-3.5 w-3.5 text-purple-400" />;
    if (f.includes("ema_alignment")) return <Activity className="h-3.5 w-3.5 text-purple-400" />;
    if (f.includes("bb_squeeze")) return <Layers className="h-3.5 w-3.5 text-sky-400" />;
    if (f.includes("ema_cross")) return <LineChart className="h-3.5 w-3.5 text-sky-400" />;
    if (f.includes("rsi")) return <Activity className="h-3.5 w-3.5 text-sky-400" />;
    return <LineChart className="h-3.5 w-3.5 text-sky-400" />;
  }
  if (f.startsWith("patterns.")) {
    if (entry.severity === "major") return <ArrowUp className="h-3.5 w-3.5 text-red-400" />;
    return <Minus className="h-3.5 w-3.5 text-slate-500" />;
  }
  return <Minus className="h-3.5 w-3.5 text-slate-500" />;
}

/** Format an ISO-8601 timestamp as a relative "time ago" string. */
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Extract a short label from the change text for display purposes.
 * For changes like "GREEN → RED" we show just the transition part.
 */
function shortChangeLabel(change: string): string {
  // Limit to a reasonable width
  if (change.length > 60) return change.slice(0, 57) + "...";
  return change;
}

export function SignalChangesPanel({
  symbol,
  token,
  limit = 5,
  variant = "compact",
}: SignalChangesPanelProps) {
  const { data, error, isLoading } = useSWR<ScanDiffResponse>(
    token ? [`/api/v1/scan/${encodeURIComponent(symbol)}/diff`, token] : null,
    ([url, tok]: [string, string | null]) => fetcher<ScanDiffResponse>(url, tok),
  );

  // ── Loading state ─────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  // ── Error state (404 = not enough scans yet, not a true error) ────────
  if (error) {
    const status = (error as Error & { status?: number }).status;
    if (status === 404) {
      return (
        <p className="text-xs text-slate-500">
          Not enough scans yet — run at least two scans for {symbol} to see
          signal changes.
        </p>
      );
    }
    return (
      <p className="text-xs text-slate-500">
        Could not load signal changes for {symbol}.
      </p>
    );
  }

  if (!data) return null;

  // Group changes by category
  const grouped = useMemo(() => {
    const groups: Record<string, ScanDiffEntry[]> = {};
    const categoryOrderMap: Record<string, number> = {};

    for (const ch of data.changes) {
      const cat = categoryLabel(ch.field);
      if (!groups[cat]) {
        groups[cat] = [];
        categoryOrderMap[cat] = categoryOrder(ch.field);
      }
      groups[cat].push(ch);
    }

    // Sort categories by order, then changes by severity within each group
    const sorted = Object.entries(groups).sort(
      ([a], [b]) => (categoryOrderMap[a] ?? 99) - (categoryOrderMap[b] ?? 99)
    );

    // Sort changes within each category by severity: major first, then minor, info
    for (const [, changes] of sorted) {
      changes.sort((a, b) => {
        const sevOrder = { major: 0, minor: 1, info: 2 };
        return (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3);
      });
    }

    return sorted;
  }, [data.changes]);

  const totalChanges = data.changes.length;
  const scoreDelta =
    data.previous_score != null && data.latest_score != null
      ? data.latest_score - data.previous_score
      : null;

  // ── Empty state ───────────────────────────────────────────────────────
  if (totalChanges === 0) {
    return (
      <p className="text-xs text-slate-500">
        No signal changes detected between the last two scans.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header strip: score delta + summary counts */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-400">
          {formatRelative(data.previous_scan_at)} → {formatRelative(data.latest_scan_at)}
        </span>
        {scoreDelta != null && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold",
              scoreDelta > 0
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : scoreDelta < 0
                ? "border-red-500/30 bg-red-500/10 text-red-400"
                : "border-slate-600 bg-slate-700/20 text-slate-300",
            )}
          >
            {scoreDelta > 0 ? (
              <ArrowUp className="h-3 w-3" />
            ) : scoreDelta < 0 ? (
              <ArrowDown className="h-3 w-3" />
            ) : null}
            {data.previous_score ?? "—"} → {data.latest_score ?? "—"}
            {scoreDelta !== 0 &&
              ` (${scoreDelta > 0 ? "+" : ""}${scoreDelta.toFixed(1)})`}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {data.summary.major > 0 && (
            <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-red-400">
              {data.summary.major} major
            </span>
          )}
          {data.summary.minor > 0 && (
            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-400">
              {data.summary.minor} minor
            </span>
          )}
          {data.summary.info > 0 && (
            <span className="rounded-full bg-blue-500/10 px-2 py-0.5 text-blue-400">
              {data.summary.info} info
            </span>
          )}
        </div>
      </div>

      {/* Category-grouped change list */}
      <div className="space-y-3">
        {grouped.slice(0, variant === "compact" ? undefined : undefined).map(([category, changes]) => {
          const visible = variant === "compact" ? changes.slice(0, limit) : changes;
          const totalInCat = changes.length;
          return (
            <div key={category}>
              {/* Category header */}
              <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                {category}
                <span className="ml-1.5 text-slate-600">
                  ({totalInCat})
                </span>
              </h4>

              {/* Changes for this category */}
              <ul className="space-y-1">
                {visible.map((entry, i) => {
                  const styles = SEVERITY_STYLES[entry.severity] ?? SEVERITY_STYLES.info;
                  return (
                    <li
                      key={`${entry.field}-${i}`}
                      className={cn(
                        "flex items-start gap-2.5 rounded-lg border px-3 py-2",
                        styles.row,
                      )}
                    >
                      {/* severity dot */}
                      <span
                        className={cn(
                          "mt-1 h-2 w-2 shrink-0 rounded-full",
                          styles.dot,
                        )}
                      />
                      {/* icon */}
                      <span className="mt-0.5 shrink-0">{changeIcon(entry)}</span>
                      {/* field + change */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <code className="truncate text-xs font-medium text-slate-200">
                            {entry.field}
                          </code>
                          <span
                            className={cn(
                              "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                              styles.badge,
                            )}
                          >
                            {entry.severity}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-slate-400">
                          {shortChangeLabel(entry.change)}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>

              {/* "...and N more" if truncated per category */}
              {variant === "compact" && totalInCat > limit && (
                <p className="pt-0.5 text-[11px] text-slate-500">
                  … and {totalInCat - limit} more in {category.toLowerCase()}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* "showing N of M" footer for compact */}
      {variant === "compact" && totalChanges > limit && (
        <p className="pt-1 text-xs text-slate-500">
          Showing {limit} of {totalChanges} changes from the last diff.
        </p>
      )}
    </div>
  );
}

export default SignalChangesPanel;
