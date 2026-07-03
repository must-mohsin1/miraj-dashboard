"use client";

import { useMemo } from "react";
import { useSession } from "next-auth/react";

import { CandlestickChart, type LivePrices } from "@/components/candlestick-chart";
import { LivePriceBadge } from "@/components/live-price-badge";
import { usePriceStream } from "@/hooks/use-price-stream";
import type { Candle, EmaData, FairValueGap, OrderBlock } from "@/lib/types";

/**
 * LiveCandlestickChart — Client Component wrapper around CandlestickChart.
 *
 * Adds real-time price streaming to the static candlestick chart by passing
 * the current live prices from ``usePriceStream`` into the chart's
 * ``livePrices`` prop. Also renders a ``LivePriceBadge`` + "LIVE" pill in the
 * chart header when the SSE connection is active.
 *
 * This wrapper exists so the analysis detail page (a Server Component) can
 * embed the chart without itself needing to be a client component — server
 * components can't call hooks.
 */

interface LiveCandlestickChartProps {
  /** The trading pair symbol being analysed (e.g. "BTC-USD"). */
  symbol: string;
  candles: Candle[];
  emas?: EmaData | null;
  orderBlocks?: OrderBlock[] | null;
  fvgs?: FairValueGap[] | null;
  /** Optional entry/stop/target levels to draw as price lines. */
  tradeLevels?: {
    entry?: number | null;
    stopLoss?: number | null;
    targets?: number[];
  } | null;
  /** Signed-in user's JWT access token (null when unauthenticated). */
  token: string | null | undefined;
}

export function LiveCandlestickChart({
  symbol,
  candles,
  emas = null,
  orderBlocks = null,
  fvgs = null,
  tradeLevels = null,
  token,
}: LiveCandlestickChartProps) {
  // Subscribe to a single symbol's live price stream.
  // useMemo keeps the array reference stable so the hook's debounce doesn't
  // fire on every render.
  // Get token client-side via useSession (server-passed token isn't available in RSC payload)
  const { data: session } = useSession();
  const clientToken = session?.accessToken ?? token;

  const symbols = useMemo(() => [symbol], [symbol]);
  const { prices, isConnected } = usePriceStream(symbols, clientToken);

  const livePrices: LivePrices | null = isConnected && Object.keys(prices).length > 0
    ? prices
    : null;

  const liveTick = symbol ? prices[symbol.toUpperCase()] : undefined;

  return (
    <div className="w-full">
      {/* Header row: chart title + live badge */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-300">
          Price Chart — {symbol}
        </h3>
        <div className="flex items-center gap-2">
          <LivePriceBadge
            symbol={symbol}
            price={liveTick}
            connected={isConnected}
          />
          {isConnected && (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-400">
              <span
                className="relative flex h-2 w-2"
                aria-hidden
              >
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                  style={{ animationDuration: "1.5s" }}
                />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Live
            </span>
          )}
        </div>
      </div>

      <CandlestickChart
        candles={candles}
        emas={emas}
        orderBlocks={orderBlocks}
        fvgs={fvgs}
        symbol={symbol}
        tradeLevels={tradeLevels}
        livePrices={livePrices}
      />
    </div>
  );
}

export default LiveCandlestickChart;
