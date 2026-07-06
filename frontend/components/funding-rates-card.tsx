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
 * paying whom in the perpetual swaps market:
 *
 *  - **Negative** rate → shorts pay longs → **bullish** (longs are being
 *    paid to hold), rendered in emerald.
 *  - **Moderate positive** (0–0.05 %/8h) → neutral / normal carry,
 *    rendered in slate.
 *  - **High positive** (> 0.05 %/8h) → longs are paying heavily to hold
 *    → overheated / crowded long, rendered in red/orange.
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

/** Colour class for a given funding-rate percentage (per 8h). */
function fundingColor(percent: number): string {
  if (percent < 0) return "text-emerald-400"; // negative = bullish
  if (percent > 0.05) return "text-red-400"; // high positive = overheated
  return "text-slate-200"; // neutral
}

/** Short qualitative signal label for a funding rate. */
function fundingSignal(percent: number): string {
  if (percent < -0.01) return "Shorts pay longs — bullish";
  if (percent > 0.05) return "High funding — long squeeze risk";
  if (percent > 0.01) return "Longs pay shorts — overheated";
  if (percent < 0) return "Shorts pay longs — bullish";
  return "Neutral";
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
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "text-sm font-semibold tabular-nums",
                        fundingColor(pct),
                      )}
                    >
                      {formatPercent(pct)}
                    </span>
                    <span className="text-xs text-slate-500">
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
