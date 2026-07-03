"use client";

import { useMemo } from "react";
import type { BalanceItem, PositionItem } from "@/lib/types";
import type { PriceMap } from "@/hooks/use-price-stream";

/**
 * LivePortfolioHeader — Client Component.
 *
 * Recalculates total portfolio value and total PnL in real-time using
 * the live price map streamed from the SSE endpoint. Shows:
 *  - Total portfolio value (sum of live USD value of every balance +
 *    sum of position margins + sum of open PnLs)
 *  - Total PnL across all open positions (green/red)
 *  - "LIVE" indicator with pulsing dot and connection state
 *
 * The price key convention mirrors how symbols are converted in
 * `portfolio-dashboard.tsx`:
 *  - Balance asset "BTC"  → key "BTC-USD"
 *  - Position symbol "BTC/USDT:USDT" → key "BTC-USDT"
 *  - Position symbol "BTC-USDT"       → key "BTC-USDT"
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

function fmtUsd(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Compute the live USD value for a single balance.
 * Non-stablecoin assets use the live price; stablecoins are pegged to $1.
 * Returns `{ value: NaN, price: null }` when no live price is available so
 * the caller can fall back to the static `usd_value`.
 */
function balanceUsdValue(
  asset: string,
  total: number,
  livePrices: PriceMap | null,
): { value: number; price: number | null } {
  const upper = asset.toUpperCase();
  if (STABLECOINS.has(upper)) {
    return { value: total, price: 1 };
  }
  // Look up live price using the SSE-format key "BTC-USD".
  const key = `${upper}-USD`;
  const tick = livePrices?.[key];
  if (tick) {
    return { value: total * tick.price, price: tick.price };
  }
  // Signal "no live data" with NaN so the caller falls back to static value.
  return { value: NaN, price: null };
}

export interface LivePortfolioHeaderProps {
  /** Static balances from the server (usd_value used as fallback). */
  balances: BalanceItem[];
  /** Open positions keyed to live mark prices. */
  positions: PositionItem[];
  /** Live price map keyed in SSE format (e.g. "BTC-USD", "BTC-USDT"). */
  livePrices: PriceMap | null;
  /** When true, the SSE connection is open — shows the pulsing LIVE dot. */
  isConnected: boolean;
}

/**
 * Convert a position symbol (e.g. "BTC/USDT:USDT" or "BTC-USDT") to the SSE
 * price map key used for live lookups ("BTC-USDT").
 */
export function positionSymbolToPriceKey(symbol: string): string {
  const s = symbol.toUpperCase();
  // ccxt futures style "BTC/USDT:USDT" → base "BTC", quote "USDT"
  const base = s.split(":")[0].replace("/", "-");
  // "BTC-USDT" → convert to "BTC-USD" for SSE key matching
  if (base.endsWith("-USDT")) {
    return base.slice(0, -5) + "-USD";
  }
  return base;
}

/**
 * Convert a balance asset (e.g. "BTC") to the SSE price map key "BTC-USD".
 */
export function assetToPriceKey(asset: string): string {
  const upper = asset.toUpperCase();
  if (STABLECOINS.has(upper)) return `${upper}-USD`; // for completeness
  return `${upper}-USD`;
}

/**
 * Look up the live price for a position symbol in the price map.
 */
function livePositionPrice(
  symbol: string,
  livePrices: PriceMap | null,
): number | null {
  if (!livePrices) return null;
  const key = positionSymbolToPriceKey(symbol);
  return livePrices[key]?.price ?? null;
}

export function LivePortfolioHeader({
  balances,
  positions,
  livePrices,
  isConnected,
}: LivePortfolioHeaderProps) {
  // Compute live total portfolio value and total PnL.
  const { totalValue, totalPnl } = useMemo(() => {
    // 1. Sum balance USD values (live price when available, else static fallback).
    let valueFromBalances = 0;
    for (const b of balances) {
      if (b.total <= 0 && b.free <= 0 && b.locked <= 0) continue;
      const { value } = balanceUsdValue(b.asset, b.total, livePrices);
      if (Number.isNaN(value)) {
        valueFromBalances += b.usd_value ?? 0;
      } else {
        valueFromBalances += value;
      }
    }

    // 2. Sum live PnL across all open positions.
    let pnl = 0;
    let hasLivePnl = false;
    for (const p of positions) {
      const livePrice = livePositionPrice(p.symbol, livePrices);
      let positionPnl: number;
      if (livePrice != null) {
        const dir =
          p.side?.toUpperCase() === "LONG" ||
          p.side?.toUpperCase() === "BUY"
            ? 1
            : -1;
        positionPnl = (livePrice - p.entry_price) * p.size * dir;
        hasLivePnl = true;
      } else {
        positionPnl = p.pnl;
      }
      pnl += positionPnl;
    }

    // 3. Total = balance values + live PnL (we avoid double-counting margins
    //    because balances already include allocated margin in most exchanges;
    //    PnL is unrealized, so it adds on top).
    const total = valueFromBalances + (hasLivePnl ? pnl : 0);

    return {
      totalValue: Number.isFinite(total) ? total : valueFromBalances,
      totalPnl: pnl,
    };
  }, [balances, positions, livePrices]);

  const pnlPositive = totalPnl >= 0;
  const useLive = isConnected && livePrices != null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center gap-6">
        <div className="flex flex-col">
          <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {useLive ? "Live Total Value" : "Portfolio Value"}
          </span>
          <span className="text-2xl font-bold tracking-tight text-slate-100 tabular-nums">
            ${fmtUsd(totalValue)}
          </span>
        </div>
        {positions.length > 0 && (
          <div className="flex flex-col">
            <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {useLive ? "Live Total PnL" : "Total PnL"}
            </span>
            <span
              className={`text-2xl font-bold tracking-tight tabular-nums ${
                pnlPositive ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {pnlPositive ? "+" : "−"}${fmtUsd(Math.abs(totalPnl))}
            </span>
          </div>
        )}
      </div>

      {/* Live indicator with pulsing dot */}
      <div className="flex items-center gap-2">
        {isConnected ? (
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-3 py-1 text-xs font-bold uppercase tracking-wide text-emerald-400">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span
                className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                style={{ animationDuration: "1.5s" }}
              />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            Live
          </span>
        ) : (
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-800/60 px-3 py-1 text-xs font-bold uppercase tracking-wide text-slate-400">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="relative inline-flex h-2 w-2 rounded-full bg-slate-500" />
            </span>
            {useLive ? "Connecting" : "Static"}
          </span>
        )}
      </div>
    </div>
  );
}

export default LivePortfolioHeader;
