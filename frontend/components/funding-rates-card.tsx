import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * FundingRatesCard — Server Component.
 *
 * Displays the latest per-8h funding rate for BTC, ETH, and SOL, sourced
 * from Binance Futures ``premiumIndex``.  Funding rates indicate who is
 * paying whom in the perpetual swaps market.  A four-tier interpretation
 * label + accent colour is rendered *below* each rate value:
 *
 *  - ``< -0.01 %``  → "Shorts paying longs — bullish"      (emerald)
 *  - ``-0.01 … +0.01 %`` → "Neutral"                       (slate/gray)
 *  - ``> +0.01 %`` → "Longs paying shorts — overheated"   (amber)
 *  - ``> +0.05 %`` → "High funding — potential long squeeze" (red)
 *
 * Degrades gracefully: when the upstream source failed, an em-dash
 * placeholder row is shown so the card layout stays stable.
 */

/** Funding rate entry, mirroring the backend `funding_rate_percent` field. */
interface FundingRateEntry {
  symbol: string;
  funding_rate: number;
  funding_rate_percent: number;
}

interface FundingRatesCardProps {
  /** Funding-rate list from the API. `null`/empty renders a fallback. */
  rates?: FundingRateEntry[] | null;
}

/**
 * Accent colour for the funding-rate *value*, following the four-tier
 * scheme.  Order matters: the > 0.05 % (red) check must come before the
 * > 0.01 % (amber) check, and the < -0.01 % (emerald) check before the
 * neutral fallback.
 */
function fundingColor(percent: number): string {
  if (percent > 0.05) return "text-red-400"; // high funding — long squeeze
  if (percent > 0.01) return "text-amber-400"; // overheated longs
  if (percent < -0.01) return "text-emerald-400"; // shorts paying longs — bullish
  return "text-slate-200"; // neutral
}

/**
 * Interpretation label shown *below* each funding rate value.  Wording
 * and thresholds match the spec exactly.
 */
function fundingSignal(percent: number): string {
  if (percent > 0.05) return "High funding — potential long squeeze";
  if (percent > 0.01) return "Longs paying shorts — overheated";
  if (percent < -0.01) return "Shorts paying longs — bullish";
  return "Neutral";
}

/** Accent colour for the interpretation label (slightly dimmer than the value). */
function fundingLabelColor(percent: number): string {
  if (percent > 0.05) return "text-red-400";
  if (percent > 0.01) return "text-amber-400";
  if (percent < -0.01) return "text-emerald-400";
  return "text-slate-400";
}

function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}%`;
}

export function FundingRatesCard({ rates }: FundingRatesCardProps) {
  const hasData = Array.isArray(rates) && rates.length > 0;

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            Funding Rates
          </CardTitle>
          <span
            className="cursor-help text-xs text-slate-600"
            title="Negative = shorts paying longs (bullish). High positive = overheated longs. Rates are per 8h on Binance Futures."
          >
            ⓘ
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ul className="divide-y divide-slate-800">
            {rates!.map((entry) => {
              const pct = entry.funding_rate_percent;
              return (
                <li
                  key={entry.symbol}
                  className="flex items-center justify-between py-2"
                >
                  <span className="text-sm font-medium text-slate-300">
                    {entry.symbol}
                  </span>
                  <div className="flex flex-col items-end gap-0.5">
                    <span
                      className={cn(
                        "text-sm font-semibold tabular-nums",
                        fundingColor(pct),
                      )}
                    >
                      {formatPercent(pct)}
                    </span>
                    <span
                      className={cn(
                        "text-[11px] font-medium",
                        fundingLabelColor(pct),
                      )}
                    >
                      {fundingSignal(pct)}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="py-4 text-center text-sm text-slate-500">
            —
            <p className="mt-1 text-xs text-slate-600">
              Funding rates unavailable
            </p>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-600">
          Negative = shorts paying longs (bullish)
        </p>
      </CardContent>
    </Card>
  );
}

export default FundingRatesCard;
