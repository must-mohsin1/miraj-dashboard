"use client";

import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowRightLeft,
  BarChart4,
  Eye,
  FlipHorizontal,
  Info,
  Minus,
  TrendingUp,
  Zap,
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
 *   - info  → blue   (rationale text, volume changes)
 *
 * Each change shows a field-specific icon, an old → new transition, and a
 * severity badge.  QQE flips get a coloured directional badge
 * (GREEN→RED = red, RED→GREEN = green).  Changes are grouped by severity:
 * major first, then minor, then info.
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

/** Parse a QQE change string like "GREEN-STRONG → RED" into a direction. */
function parseQqeDirection(change: string): "bearish" | "bullish" | "neutral" {
  const upper = change.toUpperCase();
  const greenWords = ["GREEN", "GREEN-STRONG"];
  const redWords = ["RED", "RED-STRONG"];

  for (const gw of greenWords) {
    for (const rw of redWords) {
      if (upper.includes(`${gw} → ${rw}`)) return "bearish";
      if (upper.includes(`${rw} → ${gw}`)) return "bullish";
    }
  }
  return "neutral";
}

/** QQE flip badge styles: bearish (green→red) = red badge, bullish (red→green) = green */
function qqeFlipBadge(direction: "bearish" | "bullish" | "neutral") {
  if (direction === "bearish") {
    return {
      icon: <Zap className="h-3 w-3 text-red-400" />,
      label: "BEARISH FLIP",
      className: "border-red-500/40 bg-red-500/15 text-red-400",
    };
  }
  if (direction === "bullish") {
    return {
      icon: <Zap className="h-3 w-3 text-emerald-400" />,
      label: "BULLISH FLIP",
      className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
    };
  }
  return {
    icon: <Zap className="h-3 w-3 text-amber-400" />,
    label: "QQE CHANGE",
    className: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  };
}

/** Return an icon element appropriate for the change field type. */
function changeIcon(entry: ScanDiffEntry) {
  const f = entry.field;
  const c = entry.change;

  // Score changes: arrow up/down
  if (f.startsWith("score.total") || f.startsWith("score.")) {
    const isUp = c.includes("▲");
    const isDown = c.includes("▼");
    if (isUp) return <ArrowUp className="h-3.5 w-3.5 text-emerald-400" />;
    if (isDown) return <ArrowDown className="h-3.5 w-3.5 text-red-400" />;
  }

  // QQE signal changes: zap/flip icon
  if (f.startsWith("qqe_signals.")) {
    const dir = parseQqeDirection(c);
    if (dir === "bearish") return <Zap className="h-3.5 w-3.5 text-red-400" />;
    if (dir === "bullish") return <Zap className="h-3.5 w-3.5 text-emerald-400" />;
    return <Zap className="h-3.5 w-3.5 text-amber-400" />;
  }

  // Structure (HH/HL/LH/LL) changes: arrow right-left
  if (f.startsWith("structure.")) {
    return <ArrowRightLeft className="h-3.5 w-3.5 text-red-400" />;
  }

  // Indicator changes (BB squeeze, RSI, EMA cross): activity/info icon
  if (f.startsWith("indicators.")) {
    return <Activity className="h-3.5 w-3.5 text-amber-400" />;
  }

  // Pattern changes (new / invalidated / confirmed): eye icon
  if (f.startsWith("patterns.")) {
    return <Eye className="h-3.5 w-3.5 text-amber-400" />;
  }

  // Volume changes: bar-chart icon
  if (f.startsWith("volume.")) {
    return <BarChart4 className="h-3.5 w-3.5 text-blue-400" />;
  }

  // Trade plan direction/decision: flip icon
  if (f.startsWith("trade_plan.direction") || f.startsWith("trade_plan.trade_decision")) {
    return <FlipHorizontal className="h-3.5 w-3.5 text-amber-400" />;
  }

  // Trade plan price levels: trending up
  if (f.startsWith("trade_plan.")) {
    return <TrendingUp className="h-3.5 w-3.5 text-amber-400" />;
  }

  return <Info className="h-3.5 w-3.5 text-slate-500" />;
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

/** Sort changes by severity: major first, minor second, info last. */
function sortBySeverity(changes: ScanDiffEntry[]): ScanDiffEntry[] {
  const order: Record<Severity, number> = { major: 0, minor: 1, info: 2 };
  return [...changes].sort(
    (a, b) => (order[a.severity] ?? 2) - (order[b.severity] ?? 2),
  );
}

/**
 * Render a single change entry row.
 */
function ChangeRow({ entry }: { entry: ScanDiffEntry }) {
  const styles = SEVERITY_STYLES[entry.severity] ?? SEVERITY_STYLES.info;
  const isQqe = entry.field.startsWith("qqe_signals.");
  const qqeDir = isQqe ? parseQqeDirection(entry.change) : null;

  return (
    <li
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
      {/* field-specific icon */}
      <span className="mt-0.5 shrink-0">{changeIcon(entry)}</span>
      {/* field + change */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <code className="truncate text-xs font-medium text-slate-200">
            {entry.field}
          </code>
          <div className="flex shrink-0 items-center gap-1">
            {/* QQE flip-specific directional badge */}
            {isQqe && qqeDir && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  qqeFlipBadge(qqeDir).className,
                )}
              >
                {qqeFlipBadge(qqeDir).icon}
                {qqeFlipBadge(qqeDir).label}
              </span>
            )}
            {/* severity badge */}
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                styles.badge,
              )}
            >
              {entry.severity}
            </span>
          </div>
        </div>
        <p className="mt-0.5 text-xs text-slate-400">
          {entry.change}
        </p>
      </div>
    </li>
  );
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

  // Sort changes by severity: major → minor → info
  const sortedChanges = useMemo(() => sortBySeverity(data.changes), [data.changes]);
  const changes = variant === "compact" ? sortedChanges.slice(0, limit) : sortedChanges;
  const totalChanges = sortedChanges.length;
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
    <div className="space-y-2">
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
        <div className="flex items-center gap-1.5 ml-auto">
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

      {/* Change list — grouped by severity */}
      <ul className="space-y-1.5">
        {changes.map((entry, i) => (
          <ChangeRow key={`${entry.field}-${i}`} entry={entry} />
        ))}
      </ul>

      {/* "showing N of M" footer for compact */}
      {variant === "compact" && totalChanges > limit && (
        <p className="pt-1 text-xs text-slate-500">
          Showing {limit} of {totalChanges} changes from the last diff (sorted
          by severity: major → minor → info).
        </p>
      )}
    </div>
  );
}

export default SignalChangesPanel;
