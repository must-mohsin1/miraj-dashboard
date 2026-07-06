import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { MacroResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * MacroStrip — async Server Component.
 *
 * A compact, single-row horizontal strip showing the five most
 * tradable macro signals: BTC.D, USDT.D, Fear & Greed, DXY, and the
 * Binance Long/Short ratio.  Each metric renders as a small badge with
 * its value and an accent colour.  Intended to sit at the very top of
 * the analysis page so a trader sees the broader market context before
 * diving into a per-symbol scan.
 *
 * Data is pulled from `GET /api/v1/macro` (15-min server cache).  When
 * the backend is unreachable or the user is unauthenticated, the strip
 * renders a slim "macro unavailable" placeholder rather than throwing.
 */

/** Format a percentage value with 2 decimals (no sign). */
function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/** Format a ratio with 3 decimals. */
function fmtRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

/** Format the DXY value with 2 decimals. */
function fmtDxy(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

/**
 * Accent colour for a Fear & Greed value.  Low (fear) → red/orange;
 * high (greed) → emerald.  Mirrors the MacroCards colouring.
 */
function fearGreedAccent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-200";
  }
  if (value <= 24) return "text-red-400";
  if (value <= 44) return "text-orange-400";
  if (value <= 55) return "text-slate-200";
  if (value <= 74) return "text-emerald-400";
  return "text-emerald-300";
}

/**
 * Accent for DXY: a strong dollar (>= 100) is bearish for crypto → red;
 * a weak dollar (< 100) is bullish → green.
 */
function dxyAccent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-200";
  }
  if (value >= 100) return "text-red-400";
  return "text-emerald-400";
}

/** Accent for the Binance L/S ratio: > 1 = longs dominating, < 1 = shorts. */
function lsAccent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-200";
  }
  if (value > 1.5) return "text-amber-400"; // crowded long
  if (value > 1) return "text-emerald-400"; // mild long bias
  if (value < 0.7) return "text-red-400"; // crowded short
  return "text-slate-200";
}

/** Accent for BTC.D / USDT.D dominance — neutral slate, these are context. */
function dominanceAccent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-200";
  }
  return "text-slate-100";
}

interface MacroStripProps {
  /** Optional pre-fetched macro data; otherwise fetches server-side. */
  data?: MacroResponse | null;
}

export async function MacroStrip({ data: preloaded }: MacroStripProps) {
  let macro: MacroResponse | null = preloaded ?? null;

  if (!macro) {
    const token = await getAccessToken();
    if (token) {
      try {
        macro = await serverFetch<MacroResponse>("/api/v1/macro", token);
      } catch {
        // Swallow — render a graceful fallback.
        macro = null;
      }
    }
  }

  const d = macro?.data;

  // No data at all → slim placeholder so the page still loads.
  if (!d) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-500">
        <span className="font-medium uppercase tracking-wide">Macro</span>
        <span>unavailable</span>
      </div>
    );
  }

  const btcD = d.btc_dominance;
  const usdtD = d.usdt_dominance;
  const fg = d.fear_greed_index;
  const dxy = d.dxy;
  const ls = d.binance_ls_ratio;

  const Badge = ({
    label,
    value,
    accent,
    title,
  }: {
    label: string;
    value: string;
    accent: string;
    title?: string;
  }) => (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-md border border-slate-800 bg-slate-900/80 px-2 py-1",
      )}
      title={title}
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <span className={cn("text-xs font-semibold tabular-nums", accent)}>
        {value}
      </span>
    </div>
  );

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
        Macro
      </span>
      <Badge
        label="BTC.D"
        value={fmtPct(btcD)}
        accent={dominanceAccent(btcD)}
        title="Bitcoin dominance (share of total crypto market cap)"
      />
      <Badge
        label="USDT.D"
        value={fmtPct(usdtD)}
        accent={dominanceAccent(usdtD)}
        title="Tether dominance (rising USDT.D = risk-off)"
      />
      <Badge
        label="F&G"
        value={fg != null ? String(fg) : "—"}
        accent={fearGreedAccent(fg)}
        title="Fear & Greed Index (0 = extreme fear, 100 = extreme greed)"
      />
      <Badge
        label="DXY"
        value={fmtDxy(dxy)}
        accent={dxyAccent(dxy)}
        title="US Dollar Index (strong dollar = bearish for crypto)"
      />
      <Badge
        label="L/S"
        value={fmtRatio(ls)}
        accent={lsAccent(ls)}
        title="Binance global long/short account ratio (BTCUSDT, 5m)"
      />
    </div>
  );
}

export default MacroStrip;
