"use client";

import { useEffect, useRef, useState } from "react";

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
  type MouseEventParams,
  type Time,
} from "lightweight-charts";

import { useMediaQuery } from "@/hooks/use-media-query";
import type { Candle, EmaData, OrderBlock, FairValueGap } from "@/lib/types";
import {
  DEFAULT_INDICATOR_VISIBILITY,
  type IndicatorVisibility,
} from "@/components/indicator-toggle-panel";
import {
  ChartDrawingToolbar,
  type ChartDrawingTool,
} from "@/components/chart-drawing-toolbar";

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
 * The chart uses the INK theme shared by the analysis workspace.
 * Series visibility for the indicator panes is controlled by the
 * ``indicators`` prop (driven by IndicatorTogglePanel + localStorage).
 */

/* ── Theme constants matching the app shell ──────────────────────────────── */

const COLORS = {
  background: "#0F0E0C",
  textColor: "#8E8778",
  grid: "#2A2620",
  border: "#2A2620",
  bullish: "#6CA98F",
  bearish: "#C96A55",
  volBullish: "rgba(108, 169, 143, 0.45)",
  volBearish: "rgba(201, 106, 85, 0.45)",
};

const DRAWING_COLOR = "#C2A36B";

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
  middle: "#8E8778",
  lower: "#38bdf8",
};

const RSI_COLOR = "#f59e0b"; // amber-500
const MACD_LINE_COLOR = "#6CA98F";
const MACD_SIGNAL_COLOR = "#C96A55";
const MACD_HIST_UP = "rgba(108, 169, 143, 0.6)";
const MACD_HIST_DOWN = "rgba(201, 106, 85, 0.6)";

const SUB_PANE_HEIGHT = 150;

type DrawingPoint = { time: Time; value: number };
type ChartDrawing =
  | { kind: "horizontal"; price: number }
  | { kind: "trend"; start: DrawingPoint; end: DrawingPoint }
  | { kind: "fib"; start: DrawingPoint; end: DrawingPoint };

type DrawingArtifact =
  | { kind: "priceLine"; line: IPriceLine }
  | { kind: "series"; series: ISeriesApi<"Line"> };

const FIB_LEVELS = [0, 0.382, 0.5, 0.618, 1] as const;

function timeKey(time: Time): number {
  if (typeof time === "number") return time;
  if (typeof time === "string") return Date.parse(time);
  return Date.UTC(time.year, time.month - 1, time.day) / 1000;
}

