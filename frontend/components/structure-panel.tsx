import { Layers } from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { StructureByTF, StructureLabel, StructureSwing } from "@/lib/types";

/**
 * StructurePanel — Server Component.
 *
 * Renders the per-timeframe market-structure classification
 * (HH / HL / LH / LL) for the weekly, daily, 4h, 1h, and 15m timeframes.
 *
 * Colour coding:
 *   - HH / HL (higher high / higher low) → emerald (bullish)
 *   - LH / LL (lower high / lower low)  → red     (bearish)
 *   - unknown / insufficient data       → slate   (neutral)
 *
 * The last three swing points are shown per row so the trader can see the
 * actual pivots the classification is derived from.
 */

interface TimeframeRow {
  key: keyof StructureByTF;
  label: string;
}

const TIMEFRAMES: TimeframeRow[] = [
  { key: "weekly", label: "Weekly" },
  { key: "daily", label: "Daily" },
  { key: "4h", label: "4H" },
  { key: "1h", label: "1H" },
  { key: "15m", label: "15m" },
];

/** Visual variant for a structure label (bullish / bearish / neutral). */
interface LabelVariant {
  /** Badge background + text colour. */
  badge: string;
  /** Accent border colour. */
  border: string;
  /** Text colour for the label. */
  text: string;
}

function labelVariant(label: StructureLabel["label"]): LabelVariant {
  switch (label) {
    case "HH":
    case "HL":
      return {
        badge: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
        border: "border-l-emerald-600/60",
        text: "text-emerald-400",
      };
    case "LH":
    case "LL":
      return {
        badge: "bg-red-500/10 text-red-400 border-red-700/50",
        border: "border-l-red-600/60",
        text: "text-red-400",
      };
    default:
      return {
        badge: "bg-slate-500/10 text-slate-400 border-slate-700/50",
        border: "border-l-slate-700/60",
        text: "text-slate-300",
      };
  }
}

/** Human-readable expansion of the structure code (e.g. HH → "Higher High"). */
function labelExpansion(label: StructureLabel["label"]): string {
  switch (label) {
    case "HH":
      return "Higher High";
    case "HL":
      return "Higher Low";
    case "LH":
      return "Lower High";
    case "LL":
      return "Lower Low";
    default:
      return label;
  }
}

/** Format a swing point for the last-3-swings column. */
function formatSwing(swing: StructureSwing): string {
  const arrow = swing.type === "high" ? "▲" : "▼";
  const price =
    Math.abs(swing.price) >= 1000
      ? swing.price.toLocaleString("en-US", {
          maximumFractionDigits: 0,
        })
      : swing.price.toFixed(2);
  return `${arrow} ${price}`;
}

interface StructurePanelProps {
  /** Per-TF structure labels. Pass `null` to show a placeholder. */
  structure: StructureByTF | null;
}

export function StructurePanel({ structure }: StructurePanelProps) {
  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-sm font-medium text-slate-300">
            Market Structure
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left">
                <th className="pb-2 pr-3 text-xs font-medium text-slate-500">
                  Timeframe
                </th>
                <th className="pb-2 pr-3 text-xs font-medium text-slate-500">
                  Label
                </th>
                <th className="pb-2 pr-3 text-xs font-medium text-slate-500">
                  Detail
                </th>
                <th className="pb-2 text-xs font-medium text-slate-500">
                  Last Swings
                </th>
              </tr>
            </thead>
            <tbody>
              {TIMEFRAMES.map(({ key, label }) => {
                const entry: StructureLabel | undefined = structure?.[key];
                const lbl = entry?.label ?? "unknown";
                const variant = labelVariant(lbl);
                const swings = entry?.swings ?? [];
                const lastSwings = swings.slice(-3);

                return (
                  <tr
                    key={key}
                    className={cn(
                      "border-b border-slate-800/60 last:border-0",
                      "border-l-2",
                      variant.border,
                    )}
                  >
                    <td className="py-2.5 pr-3 font-medium text-slate-300">
                      {label}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold",
                          variant.badge,
                        )}
                        title={labelExpansion(lbl)}
                      >
                        {lbl}
                      </span>
                      <span className="ml-2 text-xs text-slate-500">
                        {labelExpansion(lbl)}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-slate-400">
                      {entry?.error
                        ? entry.error
                        : entry?.detail ?? "No data"}
                    </td>
                    <td className="py-2.5">
                      {lastSwings.length > 0 ? (
                        <div className="flex flex-col gap-0.5">
                          {lastSwings.map((sw, i) => (
                            <span
                              key={i}
                              className={cn(
                                "font-mono text-xs tabular-nums",
                                sw.type === "high"
                                  ? "text-emerald-400/80"
                                  : "text-red-400/80",
                              )}
                            >
                              {formatSwing(sw)}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!structure && (
          <p className="mt-3 text-xs text-slate-500">
            No market-structure data available for this analysis.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default StructurePanel;
