"use client";

import { useEffect, useRef } from "react";

import {
  createChart,
  ColorType,
  LineStyle,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type IPriceLine,
} from "lightweight-charts";

import { useMediaQuery } from "@/hooks/use-media-query";
import type { Candle, EmaData, OrderBlock, FairValueGap } from "@/lib/types";
import type { IndicatorVisibility } from "@/components/indicator-toggle-panel";

/**
 * CandlestickChart — Client Component (lightweight-charts v5).
 *
 * Renders a full-featured candlestick chart with per-pane indicators:
 *   - Pane 0 (main): OHLC candles + EMA overlay + OB/FVG price-line
 *     zones + Bollinger Bands overlay + Volume Profile histogram overlay
 *   - Pane 1: Volume histogram
 *   - Pane 2: RSI line with 30 / 70 overbought/oversold guides
 *   - Pane 3: MACD histogram + MACD line + signal line
 *
 * The chart is dark-themed (slate-950 canvas) matching the app shell.
 * Series visibility for the indicator panes is controlled by the
 * ``indicators`` prop (driven by IndicatorTogglePanel + localStorage).
 */

/* ── Theme constants matching the app shell ──────────────────────────────── */

const COLORS = {
  background: "#0f172a", // slate-950
  textColor: "#94a3b8", // slate-400
  grid: "#1e293b", // slate-800
  border: "#334155", // slate-700
  bullish: "#22c55e", // green-500
  bearish: "#ef4444", // red-500
  volBullish: "rgba(34, 197, 94, 0.45)",
  volBearish: "rgba(239, 68, 68, 0.45)",
};

const EMA_COLORS: Record<string, string> = {
  ema_9: "#60a5fa", // blue-400
  ema_20: "#a78bfa", // violet-400
  ema_21: "#f59e0b", // amber-500
  ema_50: "#f472b6", // pink-400
  ema_200: "#34d399", // emerald-400
};

const EMA_LABELS: Record<string, string> = {
  ema_9: "EMA 9",
  ema_20: "EMA 20",
  ema_21: "EMA 21",
  ema_50: "EMA 50",
  ema_200: "EMA 200",
};

const BB_COLORS = {
  upper: "#38bdf8", // sky-400
  middle: "#94a3b8", // slate-400
  lower: "#38bdf8",
};

const RSI_COLOR = "#f59e0b"; // amber-500
const MACD_LINE_COLOR = "#22c55e"; // green
const MACD_SIGNAL_COLOR = "#ef4444"; // red
const MACD_HIST_UP = "rgba(34, 197, 94, 0.6)";
const MACD_HIST_DOWN = "rgba(239, 68, 68, 0.6)";

const SUB_PANE_HEIGHT = 150;

/* ── Time conversion ─────────────────────────────────────────────────────── */

function toTimestamp(time: string | number): UTCTimestamp {
  if (typeof time === "number") {
    const sec = time > 1e12 ? time / 1000 : time;
    return Math.floor(sec) as UTCTimestamp;
  }
  const ms = Date.parse(time);
  if (!Number.isNaN(ms)) return Math.floor(ms / 1000) as UTCTimestamp;
  const n = Number(time);
  if (!Number.isNaN(n)) return Math.floor(n > 1e12 ? n / 1000 : n) as UTCTimestamp;
  return 0 as UTCTimestamp;
}

/* ── Props ──────────────────────────────────────────────────────────────── */

export type LivePrices = Record<string, { price: number; timestamp: number }>;

/** Optional indicator series aligned to the candle timestamps. */
export interface IndicatorData {
  /** RSI series — array of {time, value} points. */
  rsi?: { time: UTCTimestamp; value: number }[];
  /** MACD series — macd, signal, histogram arrays. */
  macd?: {
    macd: { time: UTCTimestamp; value: number }[];
    signal: { time: UTCTimestamp; value: number }[];
    histogram: { time: UTCTimestamp; value: number }[];
  };
  /** Bollinger Bands — upper, middle, lower arrays. */
  bb?: {
    upper: { time: UTCTimestamp; value: number }[];
    middle: { time: UTCTimestamp; value: number }[];
    lower: { time: UTCTimestamp; value: number }[];
  };
  /** Volume Profile buckets — parallel price/volume arrays. */
  volumeProfile?: {
    price_levels: number[];
    volumes: number[];
    buy_volumes: number[];
    sell_volumes: number[];
  };
}