function renderDrawing(
  chart: IChartApi,
  candleSeries: ISeriesApi<"Candlestick">,
  drawing: ChartDrawing
): DrawingArtifact[] {
  if (drawing.kind === "horizontal") {
    return [
      {
        kind: "priceLine",
        line: candleSeries.createPriceLine({
          price: drawing.price,
          color: DRAWING_COLOR,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          lineVisible: true,
          axisLabelVisible: true,
          title: "H Line",
        }),
      },
    ];
  }

  if (drawing.kind === "trend") {
    const points = [drawing.start, drawing.end].sort(
      (a, b) => timeKey(a.time) - timeKey(b.time)
    );
    if (timeKey(points[0].time) === timeKey(points[1].time)) return [];
    const series = chart.addSeries(LineSeries, {
      color: DRAWING_COLOR,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      title: "Trend",
    });
    series.setData(points);
    return [{ kind: "series", series }];
  }

  return FIB_LEVELS.map((level) => {
    const price = drawing.start.value + (drawing.end.value - drawing.start.value) * level;
    return {
      kind: "priceLine" as const,
      line: candleSeries.createPriceLine({
        price,
        color: DRAWING_COLOR,
        lineWidth: level === 0 || level === 1 ? 2 : 1,
        lineStyle: level === 0 || level === 1 ? LineStyle.Solid : LineStyle.Dashed,
        lineVisible: true,
        axisLabelVisible: true,
        title: `Fib ${Math.round(level * 1000) / 10}%`,
      }),
    };
  });
}

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
  const drawingArtifactsRef = useRef<DrawingArtifact[]>([]);
  const drawingsRef = useRef<ChartDrawing[]>([]);
  const pendingDrawingRef = useRef<DrawingPoint | null>(null);
  const activeToolRef = useRef<ChartDrawingTool>("cursor");
  const [activeTool, setActiveTool] = useState<ChartDrawingTool>("cursor");
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);

  const isMobile = useMediaQuery("(max-width: 768px)");

  // Resolve indicator visibility defaults
  const vis = indicators ?? DEFAULT_INDICATOR_VISIBILITY;

  // Compute total chart height based on visible panes
  const paneCount = [
    true, // main pane always visible
    vis.volume, // volume
    vis.rsi, // RSI
    vis.macd, // MACD
  ].filter(Boolean).length;

  const mainPaneHeight = isMobile ? 280 : 420;
  const subPaneCount = paneCount - 1; // exclude main
  const chartHeight = mainPaneHeight + subPaneCount * SUB_PANE_HEIGHT;

  const selectDrawingTool = (tool: ChartDrawingTool) => {
    pendingDrawingRef.current = null;
    activeToolRef.current = tool;
    setActiveTool(tool);
  };

  const clearDrawings = () => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (chart && candleSeries) {
      for (const artifact of drawingArtifactsRef.current) {
        try {
          if (artifact.kind === "priceLine") {
            candleSeries.removePriceLine(artifact.line);
          } else {
            chart.removeSeries(artifact.series);
          }
        } catch (error) {
          console.debug("[chart] drawing removal failed:", error);
        }
      }
    }
    drawingArtifactsRef.current = [];
    drawingsRef.current = [];
    pendingDrawingRef.current = null;
    activeToolRef.current = "cursor";
    setDrawings([]);
    setActiveTool("cursor");
  };

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || activeToolRef.current === "cursor") return;
      pendingDrawingRef.current = null;
      activeToolRef.current = "cursor";
      setActiveTool("cursor");
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, []);

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
          separatorHoverColor: "rgba(194, 163, 107, 0.25)",
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
          labelBackgroundColor: COLORS.border,
        },
        horzLine: {
          color: COLORS.border,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: COLORS.border,
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

    drawingArtifactsRef.current = drawingsRef.current.flatMap((drawing) =>
      renderDrawing(chart, candleSeries, drawing)
    );

    const finishDrawing = () => {
      pendingDrawingRef.current = null;
      activeToolRef.current = "cursor";
      setActiveTool("cursor");
    };

    const commitDrawing = (drawing: ChartDrawing) => {
      const nextDrawings = [...drawingsRef.current, drawing];
      drawingsRef.current = nextDrawings;
      setDrawings(nextDrawings);
      drawingArtifactsRef.current.push(...renderDrawing(chart, candleSeries, drawing));
    };

    const handleChartClick = (param: MouseEventParams<Time>) => {
      const tool = activeToolRef.current;
      if (
        tool === "cursor" ||
        param.paneIndex !== 0 ||
        param.time == null ||
        param.point == null
      ) {
        return;
      }

      const price = candleSeries.coordinateToPrice(param.point.y);
      if (price == null) return;
      const point: DrawingPoint = { time: param.time, value: Number(price) };

      if (tool === "horizontal") {
        commitDrawing({ kind: "horizontal", price: point.value });
        finishDrawing();
        return;
      }

      const start = pendingDrawingRef.current;
      if (!start) {
        pendingDrawingRef.current = point;
        return;
      }

      if (tool === "trend" && timeKey(start.time) === timeKey(point.time)) {
        return;
      }

      commitDrawing({ kind: tool, start, end: point });
      finishDrawing();
    };
    chart.subscribeClick(handleChartClick);

    const candleTimes = candleData.map((c) => c.time as number);

    // ── EMA overlay lines (pane 0) ──────────────────────────────────
    if (vis?.ema && emas) {
      for (const [periodKey, values] of Object.entries(emas)) {
        if (!Array.isArray(values) || values.length === 0) continue;
        const color = EMA_COLORS[periodKey] ?? COLORS.textColor;
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
            ? `rgba(108, 169, 143, ${0.15 + 0.5 * (totalVol / maxVol)})`
            : `rgba(201, 106, 85, ${0.15 + 0.5 * (totalVol / maxVol)})`,
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
              ? `rgba(108, 169, 143, ${0.3 + 0.4 * (v / maxVol)})`
              : `rgba(201, 106, 85, ${0.3 + 0.4 * (v / maxVol)})`,
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
    if (vis.volume && volData.length > 0) {
      const volumePaneIdx = nextPane++;
      try {
        const volSeries = chart.addSeries(
          HistogramSeries,
          {
            priceFormat: { type: "volume" },
            priceScaleId: "vol",
          },
          volumePaneIdx
        );
        volSeries.setData(volData);
        volSeries.priceScale().applyOptions({
          visible: false,
          scaleMargins: { top: 0.7, bottom: 0 },
        });
      } catch (error) {
        console.debug("[chart] volume pane setup failed:", error);
      }
    }

    // ── RSI sub-pane ─────────────────────────────────────────────────
    if (vis.rsi && indicatorData?.rsi && indicatorData.rsi.length > 0) {
      const rsiPaneIdx = nextPane++;
      try {
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
          color: "rgba(201, 106, 85, 0.4)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          lineVisible: true,
          axisLabelVisible: true,
          title: "OB 70",
        });
        rsiSeries.createPriceLine({
          price: 30,
          color: "rgba(108, 169, 143, 0.4)",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          lineVisible: true,
          axisLabelVisible: true,
          title: "OS 30",
        });
        rsiSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.1, bottom: 0.1 },
          autoScale: false,
        });
      } catch (error) {
        console.debug("[chart] RSI pane setup failed:", error);
      }
    }

    // ── MACD sub-pane ────────────────────────────────────────────────
    if (vis.macd && indicatorData?.macd) {
      const macdPaneIdx = nextPane++;
      try {
        const { macd, signal, histogram } = indicatorData.macd;

        if (histogram.length > 0) {
          const histData: HistogramData[] = histogram.map((p) => ({
            time: p.time,
            value: p.value,
            color: p.value >= 0 ? MACD_HIST_UP : MACD_HIST_DOWN,
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
      } catch (error) {
        console.debug("[chart] MACD pane setup failed:", error);
      }
    }

    // ── Order block zones (price lines on candle series) ─────────────
    if (vis?.orderBlocks && orderBlocks && orderBlocks.length > 0) {
      for (const ob of orderBlocks) {
        if (ob.price_high == null && ob.price_low == null) continue;
        const isBull = (ob.type ?? "bullish").toLowerCase() !== "bearish";
        const color = isBull
          ? "rgba(108, 169, 143, 0.5)"
          : "rgba(201, 106, 85, 0.5)";
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
            color: COLORS.bearish,
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
              color: COLORS.bullish,
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
      chart.unsubscribeClick(handleChartClick);
      priceLinesRef.current = [];
      drawingArtifactsRef.current = [];
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
      <div className="flex h-48 w-full items-center justify-center border border-[#2A2620] bg-[#0F0E0C] text-sm text-[#8E8778]">
        No candle data available for chart rendering.
      </div>
    );
  }

  return (
    <div className="w-full">
      <ChartDrawingToolbar
        activeTool={activeTool}
        onToolChange={selectDrawingTool}
        onClear={clearDrawings}
        hasDrawings={drawings.length > 0}
      />
      <div
        ref={containerRef}
        className="w-full border border-[#2A2620] bg-[#0F0E0C]"
        style={{
          minHeight: chartHeight,
          cursor: activeTool === "cursor" ? undefined : "crosshair",
        }}
      />
    </div>
  );
}

export default CandlestickChart;
