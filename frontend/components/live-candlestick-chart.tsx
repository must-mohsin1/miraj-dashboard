"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickChart, type LivePrices } from "@/components/candlestick-chart";
import { LivePriceBadge } from "@/components/live-price-badge";
import { IndicatorTogglePanel, DEFAULT_INDICATOR_VISIBILITY, type IndicatorVisibility } from "@/components/indicator-toggle-panel";
import type { Candle, EmaData, FairValueGap, OrderBlock } from "@/lib/types";

interface LiveCandlestickChartProps {
  symbol: string;
  candles: Candle[];
  emas?: EmaData | null;
  orderBlocks?: OrderBlock[] | null;
  fvgs?: FairValueGap[] | null;
  tradeLevels?: {
    entry?: number | null;
    stopLoss?: number | null;
    targets?: number[];
  } | null;
  token: string | null | undefined;
}

export function LiveCandlestickChart({
  symbol,
  candles,
  emas = null,
  orderBlocks = null,
  fvgs = null,
  tradeLevels = null,
  token: _serverToken,
}: LiveCandlestickChartProps) {
  const [prices, setPrices] = useState<Record<string, { price: number; timestamp: number }>>({});
  const [isConnected, setIsConnected] = useState(false);
  const [indicators, setIndicators] = useState<IndicatorVisibility>(DEFAULT_INDICATOR_VISIBILITY);
  const esRef = useRef<EventSource | null>(null);

  const symbols = useMemo(() => [symbol], [symbol]);

  useEffect(() => {
    let cancelled = false;

    async function connect() {
      if (cancelled) return;

      // Fetch token client-side
      try {
        const res = await fetch("/api/auth/session");
        const data = await res.json();
        const token = data?.user?.accessToken;
        if (!token || cancelled) return;

        const symParam = symbols.map((s) => s.toUpperCase()).join(",");
        const url = `/api/v1/stream/prices?symbols=${encodeURIComponent(symParam)}&token=${encodeURIComponent(token)}`;

        // Close old connection
        if (esRef.current) {
          esRef.current.close();
        }

        const es = new EventSource(url);
        esRef.current = es;

        es.onopen = () => {
          if (!cancelled) setIsConnected(true);
        };

        es.onmessage = (event) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(event.data);
            if (data.symbol && typeof data.price === "number") {
              const sym = data.symbol.toUpperCase();
              setPrices((prev) => ({
                ...prev,
                [sym]: { price: data.price, timestamp: data.timestamp },
              }));
            }
          } catch {}
        };

        es.onerror = () => {
          if (!cancelled) setIsConnected(false);
          es.close();
          // Reconnect after 3s
          setTimeout(() => {
            if (!cancelled) connect();
          }, 3000);
        };
      } catch {
        if (!cancelled) {
          setTimeout(() => {
            if (!cancelled) connect();
          }, 3000);
        }
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [symbols]);

  const livePrices: LivePrices | null = isConnected && Object.keys(prices).length > 0
    ? prices
    : null;

  const liveTick = symbol ? prices[symbol.toUpperCase()] : undefined;

  return (
    <div className="w-full">
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
              <span className="relative flex h-2 w-2" aria-hidden>
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" style={{ animationDuration: "1.5s" }} />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Live
            </span>
          )}
        </div>
      </div>

      <IndicatorTogglePanel visibility={indicators} onChange={setIndicators} />

      <CandlestickChart
        candles={candles}
        emas={emas}
        orderBlocks={orderBlocks}
        fvgs={fvgs}
        symbol={symbol}
        tradeLevels={tradeLevels}
        livePrices={livePrices}
        indicators={indicators}
      />
    </div>
  );
}

export default LiveCandlestickChart;
