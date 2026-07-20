"use client";

import { useEffect, useRef, useState } from "react";

import type { LivePrice } from "@/hooks/use-price-stream";

/**
 * LivePriceBadge — Client Component.
 *
 * Renders a compact "LIVE" price pill: shows the current price, a green/red
 * flash animation on each update (green = price went up, red = went down),
 * and a pulsing green dot to indicate the stream is connected.
 *
 * Designed for use in the analysis page header and in the scanner watchlist
 * table rows.
 *
 * @example
 *   const { prices, isConnected } = usePriceStream(["BTC-USD"], token);
 *   <LivePriceBadge symbol="BTC-USD" price={prices["BTC-USD"]} connected={isConnected} />
 */

interface LivePriceBadgeProps {
  /** Trading pair symbol (display label). */
  symbol: string;
  /** Current live price tick (or undefined when no data yet). */
  price?: LivePrice;
  /** Whether the SSE stream is connected. When false, shows a muted dot. */
  connected?: boolean;
  /** Optional className for layout overrides. */
  className?: string;
  /** Number of decimal places. Defaults to 2. */
  precision?: number;
}

type FlashDirection = "up" | "down" | null;

export function LivePriceBadge({
  symbol,
  price,
  connected = false,
  className = "",
  precision = 2,
}: LivePriceBadgeProps) {
  const formattedPrice = price
    ? price.price.toLocaleString(undefined, {
        minimumFractionDigits: precision,
        maximumFractionDigits: precision,
      })
    : "—";

  // Kill tick urgency (DESIGN.md): the price updates silently — no flash,
  // no per-tick color. Direction color belongs to verdicts and P&L only.
  const priceColor = "text-slate-100";
  const bgFlash = "bg-slate-800/60";

  return (
    <span
      className={`inline-flex items-center gap-2 border border-slate-700 px-2.5 py-0.5 text-xs font-medium ${bgFlash} ${className}`}
    >
      {/* LIVE indicator with pulsing dot */}
      <span className="flex items-center gap-1.5">
        <span
          className={`relative flex h-2 w-2 ${
            connected ? "" : "opacity-40"
          }`}
        >
          {connected && (
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
              style={{ animationDuration: "1.5s" }}
            />
          )}
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              connected ? "bg-emerald-400" : "bg-slate-500"
            }`}
          />
        </span>
        <span
          className={`text-[10px] font-bold uppercase tracking-wide ${
            connected ? "text-emerald-400" : "text-slate-500"
          }`}
        >
          {connected ? "Live" : "Off"}
        </span>
      </span>

      {/* Symbol + price */}
      {symbol && (
        <span className="text-slate-400">{symbol}</span>
      )}
      <span className={`font-mono tabular-nums ${priceColor}`}>
        {formattedPrice}
      </span>
    </span>
  );
}

export default LivePriceBadge;
