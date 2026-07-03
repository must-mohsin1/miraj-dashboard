"use client";

import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PositionHistoryItem } from "@/lib/types";

/**
 * PositionHistoryTable — Client Component.
 *
 * Renders closed/historical futures positions, sorted by close_time
 * descending (most recent first). The Side column shows a coloured badge
 * (green for long, red for short). PnL and PnL% are coloured green for
 * profit, red for loss. The Close Reason column shows a badge:
 *  - liquidated → red
 *  - closed     → gray
 *  - manual     → blue
 */

interface PositionHistoryTableProps {
  positions: PositionHistoryItem[];
}

function sideMeta(side: string) {
  const s = (side ?? "").toUpperCase();
  if (s === "LONG" || s === "BUY") {
    return {
      label: "LONG",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (s === "SHORT" || s === "SELL") {
    return {
      label: "SHORT",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  return {
    label: side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

function closeReasonMeta(reason: string | null) {
  const r = (reason ?? "").toLowerCase();
  if (r === "liquidated") {
    return {
      label: "Liquidated",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  if (r === "manual") {
    return {
      label: "Manual",
      className: "bg-sky-500/10 text-sky-400 border-sky-700/50",
    };
  }
  if (r === "closed") {
    return {
      label: "Closed",
      className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
    };
  }
  return {
    label: reason || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

export function PositionHistoryTable({ positions }: PositionHistoryTableProps) {
  // Sort by close_time descending (most recent first), falling back to open_time.
  const sorted = useMemo(
    () =>
      [...positions].sort((a, b) => {
        const ta = new Date(a.close_time ?? a.open_time ?? 0).getTime();
        const tb = new Date(b.close_time ?? b.open_time ?? 0).getTime();
        return tb - ta;
      }),
    [positions],
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No closed positions.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Symbol</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-right text-slate-500">Size</TableHead>
            <TableHead className="text-right text-slate-500">Entry Price</TableHead>
            <TableHead className="text-right text-slate-500">Exit Price</TableHead>
            <TableHead className="text-right text-slate-500">PnL (USD)</TableHead>
            <TableHead className="text-right text-slate-500">PnL %</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Leverage</TableHead>
            <TableHead className="hidden text-slate-500 md:table-cell">Open Time</TableHead>
            <TableHead className="hidden text-slate-500 md:table-cell">Close Time</TableHead>
            <TableHead className="text-slate-500">Close Reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((p, i) => {
            const meta = sideMeta(p.side);
            const reasonMeta = closeReasonMeta(p.close_reason);
            const pnlPositive = p.pnl >= 0;
            return (
              <TableRow
                key={`${p.symbol}-${p.close_time ?? i}-${i}`}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="font-medium text-slate-100">
                  {p.symbol}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={meta.className}>
                    {meta.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.size)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.entry_price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.exit_price)}
                </TableCell>
                <TableCell
                  className={`text-right font-semibold tabular-nums ${
                    pnlPositive ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {pnlPositive ? "+" : ""}
                  {fmt(p.pnl)}
                </TableCell>
                <TableCell
                  className={`text-right font-semibold tabular-nums ${
                    pnlPositive ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {pnlPositive ? "+" : ""}
                  {p.pnl_percent.toFixed(2)}%
                </TableCell>
                <TableCell className="hidden text-right text-slate-300 tabular-nums md:table-cell">
                  {p.leverage}x
                </TableCell>
                <TableCell className="hidden text-slate-400 tabular-nums md:table-cell">
                  {p.open_time ? formatTime(p.open_time) : "—"}
                </TableCell>
                <TableCell className="hidden text-slate-400 tabular-nums md:table-cell">
                  {p.close_time ? formatTime(p.close_time) : "—"}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={reasonMeta.className}>
                    {reasonMeta.label}
                  </Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** Format an ISO timestamp as a compact date+time string. */
function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** Format a number with up to 8 decimal places, trimming trailing zeros. */
function fmt(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  return parseFloat(n.toFixed(8)).toString();
}

export default PositionHistoryTable;
