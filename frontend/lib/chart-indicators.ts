import type {
  Candle,
  EmaData,
  MacdData,
  BollingerBandsData,
  IndicatorSeries,
  TimeValuePoint,
} from "@/lib/types";

function candleTime(c: Candle): number {
  if (typeof c.time === "number") {
    return c.time > 1e12 ? Math.floor(c.time / 1000) : Math.floor(c.time);
  }
  const ms = Date.parse(String(c.time));
  if (Number.isNaN(ms)) return 0;
  return Math.floor(ms / 1000);
}

function ema(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length < period || period < 1) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  seed /= period;
  out[period - 1] = seed;
  for (let i = period; i < values.length; i++) {
    seed = values[i] * k + (seed as number) * (1 - k);
    out[i] = seed;
  }
  return out;
}

function sma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length < period || period < 1) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function stdev(window: number[]): number {
  const mean = window.reduce((a, b) => a + b, 0) / window.length;
  const varSum = window.reduce((a, b) => a + (b - mean) ** 2, 0) / window.length;
  return Math.sqrt(varSum);
}

/** Wilder RSI(14) aligned to `closes`. Leading nulls until the first full window. */
export function computeRsi(closes: number[], period = 14): Array<number | null> {
  const out: Array<number | null> = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gain += diff;
    else loss -= diff;
  }
  gain /= period;
  loss /= period;
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const g = diff > 0 ? diff : 0;
    const l = diff < 0 ? -diff : 0;
    gain = (gain * (period - 1) + g) / period;
    loss = (loss * (period - 1) + l) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export function computeMacd(
  closes: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9
): { macd: Array<number | null>; signal: Array<number | null>; histogram: Array<number | null> } {
  const fastE = ema(closes, fast);
  const slowE = ema(closes, slow);
  const macdLine: Array<number | null> = closes.map((_, i) => {
    if (fastE[i] == null || slowE[i] == null) return null;
    return (fastE[i] as number) - (slowE[i] as number);
  });
  const macdNumeric = macdLine.map((v) => v ?? 0);
  const firstValid = macdLine.findIndex((v) => v != null);
  const signal = ema(
    firstValid >= 0 ? macdNumeric.slice(firstValid) : [],
    signalPeriod
  );
  const signalAligned: Array<number | null> = new Array(closes.length).fill(null);
  for (let i = 0; i < signal.length; i++) {
    signalAligned[firstValid + i] = signal[i];
  }
  const histogram = macdLine.map((v, i) =>
    v == null || signalAligned[i] == null ? null : v - (signalAligned[i] as number)
  );
  return { macd: macdLine, signal: signalAligned, histogram };
}

export function computeBollinger(
  closes: number[],
  period = 20,
  mult = 2
): { upper: Array<number | null>; middle: Array<number | null>; lower: Array<number | null> } {
  const middle = sma(closes, period);
  const upper: Array<number | null> = new Array(closes.length).fill(null);
  const lower: Array<number | null> = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const window = closes.slice(i - period + 1, i + 1);
    const sd = stdev(window);
    const mid = middle[i];
    if (mid == null) continue;
    upper[i] = mid + mult * sd;
    lower[i] = mid - mult * sd;
  }
  return { upper, middle, lower };
}

export function computeEmas(closes: number[]): EmaData {
  const periods = [9, 20, 21, 50, 200];
  const data: EmaData = {};
  for (const p of periods) {
    data[`ema_${p}`] = ema(closes, p).map((v) => v ?? Number.NaN);
  }
  return data;
}

function seriesFrom(
  times: number[],
  values: Array<number | null | undefined>
): TimeValuePoint[] {
  const out: TimeValuePoint[] = [];
  const offset = times.length - values.length;
  for (let i = 0; i < values.length; i++) {
    const idx = offset + i;
    if (idx < 0 || idx >= times.length) continue;
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    if (times[idx] === 0) continue;
    out.push({ time: times[idx] as TimeValuePoint["time"], value: v });
  }
  return out;
}

/** Align scan `number[]` series (or compute from candles) into chart `IndicatorData`. */
export function buildIndicatorData(
  candles: Candle[],
  scan?: {
    rsi?: number[] | null;
    macd?: MacdData | null;
    bb?: BollingerBandsData | null;
  } | null,
  options?: { preferScan?: boolean }
): IndicatorSeries {
  const times = candles.map(candleTime);
  const closes = candles.map((c) => c.close);
  const preferScan = options?.preferScan ?? true;
  const scanFits = (values: Array<number | null | undefined> | null | undefined) =>
    Boolean(preferScan && values && values.length === closes.length);

  const rsiValues = scanFits(scan?.rsi) ? scan!.rsi! : computeRsi(closes);
  const macdFits =
    scanFits(scan?.macd?.macd) &&
    scanFits(scan?.macd?.signal) &&
    scanFits(scan?.macd?.histogram);
  const macdValues = macdFits
    ? {
        macd: scan!.macd!.macd,
        signal: scan!.macd!.signal,
        histogram: scan!.macd!.histogram,
      }
    : computeMacd(closes);
  const bbFits =
    scanFits(scan?.bb?.upper) &&
    scanFits(scan?.bb?.middle) &&
    scanFits(scan?.bb?.lower);
  const bbValues = bbFits ? scan!.bb! : computeBollinger(closes);

  return {
    rsi: seriesFrom(times, rsiValues),
    macd: {
      macd: seriesFrom(times, macdValues.macd),
      signal: seriesFrom(times, macdValues.signal),
      histogram: seriesFrom(times, macdValues.histogram),
    },
    bb: {
      upper: seriesFrom(times, bbValues.upper),
      middle: seriesFrom(times, bbValues.middle),
      lower: seriesFrom(times, bbValues.lower),
    },
  };
}

export function buildEmaOverlay(candles: Candle[]): EmaData {
  return computeEmas(candles.map((c) => c.close));
}

export { candleTime };