interface CandlestickChartProps {
  candles: Candle[];
  emas?: EmaData | null;
  orderBlocks?: OrderBlock[] | null;
  fvgs?: FairValueGap[] | null;
  /** Optional symbol label. */
  symbol?: string;
  /** Optional trade levels. */
  tradeLevels?: {
    entry?: number | null;
    stopLoss?: number | null;
    targets?: number[];
  } | null;
  /** Live prices keyed by symbol. */
  livePrices?: LivePrices | null;
  /** Per-indicator visibility (from IndicatorTogglePanel). */
  indicators?: IndicatorVisibility;
  /** Optional indicator series data. */
  indicatorData?: IndicatorData | null;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export function CandlestickChart({
  candles,
  emas = null,
  orderBlocks = null,
  fvgs = null,
  symbol = "",
  tradeLevels = null,
  livePrices = null,
  indicators,
  indicatorData = null,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const lastCandleRef = useRef<CandlestickData | null>(null);

  const isMobile = useMediaQuery("(max-width: 768px)");

  // Resolve indicator visibility defaults
  const vis = indicators;

  // Compute total chart height based on visible panes
  const paneCount = [
    true, // main pane always visible
    vis?.volume ?? true, // volume
    vis?.rsi ?? false, // RSI
    vis?.macd ?? false, // MACD
  ].filter(Boolean).length;

  const mainPaneHeight = isMobile ? 280 : 420;
  const subPaneCount = paneCount - 1; // exclude main
  const chartHeight = mainPaneHeight + subPaneCount * SUB_PANE_HEIGHT;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── Sort & deduplicate candle data ──────────────────────────────
    const seen = new Set<number>();
    const candleData: CandlestickData[] = [];
    const volData: HistogramData[] = [];

    for (const c of candles) {
      const ts = toTimestamp(c.time);
      if (ts === 0) continue;
      if (seen.has(ts)) continue;
      seen.add(ts);

      candleData.push({
        time: ts,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      });

      if (c.volume != null) {
        volData.push({
          time: ts,
          value: c.volume,
          color: c.close >= c.open ? COLORS.volBullish : COLORS.volBearish,
        });
      }
    }

    candleData.sort((a, b) => (a.time as number) - (b.time as number));
    volData.sort((a, b) => (a.time as number) - (b.time as number));

    if (candleData.length === 0) {
      return;
    }

    // ── Create chart ────────────────────────────────────────────────
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: COLORS.background },
        textColor: COLORS.textColor,
        fontSize: 11,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        attributionLogo: false,
        panes: {
          separatorColor: COLORS.border,
          separatorHoverColor: "rgba(148, 163, 184, 0.2)",
        },
      },
      grid: {
        vertLines: { color: COLORS.grid, style: LineStyle.Solid },
        horzLines: { color: COLORS.grid, style: LineStyle.Solid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: COLORS.border,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#334155",
        },
        horzLine: {
          color: COLORS.border,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#334155",
        },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        axisDoubleClickReset: true,
        mouseWheel: true,
        pinch: true,
      },
      handleScroll: {
        mouseWheel: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      kineticScroll: { touch: true, mouse: false },
      width: container.clientWidth || 600,
      height: chartHeight,
    });
    chartRef.current = chart;

    // ── Candlestick series (pane 0) ──────────────────────────────────
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.bullish,
      downColor: COLORS.bearish,
      borderUpColor: COLORS.bullish,
      borderDownColor: COLORS.bearish,
      wickUpColor: COLORS.bullish,
      wickDownColor: COLORS.bearish,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    candleSeries.setData(candleData);
    candleSeriesRef.current = candleSeries;
    lastCandleRef.current = { ...candleData[candleData.length - 1] };

    const candleTimes = candleData.map((c) => c.time as number);

    // ── EMA overlay lines (pane 0) ──────────────────────────────────
    if (vis?.ema && emas) {
      for (const [periodKey, values] of Object.entries(emas)) {
        if (!Array.isArray(values) || values.length === 0) continue;
        const color = EMA_COLORS[periodKey] ?? "#94a3b8";
        const lineData: LineData[] = [];
        const offset = candleTimes.length - values.length;
        for (let i = 0; i < values.length; i++) {
          const idx = offset + i;
          if (idx < 0 || idx >= candleTimes.length) continue;
          const v = values[i];
          if (v != null && !Number.isNaN(v)) {
            lineData.push({ time: candleTimes[idx] as UTCTimestamp, value: v });
          }
        }
        if (lineData.length === 0) continue;
        const label = EMA_LABELS[periodKey] ?? periodKey.toUpperCase();
        chart.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: label,
        }).setData(lineData);
      }
    }

    // ── Bollinger Bands overlay (pane 0) ─────────────────────────────
    if (vis?.bollinger && indicatorData?.bb) {
      const { upper, middle, lower } = indicatorData.bb;
      if (upper.length > 0) {
        chart.addSeries(LineSeries, {
          color: BB_COLORS.upper,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB Upper",
        }).setData(upper);
      }
      if (middle.length > 0) {
        chart.addSeries(LineSeries, {
          color: BB_COLORS.middle,
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB Mid",
        }).setData(middle);
      }
      if (lower.length > 0) {
        chart.addSeries(LineSeries, {
          color: BB_COLORS.lower,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: "BB Lower",
        }).setData(lower);
      }
    }

    // ── Volume Profile overlay (pane 0 right edge) ──────────────────
    // Rendered as a histogram on a separate overlay price scale, so it
    // appears as horizontal bars at each price level.
    if (indicatorData?.volumeProfile && indicatorData.volumeProfile.price_levels.length > 0) {
      const vp = indicatorData.volumeProfile;
      const maxVol = Math.max(...vp.volumes, 1);
      const vpData: HistogramData[] = [];
      // Use the last candle time so VP bars appear at the chart's right edge
      const lastTime = candleTimes[candleTimes.length - 1] as UTCTimestamp;
      for (let i = 0; i < vp.price_levels.length; i++) {
        const price = vp.price_levels[i];
        const totalVol = vp.volumes[i];
        const buyVol = vp.buy_volumes[i] ?? 0;
        const sellVol = vp.sell_volumes[i] ?? 0;
        // Positive bar = buy-dominant; negative = sell-dominant
        const isBuy = buyVol >= sellVol;
        const signedVal = isBuy ? totalVol : -totalVol;
        vpData.push({
          time: lastTime,
          value: price,
          color: isBuy
            ? `rgba(34, 197, 94, ${0.15 + 0.5 * (totalVol / maxVol)})`
            : `rgba(239, 68, 68, ${0.15 + 0.5 * (totalVol / maxVol)})`,
        });
      }
      // We can't easily draw horizontal bars in lightweight-charts v5
      // without a custom primitive. Instead, render VP as price lines
      // for the top 5 volume nodes (POC + high-volume nodes).
      const indices = vp.volumes
        .map((v, i) => ({ v, i }))
        .sort((a, b) => b.v - a.v)
        .slice(0, 8);
      for (const { v, i } of indices) {
        const price = vp.price_levels[i];
        const buyVol = vp.buy_volumes[i] ?? 0;
        const sellVol = vp.sell_volumes[i] ?? 0;
        const isBuy = buyVol >= sellVol;
        priceLinesRef.current.push(
          candleSeries.createPriceLine({
            price,
            color: isBuy
              ? `rgba(34, 197, 94, ${0.3 + 0.4 * (v / maxVol)})`
              : `rgba(239, 68, 68, ${0.3 + 0.4 * (v / maxVol)})`,
            lineWidth: 2,
            lineStyle: LineStyle.Dotted,
            lineVisible: true,
            axisLabelVisible: false,
            title: `VP ${isBuy ? "▲" : "▼"}`,
          })
        );
      }
    }

    // ── Volume histogram (pane 1) ────────────────────────────────────
    let nextPane = 1;
    if (vis?.volume && volData.length > 0) {
      const volSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          priceScaleId: "vol",
        },
        nextPane
      );
      chart.priceScale("vol", nextPane).applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },
      });
      volSeries.setData(volData);
      volSeries.priceScale().applyOptions({ visible: false });
      nextPane++;
    }

    // ── RSI sub-pane ─────────────────────────────────────────────────
    if (vis?.rsi && indicatorData?.rsi && indicatorData.rsi.length > 0) {
      const rsiPaneIdx = nextPane;
      const rsiSeries = chart.addSeries(
        LineSeries,
        {
          color: RSI_COLOR,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: "RSI(14)",
        },
        rsiPaneIdx
      );
      rsiSeries.setData(indicatorData.rsi);

      // RSI 30 / 70 horizontal guides
      rsiSeries.createPriceLine({
        price: 70,
        color: "rgba(239, 68, 68, 0.4)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        title: "OB 70",
      });
      rsiSeries.createPriceLine({
        price: 30,
        color: "rgba(34, 197, 94, 0.4)",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        title: "OS 30",
      });
      // RSI pane price scale — fix at 0–100
      rsiSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.1, bottom: 0.1 },
        autoScale: false,
      });
      nextPane++;
    }

    // ── MACD sub-pane ────────────────────────────────────────────────
    if (vis?.macd && indicatorData?.macd) {
      const macdPaneIdx = nextPane;
      const { macd, signal, histogram } = indicatorData.macd;

      // Histogram bars
      if (histogram.length > 0) {
        const histData: HistogramData[] = histogram.map((p) => ({
          time: p.time,
          value: p.value,
          color:
            p.value >= 0
              ? MACD_HIST_UP
              : MACD_HIST_DOWN,
        }));
        const histSeries = chart.addSeries(
          HistogramSeries,
          {
            priceLineVisible: false,
            lastValueVisible: false,
            title: "MACD Hist",
          },
          macdPaneIdx
        );
        histSeries.setData(histData);
      }

      // MACD line
      if (macd.length > 0) {
        chart.addSeries(
          LineSeries,
          {
            color: MACD_LINE_COLOR,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            title: "MACD",
          },
          macdPaneIdx
        ).setData(macd);
      }

      // Signal line
      if (signal.length > 0) {
        chart.addSeries(
          LineSeries,
          {
            color: MACD_SIGNAL_COLOR,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            title: "Signal",
          },
          macdPaneIdx
        ).setData(signal);
      }
      nextPane++;
    }

    // ── Order block zones (price lines on candle series) ─────────────
    if (vis?.orderBlocks && orderBlocks && orderBlocks.length > 0) {
      for (const ob of orderBlocks) {
        if (ob.price_high == null && ob.price_low == null) continue;
        const isBull = (ob.type ?? "bullish").toLowerCase() !== "bearish";
        const color = isBull ? "rgba(34, 197, 94, 0.5)" : "rgba(239, 68, 68, 0.5)";
        if (ob.price_high != null) {
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: ob.price_high,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              lineVisible: true,
              axisLabelVisible: true,
              title: `${isBull ? "OB↑" : "OB↓"} high`,
            })
          );
        }
        if (ob.price_low != null) {
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: ob.price_low,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              lineVisible: true,
              axisLabelVisible: true,
              title: `${isBull ? "OB↑" : "OB↓"} low`,
            })
          );
        }
      }
    }

    // ── Fair value gap zones ─────────────────────────────────────────
    if (vis?.fairValueGaps && fvgs && fvgs.length > 0) {
      for (const fvg of fvgs) {
        if (fvg.price_high == null && fvg.price_low == null) continue;
        const color = "rgba(250, 204, 21, 0.45)"; // yellow-400
        if (fvg.price_high != null) {
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: fvg.price_high,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.LargeDashed,
              lineVisible: true,
              axisLabelVisible: true,
              title: "FVG high",
            })
          );
        }
        if (fvg.price_low != null) {
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: fvg.price_low,
              color,
              lineWidth: 1,
              lineStyle: LineStyle.LargeDashed,
              lineVisible: true,
              axisLabelVisible: true,
              title: "FVG low",
            })
          );
        }
      }
    }

    // ── Trade levels ─────────────────────────────────────────────────
    if (tradeLevels) {
      if (tradeLevels.entry != null) {
        priceLinesRef.current.push(
          candleSeries.createPriceLine({
            price: tradeLevels.entry,
            color: "#38bdf8", // sky-400
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            lineVisible: true,
            axisLabelVisible: true,
            title: "Entry",
          })
        );
      }
      if (tradeLevels.stopLoss != null) {
        priceLinesRef.current.push(
          candleSeries.createPriceLine({
            price: tradeLevels.stopLoss,
            color: "#ef4444",
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            lineVisible: true,
            axisLabelVisible: true,
            title: "Stop",
          })
        );
      }
      if (tradeLevels.targets) {
        tradeLevels.targets.forEach((t, i) => {
          if (t == null) return;
          priceLinesRef.current.push(
            candleSeries.createPriceLine({
              price: t,
              color: "#22c55e",
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              lineVisible: true,
              axisLabelVisible: true,
              title: `T${i + 1}`,
            })
          );
        });
      }
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: chartHeight,
        });
      }
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      priceLinesRef.current = [];
      candleSeriesRef.current = null;
      lastCandleRef.current = null;
      chart.remove();
      chartRef.current = null;
    };
    // Re-create the chart when any data reference or pane layout changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    candles,
    emas,
    orderBlocks,
    fvgs,
    tradeLevels,
    symbol,
    indicatorData,
    vis,
    chartHeight,
    isMobile,
  ]);

  // ── Live price updates ───────────────────────────────────────────────
  useEffect(() => {
    if (!livePrices) return;
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    const tick = livePrices[sym];
    if (!tick || typeof tick.price !== "number") return;

    const series = candleSeriesRef.current;
    const last = lastCandleRef.current;
    if (!series || !last) return;

    const price = tick.price;
    const updated: CandlestickData = {
      time: last.time,
      open: last.open,
      high: Math.max(last.high, price),
      low: Math.min(last.low, price),
      close: price,
    };

    try {
      series.update(updated);
      lastCandleRef.current = updated;
    } catch (err) {
      console.debug("[chart] series.update failed:", err);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [livePrices, symbol]);

  if (!candles || candles.length === 0) {
    return (
      <div className="flex h-48 w-full items-center justify-center rounded-xl border border-slate-800 bg-slate-900/60 text-sm text-slate-500">
        No candle data available for chart rendering.
      </div>
    );
  }

  return (
    <div className="w-full">
      <div
        ref={containerRef}
        className="w-full rounded-xl border border-slate-800 bg-slate-950"
        style={{ minHeight: chartHeight }}
      />
    </div>
  );
}

export default CandlestickChart;
