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

export interface LiveCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  closed: boolean;
}

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
    direction?: string | null;
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
  const [liveCandle, setLiveCandle] = useState<LiveCandle | null>(null);
  const [candleStreamConnected, setCandleStreamConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const candleWsRef = useRef<WebSocket | null>(null);

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
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const normalized = symbol.trim().toUpperCase().replace(/[\\/-]/g, "");
    const streamSymbol = normalized.endsWith("USDT") ? normalized.toLowerCase() : null;
    const interval = timeframe === "1w" ? "1w" : timeframe;

    setLiveCandle(null);
    setCandleStreamConnected(false);
    if (!streamSymbol || typeof WebSocket === "undefined") return;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${streamSymbol}@kline_${interval}`);
      candleWsRef.current = ws;
      ws.onopen = () => {
        if (!cancelled) setCandleStreamConnected(true);
      };
      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data);
          const kline = payload?.k;
          if (!kline) return;
          setLiveCandle({
            time: Math.floor(Number(kline.t) / 1000),
            open: Number(kline.o),
            high: Number(kline.h),
            low: Number(kline.l),
            close: Number(kline.c),
            volume: Number(kline.v),
            closed: Boolean(kline.x),
          });
        } catch {
          // Ignore malformed public frames; the reconnect path remains active.
        }
      };
      ws.onerror = () => {
        if (!cancelled) setCandleStreamConnected(false);
        ws.close();
      };
      ws.onclose = () => {
        if (cancelled) return;
        setCandleStreamConnected(false);
        reconnectTimer = setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      candleWsRef.current?.close();
      candleWsRef.current = null;
    };
  }, [symbol, timeframe]);

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
    const base = tfCandles && tfCandles.length > 0 ? tfCandles : timeframe === "1d" ? scanCandles : [];
    if (!liveCandle || base.length === 0) return base;
    const nextCandle: Candle = {
      time: liveCandle.time,
      open: liveCandle.open,
      high: liveCandle.high,
      low: liveCandle.low,
      close: liveCandle.close,
      volume: liveCandle.volume,
    };
    const last = base[base.length - 1];
    if (Number(last.time) === liveCandle.time) return [...base.slice(0, -1), nextCandle];
    if (Number(last.time) < liveCandle.time) return [...base, nextCandle];
    return base;
  }, [tfCandles, timeframe, scanCandles, liveCandle]);
  const useScanSeries = timeframe === "1d" && !liveCandle && (!tfCandles || tfCandles.length === 0);
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
          {candleStreamConnected && (
            <span className="inline-flex items-center gap-1 border border-[#2A2620] bg-[#1D1A16] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#6CA98F]">
              Candle stream
            </span>
          )}
          {!candleStreamConnected && symbol.toUpperCase().replace(/[\\/-]/g, "").endsWith("USDT") && (
            <span className="inline-flex items-center gap-1 border border-[#4A3028] bg-[#211815] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#C96A55]">
              Candle reconnecting
            </span>
          )}
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
          drawingScope={timeframe}
          tradeLevels={tradeLevels}
          liveCandle={liveCandle}
          livePrices={livePrices}
          indicators={indicators}
          indicatorData={indicatorData}
        />
      )}
    </div>
  );
}

export default LiveCandlestickChart;
