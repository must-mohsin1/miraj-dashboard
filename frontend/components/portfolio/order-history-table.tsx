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
import type { OrderHistoryItem } from "@/lib/types";

/**
 * OrderHistoryTable — Client Component.
 *
 * Renders historical (closed/cancelled) orders sorted by timestamp descending.
 * Side is colour-coded (green = buy, red = sell). Status badges give a quick
 * visual indicator of order outcome.
 */

interface OrderHistoryTableProps {
  orders: OrderHistoryItem[];
}

function sideMeta(side: string, sideAction?: string | null) {
  // Prefer the full MEXC action name (e.g. "Open Long", "Close Short")
  // which carries the direction; fall back to the buy/sell side.
  const action = (sideAction ?? "").toLowerCase();
  const s = (side ?? "").toLowerCase();

  // Open Long / Close Short → buy (green)；Close Long / Open Short → sell (red)
  // But "Close Long" closes a long (sell) — colour by the action direction.
  if (action === "open long") {
    return {
      label: "Open Long",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (action === "close long") {
    return {
      label: "Close Long",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  if (action === "open short") {
    return {
      label: "Open Short",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  if (action === "close short") {
    return {
      label: "Close Short",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }

  // Fall back to buy/sell.
  if (s === "buy" || s === "long") {
    return {
      label: side?.toUpperCase() || "BUY",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (s === "sell" || s === "short") {
    return {
      label: side?.toUpperCase() || "SELL",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  return {
    label: sideAction || side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

function statusBadge(status: string) {
  const st = (status ?? "").toLowerCase();
  if (st === "filled" || st === "closed") {
    return { label: "Filled", className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50" };
  }
  if (st === "partially_filled" || st === "partially filled") {
    return { label: "Partial", className: "bg-amber-500/10 text-amber-400 border-amber-700/50" };
  }
  if (st === "cancelled" || st === "canceled") {
    return { label: "Cancelled", className: "bg-slate-500/10 text-slate-400 border-slate-700/50" };
  }
  if (st === "open") {
    return { label: "Open", className: "bg-amber-500/10 text-amber-400 border-amber-700/50" };
  }
  return { label: status || "—", className: "bg-slate-500/10 text-slate-400 border-slate-700/50" };
}

export function OrderHistoryTable({ orders }: OrderHistoryTableProps) {
  // Sort by timestamp descending (most recent first).
  const sorted = useMemo(
    () =>
      [...orders].sort((a, b) => {
        const ta = new Date(a.timestamp).getTime();
        const tb = new Date(b.timestamp).getTime();
        return tb - ta;
      }),
    [orders]
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No order history.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Time</TableHead>
            <TableHead className="text-slate-500">Symbol</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-slate-500">Type</TableHead>
            <TableHead className="text-slate-500">Status</TableHead>
            <TableHead className="text-right text-slate-500">Price</TableHead>
            <TableHead className="text-right text-slate-500">Fill Price</TableHead>
            <TableHead className="text-right text-slate-500">Amount</TableHead>
            <TableHead className="text-right text-slate-500">Filled</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Cost</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Fee</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Lvg</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((o, i) => {
            const side = sideMeta(o.side, o.side_action);
            const status = statusBadge(o.status);
            return (
              <TableRow
                key={`${o.symbol}-${o.timestamp}-${o.side}-${o.price}-${i}`}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="whitespace-nowrap text-slate-400 tabular-nums">
                  {formatTime(o.timestamp)}
                </TableCell>
                <TableCell className="font-medium text-slate-100">
                  {o.symbol}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={side.className}>
                    {side.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-slate-300">{o.type}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={status.className}>
                    {status.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {o.filled_price ? fmt(o.filled_price) : "—"}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.amount)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.filled)}
                </TableCell>
                <TableCell className="hidden text-right text-slate-300 tabular-nums md:table-cell">
                  {fmt(o.cost)}
                </TableCell>
                <TableCell className="hidden text-right text-slate-300 tabular-nums md:table-cell">
                  {o.fee != null && o.fee !== 0 ? (
                    <span>
                      {fmt(o.fee)}
                      {o.fee_currency ? ` ${o.fee_currency}` : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="hidden text-right text-slate-300 tabular-nums md:table-cell">
                  {o.leverage ? `${o.leverage}x` : "—"}
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

export default OrderHistoryTable;