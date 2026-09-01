"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CandlestickChart, type LivePrices } from "@/components/candlestick-chart";
import { LivePriceBadge } from "@/components/live-price-badge";
import { IndicatorTogglePanel, DEFAULT_INDICATOR_VISIBILITY, type IndicatorVisibility } from "@/components/indicator-toggle-panel";
import { TimeframeSelector } from "@/components/timeframe-selector";
import { buildEmaOverlay, buildIndicatorData } from "@/lib/chart-indicators";
import type {
  Candle,
  CandlesResponse,
  EmaData,
  FairValueGap,
  MacdData,
  BollingerBandsData,
  OrderBlock,
  Timeframe,
} from "@/lib/types";

interface LiveCandlestickChartProps {
  symbol: string;
  candles: Candle[];
  emas?: EmaData | null;
  orderBlocks?: OrderBlock[] | null;
  fvgs?: FairValueGap[] | null;
  rsi?: number[] | null;
  macd?: MacdData | null;
  bb?: BollingerBandsData | null;
  tradeLevels?: {
    entry?: number | null;
    stopLoss?: number | null;
    targets?: number[];
  } | null;
  token: string | null | undefined;
}

export function LiveCandlestickChart({
  symbol,
  candles: scanCandles,
  emas: scanEmas = null,
  orderBlocks = null,
  fvgs = null,
  rsi: scanRsi = null,
  macd: scanMacd = null,
  bb: scanBb = null,
  tradeLevels = null,
  token: _serverToken,
}: LiveCandlestickChartProps) {
  const [prices, setPrices] = useState<Record<string, { price: number; timestamp: number }>>({});
  const [isConnected, setIsConnected] = useState(false);
  const [indicators, setIndicators] = useState<IndicatorVisibility>(DEFAULT_INDICATOR_VISIBILITY);
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [tfCandles, setTfCandles] = useState<Candle[] | null>(null);
  const [tfError, setTfError] = useState<string | null>(null);
  const [tfLoading, setTfLoading] = useState(false);
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

  useEffect(() => {
    let cancelled = false;
    async function loadTimeframe() {
      setTfLoading(true);
      setTfError(null);
      setTfCandles(null);
      try {
        const session = await fetch("/api/auth/session").then((r) => r.json());
        const token = session?.user?.accessToken as string | undefined;
        const headers: HeadersInit = {};
        if (token) headers.Authorization = `Bearer ${token}`;
        const res = await fetch(
          `/api/v1/charts/${encodeURIComponent(symbol)}/candles?timeframe=${timeframe}&limit=300`,
          { headers, cache: "no-store" }
        );
        if (!res.ok) {
          throw new Error(`Candle fetch failed (${res.status})`);
        }
        const payload = (await res.json()) as CandlesResponse;
        if (payload.timeframe !== timeframe) {
          throw new Error("Candle response timeframe mismatch");
        }
        if (!cancelled) {
          setTfCandles(payload.candles ?? []);
        }
      } catch {
        if (!cancelled) {
          setTfCandles(null);
          setTfError(`${timeframe} candles unavailable.`);
        }
      } finally {
        if (!cancelled) setTfLoading(false);
      }
    }
    void loadTimeframe();
    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe]);

  const displayCandles = useMemo(() => {
    if (tfCandles && tfCandles.length > 0) return tfCandles;
    return timeframe === "1d" ? scanCandles : [];
  }, [tfCandles, timeframe, scanCandles]);
  const useScanSeries = timeframe === "1d" && (!tfCandles || tfCandles.length === 0);
  const displayEmas = useMemo(
    () => (useScanSeries && scanEmas ? scanEmas : buildEmaOverlay(displayCandles)),
    [useScanSeries, scanEmas, displayCandles]
  );
  const indicatorData = useMemo(
    () =>
      buildIndicatorData(
        displayCandles,
        useScanSeries ? { rsi: scanRsi, macd: scanMacd, bb: scanBb } : null,
        { preferScan: useScanSeries }
      ),
    [displayCandles, useScanSeries, scanRsi, scanMacd, scanBb]
  );

  const livePrices: LivePrices | null = isConnected && Object.keys(prices).length > 0
    ? prices
    : null;

  const liveTick = symbol ? prices[symbol.toUpperCase()] : undefined;

  const handleTimeframeChange = (nextTimeframe: Timeframe) => {
    if (nextTimeframe === timeframe) return;
    setTfCandles(null);
    setTfError(null);
    setTimeframe(nextTimeframe);
  };

  return (
    <div className="w-full">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          Price chart — {symbol}
        </h3>
        <div className="flex items-center gap-2">
          <TimeframeSelector
            timeframe={timeframe}
            onTimeframeChange={handleTimeframeChange}
          />
          <LivePriceBadge
            symbol={symbol}
            price={liveTick}
            connected={isConnected}
          />
          {isConnected && (
            <span className="inline-flex items-center gap-1 border border-[#2A2620] bg-[#1D1A16] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#6CA98F]">
              <span className="relative flex h-2 w-2" aria-hidden>
                <span className="relative inline-flex h-2 w-2 rounded-full bg-[#6CA98F]" />
              </span>
              Live
            </span>
          )}
        </div>
      </div>

      {tfError && (
        <p className="mb-2 text-xs text-[#8E8778]" role="status">
          {tfError}
          {timeframe === "1d" && scanCandles.length > 0
            ? " Showing scan daily candles."
            : ` ${timeframe} candles unavailable.`}
        </p>
      )}
      {tfLoading && (
        <p className="mb-2 text-xs text-[#8E8778]" aria-busy="true">
          Loading {timeframe} candles…
        </p>
      )}

      <IndicatorTogglePanel visibility={indicators} onChange={setIndicators} />

      {displayCandles.length === 0 ? (
        <p className="border border-[#2A2620] bg-[#161411] p-6 text-sm text-[#8E8778]">
          No candles for this timeframe.
        </p>
      ) : (
        <CandlestickChart
          candles={displayCandles}
          emas={displayEmas}
          orderBlocks={timeframe === "1d" ? orderBlocks : null}
          fvgs={timeframe === "1d" ? fvgs : null}
          symbol={symbol}
          tradeLevels={tradeLevels}
          livePrices={livePrices}
          indicators={indicators}
          indicatorData={indicatorData}
        />
      )}
    </div>
  );
}

export default LiveCandlestickChart;
