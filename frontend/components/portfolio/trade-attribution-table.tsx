"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { TradeAttributionResponse } from "@/lib/types";

/**
 * TradeAttributionTable — Client Component.
 *
 * Fetches `GET /api/v1/portfolio/{exchange}/trade-attribution` and renders a
 * table linking each closed position to the Miraj scan that preceded its
 * entry — showing the confluence score, scan direction, and per-TF QQE
 * signals at entry for every trade.
 *
 * Rows are colour-coded to surface signal quality at a glance:
 *  - Green row  → scan score >= 20 AND the trade was profitable (good signal)
 *  - Red row    → scan score >= 20 AND the trade was losing (false signal)
 *  - Default   → score < 20 or no scan linked (neutral)
 *
 * Below the table, a score-band win-rate breakdown summarises how each
 * confluence-score band actually performed, plus a footer summary of how
 * many trades were taken on high-confidence (>= 20) signals.
 */

interface TradeAttributionTableProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

/** Score bands (5-point-wide, mirroring the backend SCAN_BANDS). */
const SCORE_BANDS = [
  [0, 5],
  [5, 10],
  [10, 15],
  [15, 20],
  [20, 25],
  [25, 30],
] as const;

const HIGH_CONFIDENCE_THRESHOLD = 20;

export function TradeAttributionTable({
  token,
  exchange,
}: TradeAttributionTableProps) {
  const [data, setData] = useState<TradeAttributionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchData() {
    setRefreshing(true);
    try {
      const res = await fetch(
        `/api/v1/portfolio/${exchange}/trade-attribution`,
        { headers },
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: TradeAttributionResponse = await res.json();
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
        Linking trades to scans…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 p-4 text-sm text-red-400">
        Failed to load trade attribution: {error}
      </div>
    );
  }

  const items = data?.items ?? [];
  const totalTrades = data?.total_trades ?? items.length;
  const highConfidence = data?.high_confidence_trades ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          Each closed position linked to the nearest scan that ran before
          entry — shows which confluence score led to each trade.
        </p>
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

      {items.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
          No closed positions yet. Trade attribution will appear once you have
          closed trades linked to Miraj scans.
        </div>
      ) : (
        <>
          <AttributionTable items={items} />
          <ScoreBandSummary items={items} />
          <FooterSummary
            totalTrades={totalTrades}
            highConfidence={highConfidence}
          />
        </>
      )}

      {error && (
        <p className="text-xs text-amber-500">
          (refresh failed: {error})
        </p>
      )}
    </div>
  );
}

// ── Main attribution table ─────────────────────────────────────────────────

