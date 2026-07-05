import {
  ArrowDownRight,
  ArrowUpRight,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * CMEGapsCard — Server Component.
 *
 * Lists unfilled CME futures gaps on BTC (``BTC=F``) weekly candles from
 * the last ~3 months.  CME futures close Friday ~17:00 ET and reopen
 * Sunday ~18:00 ET; the weekend break frequently produces an open ≠
 * previous close, and these gaps tend to get revisited ("filled") by
 * later price action.
 *
 * Colour rule:
 *  - **Up gap** (opened higher than Friday's close) → green badge.
 *  - **Down gap** (opened lower than Friday's close) → red badge.
 *
 * Only unfilled gaps are shown (the actionable set). When the upstream
 * source failed or there are no gaps, a fallback message is rendered so
 * the card layout stays stable.
 */

/** A single CME gap entry, mirroring the backend response shape. */
interface CMEGapEntry {
  date: string;
  gap_percent: number;
  direction: string;
  filled: boolean;
}

interface CMEGapsCardProps {
  /** Unfilled CME gaps from the API. `null`/empty renders a fallback. */
  gaps?: CMEGapEntry[] | null;
}

export function CMEGapsCard({ gaps }: CMEGapsCardProps) {
  const hasData = Array.isArray(gaps) && gaps.length > 0;

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium text-slate-400">
            CME Gaps
          </CardTitle>
          <span
            className="cursor-help text-xs text-slate-600"
            title="CME futures weekend gaps tend to get filled. Shown: unfilled gaps from the last 3 months."
          >
            ⓘ
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {hasData ? (
          <ul className="divide-y divide-slate-800">
            {gaps!.map((gap) => {
              const isUp = gap.direction === "up";
              return (
                <li
                  key={gap.date}
                  className="flex items-center justify-between py-2"
                >
                  <div className="flex items-center gap-2">
                    {isUp ? (
                      <ArrowUpRight className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <ArrowDownRight className="h-4 w-4 text-red-400" />
                    )}
                    <span className="text-sm font-medium text-slate-300">
                      {gap.date}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                        isUp
                          ? "bg-emerald-500/10 text-emerald-400"
                          : "bg-red-500/10 text-red-400",
                      )}
                    >
                      {isUp ? "+" : "−"}
                      {Math.abs(gap.gap_percent).toFixed(2)}%
                    </span>
                    <span className="text-xs text-slate-600">
                      {isUp ? "Up" : "Down"}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="py-4 text-center text-sm text-slate-500">
            No unfilled CME gaps
            <p className="mt-1 text-xs text-slate-600">
              Last 3 months of BTC=F weekly candles
            </p>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-600">
          CME gaps tend to get filled
        </p>
      </CardContent>
    </Card>
  );
}

export default CMEGapsCard;
