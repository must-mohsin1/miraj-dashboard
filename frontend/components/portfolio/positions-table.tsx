"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PositionItem } from "@/lib/types";

/**
 * PositionsTable — Client Component.
 *
 * Renders the user's open futures positions. The Side column shows a coloured
 * badge (green for long, red for short). PnL and PnL% are coloured green for
 * profit, red for loss.
 */

interface PositionsTableProps {
  positions: PositionItem[];
}

function sideMeta(side: string) {
  const s = (side ?? "").toUpperCase();
  if (s === "LONG" || s === "BUY") {
    return {
      label: "LONG",
      className:
        "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
      arrow: "▲" as const,
    };
  }
  if (s === "SHORT" || s === "SELL") {
    return {
      label: "SHORT",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
      arrow: "▼" as const,
    };
  }
  return {
    label: side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
    arrow: "■" as const,
  };
}

export function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No open positions.
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
            <TableHead className="text-right text-slate-500">Mark Price</TableHead>
            <TableHead className="text-right text-slate-500">PnL (USD)</TableHead>
            <TableHead className="text-right text-slate-500">PnL %</TableHead>
            <TableHead className="text-right text-slate-500">Leverage</TableHead>
            <TableHead className="text-right text-slate-500">Liq Price</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p, i) => {
            const meta = sideMeta(p.side);
            const pnlPositive = p.pnl >= 0;
            return (
              <TableRow
                key={`${p.symbol}-${i}`}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="font-medium text-slate-100">
                  {p.symbol}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className={meta.className}>
                    {meta.arrow} {meta.label}
                  </Badge>
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.size)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.entry_price)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(p.mark_price)}
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
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {p.leverage}x
                </TableCell>
                <TableCell className="text-right text-slate-400 tabular-nums">
                  {p.liquidation_price != null
                    ? fmt(p.liquidation_price)
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

/** Format a number with up to 8 decimal places, trimming trailing zeros. */
function fmt(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  return parseFloat(n.toFixed(8)).toString();
}

export default PositionsTable;
