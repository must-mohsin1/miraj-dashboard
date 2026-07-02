"use client";

import { useMemo } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BalanceItem } from "@/lib/types";

/**
 * BalancesTable — Client Component.
 *
 * Renders the user's spot wallet balances in a sortable table with columns:
 * Asset · Free · Locked · Total · USD Value · % of Portfolio.
 *
 * USD-valued balances are colored green/red relative to the total portfolio
 * value. Rows with zero total balance are filtered out.
 */

interface BalancesTableProps {
  balances: BalanceItem[];
}

export function BalancesTable({ balances }: BalancesTableProps) {
  // Sort by USD value descending (largest holding first) for quick scanning.
  const sorted = useMemo(
    () =>
      [...balances]
        .filter((b) => b.total > 0 || b.free > 0 || b.locked > 0)
        .sort(
          (a, b) =>
            (b.usd_value ?? 0) - (a.usd_value ?? 0) ||
            b.total - a.total
        ),
    [balances]
  );

  const totalUsd = useMemo(
    () => sorted.reduce((sum, b) => sum + (b.usd_value ?? 0), 0),
    [sorted]
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No balances found. Click Refresh to fetch live data from MEXC.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Asset</TableHead>
            <TableHead className="text-right text-slate-500">Free</TableHead>
            <TableHead className="text-right text-slate-500">Locked</TableHead>
            <TableHead className="text-right text-slate-500">Total</TableHead>
            <TableHead className="text-right text-slate-500">USD Value</TableHead>
            <TableHead className="text-right text-slate-500">% Portfolio</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((b) => {
            const pct =
              totalUsd > 0 && b.usd_value != null
                ? (b.usd_value / totalUsd) * 100
                : 0;
            const usdPositive = (b.usd_value ?? 0) > 0;
            return (
              <TableRow
                key={b.asset}
                className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
              >
                <TableCell className="font-medium text-slate-100">
                  {b.asset}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(b.free)}
                </TableCell>
                <TableCell className="text-right text-slate-300 tabular-nums">
                  {fmt(b.locked)}
                </TableCell>
                <TableCell className="text-right font-medium text-slate-100 tabular-nums">
                  {fmt(b.total)}
                </TableCell>
                <TableCell
                  className={`text-right font-semibold tabular-nums ${
                    usdPositive ? "text-emerald-400" : "text-slate-500"
                  }`}
                >
                  {b.usd_value != null
                    ? `$${fmt(b.usd_value)}`
                    : "—"}
                </TableCell>
                <TableCell className="text-right text-slate-400 tabular-nums">
                  {pct.toFixed(2)}%
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
  // Up to 8 decimal places, strip trailing zeros.
  return parseFloat(n.toFixed(8)).toString();
}

export default BalancesTable;
