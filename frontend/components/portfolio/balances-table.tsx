"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BalanceItem } from "@/lib/types";
import type { PriceMap } from "@/hooks/use-price-stream";

/**
 * BalancesTable — Client Component.
 *
 * Renders the user's spot wallet balances in a sortable table with columns:
 * Asset · Free · Locked · Total · USD Value · % of Portfolio.
 *
 * When a `livePrices` map is supplied (keyed in SSE format, e.g. "BTC-USD"),
 * the USD value column is recalculated in real-time:
 *  - Stablecoins (USDT, USDC, DAI, …) use a fixed $1 peg.
 *  - All other assets use `total * livePrice`.
 * The total portfolio value and per-asset % are recomputed live as prices
 * tick. The USD value cell flashes green/red on each price update.
 */

const STABLECOINS = new Set([
  "USDT",
  "USDC",
  "BUSD",
  "DAI",
  "TUSD",
  "FDUSD",
  "USDP",
  "PAX",
  "GUSD",
  "UST",
  "SUSD",
]);

/** Convert a balance asset ("BTC") to its SSE price map key ("BTC-USD"). */
function assetPriceKey(asset: string): string {
  return `${asset.toUpperCase()}-USD`;
}

/** Live USD value for a single balance row. */
function computeUsdValue(
  asset: string,
  total: number,
  livePrices: PriceMap | null,
): { value: number | null; price: number | null } {
  const upper = asset.toUpperCase();
  if (STABLECOINS.has(upper)) {
    return { value: total, price: 1 };
  }
  const key = assetPriceKey(asset);
  const tick = livePrices?.[key];
  if (tick) {
    return { value: total * tick.price, price: tick.price };
  }
  return { value: null, price: null };
}

interface BalancesTableProps {
  balances: BalanceItem[];
  /** Live prices keyed in SSE format (e.g. "BTC-USD"). null when not streaming. */
  livePrices?: PriceMap | null;
}

export function BalancesTable({ balances, livePrices = null }: BalancesTableProps) {
  // Sort by live-or-static USD value descending (largest holding first).
  const sorted = useMemo(() => {
    return [...balances]
      .filter((b) => b.total > 0 || b.free > 0 || b.locked > 0)
      .sort((a, b) => {
        const aVal = computeUsdValue(a.asset, a.total, livePrices).value ?? a.usd_value ?? 0;
        const bVal = computeUsdValue(b.asset, b.total, livePrices).value ?? b.usd_value ?? 0;
        return bVal - aVal || b.total - a.total;
      });
  }, [balances, livePrices]);

  // Total USD value across all balances (live when available).
  const totalUsd = useMemo(
    () =>
      sorted.reduce((sum, b) => {
        const { value } = computeUsdValue(b.asset, b.total, livePrices);
        return sum + (value ?? b.usd_value ?? 0);
      }, 0),
    [sorted, livePrices],
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
            const { value, price } = computeUsdValue(b.asset, b.total, livePrices);
            const usdValue = value ?? b.usd_value ?? null;
            const pct = totalUsd > 0 && usdValue != null ? (usdValue / totalUsd) * 100 : 0;
            const usdPositive = (usdValue ?? 0) > 0;
            const hasLivePrice = price != null && !STABLECOINS.has(b.asset.toUpperCase());
            return (
              <BalanceRow
                key={b.asset}
                balance={b}
                usdValue={usdValue}
                pct={pct}
                usdPositive={usdPositive}
                livePrice={hasLivePrice ? price : null}
              />
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Single balance row. Decoupled so per-row price-flash state (green/red)
 * is isolated to the asset whose price just ticked.
 */
interface BalanceRowProps {
  balance: BalanceItem;
  usdValue: number | null;
  pct: number;
  usdPositive: boolean;
  livePrice: number | null;
}

function BalanceRow({ balance, usdValue, pct, usdPositive, livePrice }: BalanceRowProps) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevPriceRef = useRef<number | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (livePrice == null) return;
    const prev = prevPriceRef.current;
    if (prev != null && livePrice > prev) {
      setFlash("up");
    } else if (prev != null && livePrice < prev) {
      setFlash("down");
    }
    prevPriceRef.current = livePrice;

    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlash(null), 600);

    return () => {
      if (flashTimerRef.current) {
        clearTimeout(flashTimerRef.current);
        flashTimerRef.current = null;
      }
    };
  }, [livePrice]);

  const valueColor =
    flash === "up"
      ? "text-emerald-400"
      : flash === "down"
        ? "text-red-400"
        : usdPositive
          ? "text-emerald-400"
          : "text-slate-500";

  return (
    <TableRow
      className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
    >
      <TableCell className="font-medium text-slate-100">
        <span className="inline-flex items-center gap-2">
          {balance.asset}
          {livePrice != null && (
            <span className="relative flex h-1.5 w-1.5" aria-hidden title="Live price">
              <span
                className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                style={{ animationDuration: "1.5s" }}
              />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
          )}
        </span>
      </TableCell>
      <TableCell className="text-right text-slate-300 tabular-nums">
        {fmt(balance.free)}
      </TableCell>
      <TableCell className="text-right text-slate-300 tabular-nums">
        {fmt(balance.locked)}
      </TableCell>
      <TableCell className="text-right font-medium text-slate-100 tabular-nums">
        {fmt(balance.total)}
      </TableCell>
      <TableCell
        className={`text-right font-semibold tabular-nums transition-colors duration-300 ${valueColor}`}
      >
        {usdValue != null ? `$${fmt(usdValue)}` : "—"}
      </TableCell>
      <TableCell className="text-right text-slate-400 tabular-nums">
        {pct.toFixed(2)}%
      </TableCell>
    </TableRow>
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
