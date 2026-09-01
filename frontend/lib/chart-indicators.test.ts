import { buildIndicatorData, computeBollinger, computeRsi } from "./chart-indicators";
import type { Candle } from "@/lib/types";

function candlesFromCloses(closes: number[]): Candle[] {
  return closes.map((close, i) => ({
    time: 1_700_000_000 + i * 86400,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 100,
  }));
}

describe("chart indicators", () => {
  it("computes RSI in 0–100 after the warmup window", () => {
    const closes = Array.from({ length: 40 }, (_, i) => 100 + i);
    const rsi = computeRsi(closes);
    const last = rsi[rsi.length - 1];
    expect(last).not.toBeNull();
    expect(last as number).toBeGreaterThan(50);
    expect(last as number).toBeLessThanOrEqual(100);
  });

  it("uses scan rsi only when the series length matches the candles", () => {
    const bars = candlesFromCloses([10, 11, 12, 13, 14]);
    const matched = buildIndicatorData(bars, { rsi: [40, 50, 60, 70, 80] });
    expect(matched.rsi).toHaveLength(5);
    expect(matched.rsi?.[0]?.value).toBe(40);
    expect(matched.rsi?.[4]?.value).toBe(80);

    const mismatched = buildIndicatorData(bars, { rsi: [40, 50, 60] });
    expect(mismatched.rsi?.some((point) => point.value === 60)).toBe(false);
  });

  it("recomputes MACD and BB when any scan sub-series length differs", () => {
    const bars = candlesFromCloses(
      Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 4)
    );
    const sentinels = new Array(60).fill(999);
    const data = buildIndicatorData(
      bars,
      {
        macd: {
          macd: sentinels,
          signal: [999],
          histogram: sentinels,
        },
        bb: {
          upper: [999],
          middle: sentinels,
          lower: sentinels,
        },
      },
      { preferScan: true }
    );

    expect(data.macd?.macd).toHaveLength(35);
    expect(data.bb?.middle).toHaveLength(41);
    expect(data.macd?.macd.some((point) => point.value === 999)).toBe(false);
    expect(data.bb?.middle.some((point) => point.value === 999)).toBe(false);
  });

  it("computes MACD and BB from candles when scan series are missing", () => {
    const bars = candlesFromCloses(
      Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 4)
    );
    const data = buildIndicatorData(bars, null, { preferScan: false });
    expect((data.rsi?.length ?? 0) > 10).toBe(true);
    expect((data.macd?.macd.length ?? 0) > 10).toBe(true);
    expect((data.bb?.middle.length ?? 0) > 10).toBe(true);
  });

  it("centers Bollinger bands on SMA, not EMA", () => {
    const closes = Array.from({ length: 25 }, (_, i) => i + 1);
    const bb = computeBollinger(closes, 20, 2);
    const last20 = closes.slice(-20);
    const sma20 = last20.reduce((a, b) => a + b, 0) / 20;
    expect(bb.middle[24]).toBeCloseTo(sma20, 8);
  });
});
