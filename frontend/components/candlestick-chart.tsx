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

import type { Candle, EmaData, OrderBlock, FairValueGap } from "@/lib/types";

/**
 * CandlestickChart — Client Component (lightweight-charts v5).
 *
 * Renders a full-featured candlestick chart with:
 *  - OHLC candles (green bullish / red bearish) in the main pane
 *  - A volume histogram in a separate lower pane
 *  - EMA overlay lines (EMA 20 / EMA 50, opts: 9, 21) in the main pane
 *  - Order block zones drawn as horizontal price-line pairs (green/red)
 *  - Fair-value-gap zones drawn as dashed yellow price-line pairs
 *  - A dark slate theme matching the app shell
 *  - Responsive full-width sizing via a ResizeObserver
 *
 * Because lightweight-charts mutates the DOM directly, the chart is created
 * once inside a ref'd container and torn down on unmount; subsequent prop
 * changes rebuild the chart (the component is intended to be keyed by
 * symbol so a fresh analysis remounts it).
 */

/* ── Theme constants matching the app shell ──────────────────────────────── */

const COLORS = {
  background: "#0f172a", // slate-950 (transparent-ish canvas)
  textColor: "#94a3b8", // slate-400
  grid: "#1e293b", // slate-800
  border: "#334155", // slate-700
  bullish: "#22c55e", // green-500
  bearish: "#ef4444", // red-500
  volBullish: "rgba(34, 197, 94, 0.45)",
  volBearish: "rgba(239, 68, 68, 0.45)",
};

/** EMA colour per period label. Looks for keys "ema_9", "ema_21", "ema_50". */
const EMA_COLORS: Record<string, string> = {
  ema_9: "#60a5fa", // blue-400
  ema_21: "#f59e0b", // amber-500
  ema_50: "#a78bfa", // violet-400
};

const EMA_LABELS: Record<string, string> = {
  ema_9: "EMA 9",
  ema_21: "EMA 21",
  ema_50: "EMA 50",
};

/* ── Time conversion ─────────────────────────────────────────────────────── */

/**
 * Convert a candle `time` (ISO-8601 string or epoch) to a UTCTimestamp
 * (seconds since epoch). lightweight-charts requires monotonically
 * increasing timestamps in seconds.
 */
function toTimestamp(time: string | number): UTCTimestamp {
  if (typeof time === "number") {
    // If the number looks like milliseconds, divide; otherwise assume seconds
    const sec = time > 1e12 ? time / 1000 : time;
    return Math.floor(sec) as UTCTimestamp;
  }
  const ms = Date.parse(time);
  if (!Number.isNaN(ms)) return Math.floor(ms / 1000) as UTCTimestamp;
  // Fallback: try parsing as a plain number
  const n = Number(time);
  if (!Number.isNaN(n)) return Math.floor(n > 1e12 ? n / 1000 : n) as UTCTimestamp;
  return 0 as UTCTimestamp;
}

/* ── Props ──────────────────────────────────────────────────────────────── */

