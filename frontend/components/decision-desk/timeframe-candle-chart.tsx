"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineStyle,
  createChart,
  type CandlestickData,
  type UTCTimestamp,
} from "lightweight-charts";

import type { CollectorCandle, CollectorLevelRange } from "@/lib/collector-report-types";

const COLORS = {
  background: "#161411",
  border: "#2A2620",
  text: "#8E8778",
  up: "#6CA98F",
  down: "#C96A55",
  fvg: "#D19A4A",
  ote: "#C2A36B",
};

function price(value: number) {
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function range(label: string, value?: CollectorLevelRange | null) {
  return value ? `${label} ${price(value.low)}–${price(value.high)}` : null;
}

function completedCandles(candles: CollectorCandle[]): CandlestickData[] {
  const deduplicated = new Map<number, CandlestickData>();
  for (const candle of candles) {
    const timestamp = Date.parse(candle.time);
    if (!Number.isFinite(timestamp)) continue;
    deduplicated.set(Math.floor(timestamp / 1000), {
      time: Math.floor(timestamp / 1000) as UTCTimestamp,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    });
  }
  return [...deduplicated.entries()].sort(([a], [b]) => a - b).map(([, candle]) => candle);
}

function addRangeOverlay(series: ReturnType<typeof createChart>["addSeries"] extends (...args: never[]) => infer Result ? Result : never, label: string, value: CollectorLevelRange, color: string) {
  for (const [edge, level] of [["low", value.low], ["high", value.high]] as const) {
    series.createPriceLine({ color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `${label} ${edge}`, price: level });
  }
}

export function TimeframeCandleChart({ timeframe, candles, fvg, ote }: { timeframe: string; candles: CollectorCandle[]; fvg?: CollectorLevelRange | null; ote?: CollectorLevelRange | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const data = completedCandles(candles);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || data.length === 0) return;

    const chart = createChart(container, {
      autoSize: true,
      height: 280,
      layout: { background: { type: ColorType.Solid, color: COLORS.background }, textColor: COLORS.text, fontFamily: "var(--font-mono)" },
      grid: { vertLines: { color: COLORS.border }, horzLines: { color: COLORS.border } },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: { borderColor: COLORS.border, timeVisible: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderUpColor: COLORS.up,
      borderDownColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
    });
    series.setData(data);
    if (fvg) addRangeOverlay(series, "FVG", fvg, COLORS.fvg);
    if (ote) addRangeOverlay(series, "OTE", ote, COLORS.ote);
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [data, fvg, ote]);

  if (data.length === 0) {
    return <p className="mt-4 border-y border-slate-800 py-4 text-sm text-slate-500">No completed candle evidence was supplied for {timeframe}.</p>;
  }

  return <div className="mt-4 border border-slate-800 bg-slate-900" role="img" aria-label={`${timeframe} completed candle chart`}><div ref={containerRef} className="h-[280px] w-full" />{(fvg || ote) ? <div className="flex flex-wrap gap-x-4 border-t border-slate-800 px-3 py-2 font-mono text-[11px] text-slate-500">{range("FVG", fvg) ? <span>{range("FVG", fvg)}</span> : null}{range("OTE", ote) ? <span>{range("OTE", ote)}</span> : null}</div> : null}</div>;
}
