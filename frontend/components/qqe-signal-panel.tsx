import { Activity, HelpCircle } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { QqeSignals, QqeSignal } from "@/lib/types";

/**
 * QqeSignalPanel — Server Component.
 *
 * Renders the per-timeframe QQE Mod signal (Daily / 4H / 1H) as coloured
 * badges so a trader can see "daily GREEN STRONG, 4h GREEN, 1h RED" at a
 * glance without parsing the raw `qqe` dict.
 *
 * Colours follow the dark theme:
 *   - GREEN  → emerald
 *   - RED    → red
 *   - NEUTRAL → slate
 *
 * STRONG strength (volume-confirmed) renders with a bolder border + brighter
 * text to distinguish it from the NORMAL variant.
 */

/** Visual variant for a QQE trend. */
interface TrendVariant {
  /** Badge background + main text colour. */
  badge: string;
  /** Accent ring/border colour (emerald/red/slate). */
  ring: string;
  /** Large label colour. */
  label: string;
  /** Short human description. */
  blurb: string;
}

function trendVariant(trend: QqeSignal["trend"]): TrendVariant {
  switch (trend) {
    case "GREEN":
      return {
        badge: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
        ring: "border-emerald-600/60",
        label: "text-emerald-400",
        blurb: "Bullish momentum",
      };
    case "RED":
      return {
        badge: "bg-red-500/10 text-red-400 border-red-700/50",
        ring: "border-red-600/60",
        label: "text-red-400",
        blurb: "Bearish momentum",
      };
    default:
      return {
        badge: "bg-slate-500/10 text-slate-400 border-slate-700/50",
        ring: "border-slate-700/60",
        label: "text-slate-300",
        blurb: "No clear trend",
      };
  }
}

interface TimeframeRow {
  key: "daily" | "4h" | "1h";
  label: string;
}

const TIMEFRAMES: TimeframeRow[] = [
  { key: "daily", label: "Daily" },
  { key: "4h", label: "4H" },
  { key: "1h", label: "1H" },
];

interface QqeSignalPanelProps {
  /** Per-TF QQE signals. Pass `null` to show a placeholder. */
  signals: QqeSignals | null;
}

export function QqeSignalPanel({ signals }: QqeSignalPanelProps) {
  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-sm font-medium text-slate-300">
              QQE Signals
            </CardTitle>
          </div>
          <span
            className="group relative inline-flex cursor-help items-center"
            title="QQE Mod (Qualitative Quantitative Estimation)"
          >
            <HelpCircle className="h-3.5 w-3.5 text-slate-500" />
            <span className="pointer-events-none absolute right-0 top-6 z-10 hidden w-64 rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300 shadow-xl group-hover:block">
              QQE combines RSI smoothing with a dynamic trailing stop to
              identify trend direction. STRONG = volume-confirmed conviction
              (high buy-volume on green, low on red). Aligned signals across
              daily/4h/1h strengthen the confluence.
            </span>
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {TIMEFRAMES.map(({ key, label }) => {
            const sig = signals?.[key] ?? {
              trend: "NEUTRAL",
              strength: "NONE",
            };
            const variant = trendVariant(sig.trend);
            const isStrong = sig.strength === "STRONG";
            const isNormal = sig.strength === "NORMAL";

            return (
              <div
                key={key}
                className={cn(
                  "flex flex-col gap-2 rounded-lg border bg-slate-950/40 p-3",
                  isStrong ? variant.ring : "border-slate-800",
                  isStrong && "ring-1 ring-offset-0",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-400">
                    {label}
                  </span>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold",
                      variant.badge,
                      isStrong && "font-bold ring-1 ring-offset-0",
                    )}
                  >
                    {sig.trend}
                  </span>
                </div>
                <div className={cn("text-lg font-bold", variant.label)}>
                  {isStrong ? "STRONG" : isNormal ? "Normal" : "—"}
                </div>
                <p className="text-xs text-slate-500">{variant.blurb}</p>
              </div>
            );
          })}
        </div>
        {!signals && (
          <p className="mt-3 text-xs text-slate-500">
            No QQE signal data available for this analysis.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default QqeSignalPanel;