function AttributionTable({
  items,
}: {
  items: NonNullable<TradeAttributionResponse>["items"];
}) {
  // Sort by close time descending (most recent first).
  const sorted = useMemo(
    () =>
      [...items].sort((a, b) => {
        const ta = a.close_time ? new Date(a.close_time).getTime() : 0;
        const tb = b.close_time ? new Date(b.close_time).getTime() : 0;
        return tb - ta;
      }),
    [items],
  );

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Symbol</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-right text-slate-500">Entry</TableHead>
            <TableHead className="text-right text-slate-500">Exit</TableHead>
            <TableHead className="text-right text-slate-500">PnL</TableHead>
            <TableHead className="text-right text-slate-500">Scan Score</TableHead>
            <TableHead className="text-slate-500">Scan Direction</TableHead>
            <TableHead className="hidden text-slate-500 md:table-cell">
              QQE at Entry
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((it, i) => {
            const profitable = it.pnl >= 0;
            const isHighConf = it.scan_score !== null && it.scan_score >= 20;
            // Green if high-confidence + profitable; red if high-confidence + losing (false signal).
            const rowTint = !isHighConf
              ? ""
              : profitable
                ? "bg-emerald-500/5 hover:bg-emerald-500/10"
                : "bg-red-500/5 hover:bg-red-500/10";
            return (
              <TableRow
                key={`${it.position_symbol}-${it.close_time ?? it.open_time ?? i}`}
                className={`border-slate-800/60 transition-colors last:border-0 ${rowTint}`}
              >
                <TableCell className="font-medium text-slate-100">
                  {it.position_symbol}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={
                      it.position_side === "LONG"
                        ? "border-emerald-700 bg-emerald-500/10 text-emerald-400"
                        : "border-red-700 bg-red-500/10 text-red-400"
                    }
                  >
                    {it.position_side === "LONG" ? "▲" : "▼"} {it.position_side}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(it.entry_price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(it.exit_price)}
                </TableCell>
                <TableCell
                  className={`text-right font-semibold tabular-nums ${
                    profitable ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {profitable ? "+" : ""}
                  {fmt(it.pnl)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {it.scan_score !== null ? (
                    <span
                      className={
                        isHighConf ? "font-bold text-emerald-400" : "text-slate-300"
                      }
                    >
                      {it.scan_score.toFixed(1)}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </TableCell>
                <TableCell>
                  {it.scan_direction ? (
                    <Badge
                      variant="outline"
                      className={
                        it.scan_direction === "LONG"
                          ? "border-emerald-700/50 bg-emerald-500/5 text-emerald-400"
                          : "border-red-700/50 bg-red-500/5 text-red-400"
                      }
                    >
                      {it.scan_direction}
                    </Badge>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  <QqeBadges signals={it.scan_qqe_signals} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// ── Per-TF QQE badges ───────────────────────────────────────────────────────

function QqeBadges({
  signals,
}: {
  signals: TradeAttributionResponse["items"][number]["scan_qqe_signals"];
}) {
  if (!signals || Object.keys(signals).length === 0) {
    return <span className="text-slate-600">—</span>;
  }
  const tfs: Array<[string, keyof typeof signals]> = [
    ["1H", "1h"],
    ["4H", "4h"],
    ["1D", "daily"],
  ];
  return (
    <div className="flex flex-wrap gap-1">
      {tfs.map(([label, key]) => {
        const sig = signals[key];
        if (!sig) return null;
        const trend = (sig.trend || "NEUTRAL").toUpperCase();
        const strong = (sig.strength || "NONE").toUpperCase() === "STRONG";
        const cls =
          trend === "GREEN"
            ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
            : trend === "RED"
              ? "border-red-700/50 bg-red-500/10 text-red-400"
              : "border-slate-700 bg-slate-500/10 text-slate-400";
        return (
          <Badge
            key={key}
            variant="outline"
            className={`px-1 text-[9px] font-bold ${cls}`}
            title={`${label} QQE: ${trend}${strong ? " (strong)" : ""}`}
          >
            {label} {trend === "GREEN" ? "▲" : trend === "RED" ? "▼" : "■"}
            {strong && "*"}
          </Badge>
        );
      })}
    </div>
  );
}

// ── Score-band win-rate breakdown ──────────────────────────────────────────

function ScoreBandSummary({
  items,
}: {
  items: NonNullable<TradeAttributionResponse>["items"];
}) {
  // Bucket trades into score bands and compute win rate per band.
  const bands = useMemo(() => {
    const buckets = SCORE_BANDS.map(([lo, hi]) => ({
      label: `${lo}-${hi}`,
      lo,
      hi,
      total: 0,
      wins: 0,
    }));
    for (const it of items) {
      if (it.scan_score === null) continue;
      const score = it.scan_score;
      for (const b of buckets) {
        if (score >= b.lo && score < b.hi) {
          b.total += 1;
          if (it.pnl > 0) b.wins += 1;
          break;
        }
      }
    }
    return buckets.map((b) => ({
      ...b,
      winRate: b.total > 0 ? Math.round((b.wins / b.total) * 100) : 0,
    }));
  }, [items]);

  // Only render bands that actually have trades.
  const activeBands = bands.filter((b) => b.total > 0);
  if (activeBands.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-medium text-slate-300">
        Win Rate by Confluence Score Band
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {bands.map((b) => {
          const isHigh = b.lo >= HIGH_CONFIDENCE_THRESHOLD;
          const dimmed = b.total === 0;
          return (
            <div
              key={b.label}
              className={`rounded-lg border p-2 text-center ${
                dimmed
                  ? "border-slate-800 bg-slate-900/40"
                  : isHigh
                    ? "border-emerald-700/50 bg-emerald-500/5"
                    : "border-slate-700 bg-slate-800/40"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wide text-slate-500">
                Score {b.label}
              </div>
              <div
                className={`mt-1 text-lg font-bold tabular-nums ${
                  dimmed
                    ? "text-slate-600"
                    : isHigh
                      ? "text-emerald-400"
                      : "text-slate-200"
                }`}
              >
                {b.total > 0 ? `${b.winRate}%` : "—"}
              </div>
              <div className="text-[10px] text-slate-500">
                {b.total > 0 ? `${b.wins}/${b.total} wins` : "no trades"}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Trades entered with confluence score 20-25 and 25-30 are highlighted
        as high-confidence signals.
      </p>
    </div>
  );
}

// ── Footer summary ─────────────────────────────────────────────────────────

function FooterSummary({
  totalTrades,
  highConfidence,
}: {
  totalTrades: number;
  highConfidence: number;
}) {
  const pct =
    totalTrades > 0 ? Math.round((highConfidence / totalTrades) * 100) : 0;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-sm text-slate-300">
        <span className="font-bold text-emerald-400">{highConfidence}</span>
        <span className="text-slate-400"> of </span>
        <span className="font-bold text-slate-100">{totalTrades}</span>
        <span className="text-slate-400">
          {" "}
          trades were taken on high-confidence signals (score ≥ 20)
        </span>
        {totalTrades > 0 && (
          <span className="ml-2 text-xs text-slate-500">({pct}%)</span>
        )}
      </p>
    </div>
  );
}

// ── Number formatting helpers ───────────────────────────────────────────────

/** Format a number with up to 8 decimal places, trimming trailing zeros. */
function fmt(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  return parseFloat(n.toFixed(8)).toString();
}

export default TradeAttributionTable;
