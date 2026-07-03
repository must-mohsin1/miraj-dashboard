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
 * Renders historical (closed/cancelled) orders, sorted by timestamp
 * descending (most recent first). The Side column is colour-coded
 * (green = buy, red = sell). The Type column shows a limit/market badge.
 * The Status column shows filled (green) / cancelled (red).
 */

interface OrderHistoryTableProps {
  orders: OrderHistoryItem[];
}

function sideMeta(side: string) {
  const s = (side ?? "").toUpperCase();
  if (s === "BUY" || s === "LONG") {
    return {
      label: "BUY",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (s === "SELL" || s === "SHORT") {
    return {
      label: "SELL",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  return {
    label: side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

function typeMeta(type: string) {
  const t = (type ?? "").toLowerCase();
  if (t === "market") {
    return {
      label: "Market",
      className: "bg-violet-500/10 text-violet-400 border-violet-700/50",
    };
  }
  if (t === "limit") {
    return {
      label: "Limit",
      className: "bg-amber-500/10 text-amber-400 border-amber-700/50",
    };
  }
  return {
    label: type || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
}

function statusMeta(status: string) {
  const s = (status ?? "").toLowerCase();
  if (s === "filled") {
    return {
      label: "Filled",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    };
  }
  if (s === "cancelled" || s === "canceled") {
    return {
      label: "Cancelled",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
    };
  }
  if (s === "open" || s === "new") {
    return {
      label: "Open",
      className: "bg-sky-500/10 text-sky-400 border-sky-700/50",
    };
  }
  return {
    label: status || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
  };
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
    [orders],
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No order history.
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
            <TableHead className="text-slate-500">Type</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-right text-slate-500">Price</TableHead>
            <TableHead className="text-right text-slate-500">Amount</TableHead>
            <TableHead className="text-right text-slate-500">Filled</TableHead>
            <TableHead className="text-right text-slate-500">Cost</TableHead>
            <TableHead className="text-slate-500">Status</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Reduce Only</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((o, i) => {
            const meta = sideMeta(o.side);
            const tMeta = typeMeta(o.type);
            const sMeta = statusMeta(o.status);
            return (
              <TableRow
                key={`${o.symbol}-${o.timestamp}-${i}`}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="text-slate-400 tabular-nums">
                  {formatTime(o.timestamp)}
                </TableCell>
                <TableCell className="font-medium text-slate-100">
                  {o.symbol}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={tMeta.className}>
                    {tMeta.label}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={meta.className}>
                    {meta.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.amount)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.filled)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(o.cost)}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={sMeta.className}>
                    {sMeta.label}
                  </Badge>
                </TableCell>
                <TableCell className="hidden text-right text-slate-400 tabular-nums md:table-cell">
                  {o.reduce_only ? "Yes" : "No"}
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
