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
import type { TradeItem } from "@/lib/types";

/**
 * TradesTable — Client Component.
 *
 * Renders recent trades (spot + futures) sorted by timestamp descending. The
 * Side column is colour-coded (green = buy/long, red = sell/short).
 */

interface TradesTableProps {
  trades: TradeItem[];
}

function sideMeta(side: string) {
  const s = (side ?? "").toUpperCase();
  if (s === "BUY" || s === "LONG") {
    return {
      label: s,
      className:
        "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (s === "SELL" || s === "SHORT") {
    return {
      label: s,
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  return {
    label: side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

export function TradesTable({ trades }: TradesTableProps) {
  // Sort by timestamp descending (most recent first).
  const sorted = useMemo(
    () =>
      [...trades].sort((a, b) => {
        const ta = new Date(a.timestamp).getTime();
        const tb = new Date(b.timestamp).getTime();
        return tb - ta;
      }),
    [trades]
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No recent trades.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Time</TableHead>
            <TableHead className="text-slate-500">Symbol</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-slate-500">Type</TableHead>
            <TableHead className="text-right text-slate-500">Price</TableHead>
            <TableHead className="text-right text-slate-500">Amount</TableHead>
            <TableHead className="text-right text-slate-500">Cost</TableHead>
            <TableHead className="text-right text-slate-500">Fee</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((t, i) => {
            const meta = sideMeta(t.side);
            return (
              <TableRow
                key={`${t.exchange_trade_id}-${i}`}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="text-slate-400 tabular-nums">
                  {formatTime(t.timestamp)}
                </TableCell>
                <TableCell className="font-medium text-slate-100">
                  {t.symbol}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={meta.className}>
                    {meta.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-slate-300">{t.type}</TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(t.price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(t.amount)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(t.cost)}
                </TableCell>
                <TableCell className="text-right text-slate-400 tabular-nums">
                  {t.fee != null
                    ? `${fmt(t.fee)}${t.fee_currency ? ` ${t.fee_currency}` : ""}`
                    : "—"}
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

export default TradesTable;
