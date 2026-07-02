import { ArrowDown, ArrowUp, Crosshair, Target, TrendingDown } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { TradePlanFlat } from "@/lib/types";

/**
 * TradePlan — Server Component.
 *
 * Renders the entry / stop-loss / take-profit levels for a single scan in a
 * clean card layout with computed risk-to-reward ratios. The backend returns
 * a flat trade-plan object (`trade_plan_flat`) whose keys we read here; the
 * component degrades gracefully when any level is missing.
 *
 * R:R is calculated as `|target − entry| / |entry − stop|` and shown as
 * `1:x.x`. When the stop or entry is null the ratio shows "—".
 */

/** Format a price (USD) for display. Large values get thousands separators. */
function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1000) {
    return `$${value.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  return `$${value.toFixed(2)}`;
}

/** Calculate the risk:reward ratio for a single target. */
function riskReward(
  entry: number | null,
  stop: number | null,
  target: number | null,
  direction: string
): string {
  if (entry == null || stop == null || target == null) return "—";
  const risk = Math.abs(entry - stop);
  if (risk < 1e-6) return "—";
  const isLong = direction.toUpperCase() === "LONG";
  const reward = isLong ? Math.abs(target - entry) : Math.abs(entry - target);
  const ratio = reward / risk;
  if (!Number.isFinite(ratio)) return "—";
  return `1:${ratio.toFixed(2)}`;
}

/** Percentage distance from entry to a level (signed). */
function pctFromEntry(
  entry: number | null,
  level: number | null,
  direction: string
): string {
  if (entry == null || level == null || entry === 0) return "";
  const isLong = direction.toUpperCase() === "LONG";
  const diff = isLong ? level - entry : entry - level;
  const pct = (diff / entry) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

interface TradePlanProps {
  /** The flat trade-plan object from the scan response. Pass `null` to show a placeholder. */
  tradePlan: TradePlanFlat | null;
}

export function TradePlan({ tradePlan }: TradePlanProps) {
  if (!tradePlan || tradePlan.entry == null) {
    return (
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-slate-400">
            Trade Plan
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-500">
            No trade plan available for this analysis.
          </p>
        </CardContent>
      </Card>
    );
  }

  const direction = tradePlan.direction?.toUpperCase() ?? "LONG";
  const isLong = direction === "LONG";
  const entry = tradePlan.entry;
  const stop = tradePlan.stop_loss;
  const targets = [tradePlan.target_1, tradePlan.target_2, tradePlan.target_3].filter(
    (t): t is number => t != null && !Number.isNaN(t)
  );

  const dirIcon = isLong ? (
    <ArrowUp className="h-4 w-4 text-emerald-400" />
  ) : (
    <ArrowDown className="h-4 w-4 text-red-400" />
  );
  const dirColor = isLong
    ? "bg-emerald-500/10 text-emerald-400 border-emerald-700/50"
    : direction === "SHORT"
    ? "bg-red-500/10 text-red-400 border-red-700/50"
    : "bg-slate-500/10 text-slate-400 border-slate-700/50";

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-slate-400">
            Trade Plan
          </CardTitle>
          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${dirColor}`}
          >
            {dirIcon}
            {direction}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Entry */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Crosshair className="h-4 w-4 text-slate-500" />
            <span className="text-sm text-slate-400">Entry</span>
          </div>
          <div className="text-right">
            <div className="text-lg font-semibold text-slate-100">
              {formatPrice(entry)}
            </div>
          </div>
        </div>

        {/* Stop Loss */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-red-400" />
            <span className="text-sm text-slate-400">Stop Loss</span>
          </div>
          <div className="text-right">
            <div className="text-lg font-semibold text-red-400">
              {formatPrice(stop)}
            </div>
            {stop != null && entry != null && (
              <div className="text-xs text-slate-500">
                {pctFromEntry(entry, stop, direction)}
              </div>
            )}
          </div>
        </div>

        {/* Targets */}
        {targets.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 pb-1">
              <Target className="h-4 w-4 text-emerald-400" />
              <span className="text-sm text-slate-400">Take Profit Targets</span>
            </div>
            {targets.map((t, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2"
              >
                <span className="text-sm font-medium text-slate-300">
                  T{i + 1}
                </span>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-slate-500">
                    {pctFromEntry(entry, t, direction)}
                  </span>
                  <span className="text-sm font-semibold text-emerald-400">
                    {riskReward(entry, stop, t, direction)}
                  </span>
                  <span className="text-base font-semibold text-slate-100 tabular-nums">
                    {formatPrice(t)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">No take-profit targets.</p>
        )}

        {/* Rationale */}
        {tradePlan.rationale && (
          <div className="border-t border-slate-800 pt-3">
            <p className="text-xs text-slate-500">Rationale</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">
              {tradePlan.rationale}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default TradePlan;