interface CandlestickChartProps {
  candles: Candle[];
  emas?: EmaData | null;
  orderBlocks?: OrderBlock[] | null;
  fvgs?: FairValueGap[] | null;
  /** Optional symbol label shown in the top-left of the chart. */
  symbol?: string;
  /** Optional entry/stop/target levels to draw as price lines. */
  tradeLevels?: {
    entry?: number | null;
    stopLoss?: number | null;
    targets?: number[];
  } | null;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export function CandlestickChart({
  candles,
  emas = null,
  orderBlocks = null,
  fvgs = null,
  symbol = "",
  tradeLevels = null,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // ── Create chart with dark theme ────────────────────────────────
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
      width: container.clientWidth || 600,
      height: 500,
    });
    chartRef.current = chart;

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
        // Optional colour override is ignored; we rely on up/down colors below
      });

      if (c.volume != null) {
        volData.push({
          time: ts,
          value: c.volume,
          color: c.close >= c.open ? COLORS.volBullish : COLORS.volBearish,
        });
      }
    }

    // Sort ascending by time (lightweight-charts requires this)
    candleData.sort((a, b) => (a.time as number) - (b.time as number));
    volData.sort((a, b) => (a.time as number) - (b.time as number));

    if (candleData.length === 0) {
      chart.applyOptions({ height: 120 });
      return;
    }

    // ── Candlestick series (main pane, index 0) ─────────────────────
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

    // ── EMA overlay lines (main pane) ───────────────────────────────
    // The backend returns emas as {period: number[]} aligned 1-to-1 with
    // the candles array (same length, same order). We re-align to the
    // candle timestamps so lightweight-charts can plot them.
    const candleTimes = candleData.map((c) => c.time as number);
    if (emas) {
      for (const [periodKey, values] of Object.entries(emas)) {
        if (!Array.isArray(values) || values.length === 0) continue;
        const color = EMA_COLORS[periodKey] ?? "#94a3b8";
        const lineData: LineData[] = [];
        // Align from the end (values are the most recent N points)
        const offset = candleTimes.length - values.length;
        for (let i = 0; i < values.length; i++) {
          const candleIdx = offset + i;
          if (candleIdx < 0 || candleIdx >= candleTimes.length) continue;
          const t = candleTimes[candleIdx];
          const v = values[i];
          if (v != null && !Number.isNaN(v)) {
            lineData.push({ time: t as UTCTimestamp, value: v });
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

    // ── Volume histogram (separate lower pane, index 1) ─────────────
    if (volData.length > 0) {
      const volSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          priceScaleId: "vol",
        },
        1 // paneIndex 1 → lower pane
      );
      // Give the volume pane its own price scale so it doesn't overlap candles
      chart.priceScale("vol", 1).applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },
      });
      volSeries.setData(volData);
      volSeries.priceScale().applyOptions({
        visible: false,
      });
    }

    // ── Order block zones (price lines on the candle series) ─────────
    // lightweight-charts has no native rectangle primitive, so we mark
    // each zone's high and low with a horizontal price line. Bullish
    // zones are green, bearish zones red.
    if (orderBlocks && orderBlocks.length > 0) {
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

    // ── Fair value gap zones (dashed yellow price lines) ─────────────
    if (fvgs && fvgs.length > 0) {
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

    // ── Trade levels (entry / stop / targets) ───────────────────────
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

    // Optionally set the chart title via a watermark-like overlay
    // (lightweight-charts v5 supports createTextWatermark plugin; we keep
    // it lightweight here and rely on the surrounding card header instead.)

    // ── Fit content + responsive resize ─────────────────────────────
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    // Cleanup on unmount or prop change
    return () => {
      resizeObserver.disconnect();
      priceLinesRef.current = [];
      chart.remove();
      chartRef.current = null;
    };
    // Re-create the chart whenever any data array reference changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, emas, orderBlocks, fvgs, tradeLevels, symbol]);

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
        style={{ minHeight: 500 }}
      />
      {/* Legend */}
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-400">
        {/* Candles */}
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: COLORS.bullish }}
          />
          Bullish
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: COLORS.bearish }}
          />
          Bearish
        </span>
        {/* EMAs */}
        {emas &&
          Object.keys(emas).map((period) => {
            const key = EMA_LABELS[period] ?? period;
            const color = EMA_COLORS[period] ?? "#94a3b8";
            return (
              <span key={period} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-0.5 w-4 rounded-full"
                  style={{ backgroundColor: color }}
                />
                {key}
              </span>
            );
          })}
        {/* Order blocks */}
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm border border-dashed"
            style={{ borderColor: "rgba(34, 197, 94, 0.6)" }}
          />
          Order Block
        </span>
        {/* FVGs */}
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm border border-dashed"
            style={{ borderColor: "rgba(250, 204, 21, 0.6)" }}
          />
          Fair Value Gap
        </span>
      </div>
    </div>
  );
}

export default CandlestickChart;
