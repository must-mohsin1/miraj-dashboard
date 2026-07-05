import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { MacroData } from "@/lib/types";

/**
 * MacroCards — Server Component.
 *
 * Renders the four headline macro indicators in a responsive grid:
 * BTC Dominance, USDT Dominance, Fear & Greed Index, and the Binance
 * Long/Short ratio. Each card shows a title, a big value, and a short
 * subtitle. Colours follow the app's dark slate theme.
 *
 * When a value is unavailable (the upstream source failed) the card
 * renders an em-dash placeholder rather than blank space, and dims the
 * subtitle so the grid stays visually balanced.
 */

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

/** Format the DXY (Dollar Index) value with 2 decimals, no percent sign. */
function formatDxy(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

/**
 * DXY is inversely correlated with crypto risk assets: a strong dollar
 * (DXY >= 100) is bearish for crypto → red; a weak dollar (< 100) is
 * bullish → green. This threshold aligns with the regime heuristic the
 * backend uses in `macro_service.compute_regime`. The absolute level is a
 * proxy for direction since the cache stores only the latest point value.
 */
function dxyColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-200";
  }
  if (value >= 100) return "text-red-400"; // strong dollar → bearish for crypto
  return "text-emerald-400"; // weak dollar → bullish for crypto
}

/**
 * Pick a Fear & Greed label. The backend already returns a classification
 * (`fear_greed_label`), but it may be missing/expired — fall back to a
 * numeric band so the card is never left without context.
 */
function fearGreedLabel(
  value: number | null | undefined,
  backendLabel: string | null | undefined
): string {
  if (backendLabel) return backendLabel;
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value <= 24) return "Extreme Fear";
  if (value <= 44) return "Fear";
  if (value <= 55) return "Neutral";
  if (value <= 74) return "Greed";
  return "Extreme Greed";
}

/** Map a Fear & Greed label to an accent colour used for the big value. */
function fearGreedColor(label: string): string {
  switch (label) {
    case "Extreme Fear":
      return "text-red-400";
    case "Fear":
      return "text-orange-400";
    case "Neutral":
      return "text-slate-200";
    case "Greed":
      return "text-emerald-400";
    case "Extreme Greed":
      return "text-emerald-300";
    default:
      return "text-slate-200";
  }
}

interface MacroCardsProps {
  /** Macro data block from the API; pass `null` to render an empty/placeholder grid. */
  data: MacroData | null;
}

export function MacroCards({ data }: MacroCardsProps) {
  const d = data ?? ({} as Partial<MacroData>);

  const btcDominance = d.btc_dominance ?? null;
  const usdtDominance = d.usdt_dominance ?? null;
  const fearGreedIndex = d.fear_greed_index ?? null;
  const fearLabel = fearGreedLabel(fearGreedIndex, d.fear_greed_label);
  const longShortRatio = d.binance_ls_ratio ?? null;
  const dxy = d.dxy ?? null;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {/* BTC Dominance */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            BTC Dominance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold text-slate-100">
            {formatPercent(btcDominance)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Bitcoin share of total market cap
          </p>
        </CardContent>
      </Card>

      {/* USDT Dominance */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            USDT Dominance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold text-slate-100">
            {formatPercent(usdtDominance)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Tether share of total market cap
          </p>
        </CardContent>
      </Card>

      {/* Fear & Greed Index */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            Fear &amp; Greed Index
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div
            className={cn(
              "text-3xl font-bold",
              fearGreedColor(fearLabel)
            )}
          >
            {fearGreedIndex === null || fearGreedIndex === undefined
              ? "—"
              : fearGreedIndex}
          </div>
          <p className="mt-1 text-xs text-slate-500">{fearLabel}</p>
        </CardContent>
      </Card>

      {/* Long/Short Ratio */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            Long / Short Ratio
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold text-slate-100">
            {formatRatio(longShortRatio)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Binance global long/short (BTCUSDT)
          </p>
        </CardContent>
      </Card>

      {/* DXY (Dollar Index) */}
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            DXY (Dollar Index)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className={cn("text-3xl font-bold", dxyColor(dxy))}>
            {formatDxy(dxy)}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Rising DXY = bearish for crypto, falling = bullish
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default MacroCards;
