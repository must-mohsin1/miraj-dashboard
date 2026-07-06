"use client";

import type { Pattern } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

interface PatternsPanelProps {
  patterns: Pattern[] | null | undefined;
}

export function PatternsPanel({ patterns }: PatternsPanelProps) {
  if (!patterns || patterns.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-300">Chart Patterns</h3>
        <p className="text-xs text-slate-500">No patterns detected</p>
      </div>
    );
  }

  function directionMeta(dir: string) {
    const d = dir.toLowerCase();
    if (d.includes("bull")) return { label: "Bullish", className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50" };
    if (d.includes("bear")) return { label: "Bearish", className: "bg-red-500/10 text-red-400 border-red-700/50" };
    return { label: dir || "Neutral", className: "bg-slate-500/10 text-slate-400 border-slate-700/50" };
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">Chart Patterns</h3>
      <div className="flex flex-wrap gap-2">
        {patterns.map((p, i) => {
          const meta = directionMeta(p.direction || "");
          return (
            <div
              key={i}
              className="flex items-center gap-2 rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2"
              title={typeof p.details === "string" ? p.details : JSON.stringify(p.details || "")}
            >
              <span className="text-xs font-medium text-slate-200">{p.name || p.pattern}</span>
              <Badge variant="outline" className={`text-[9px] ${meta.className}`}>
                {meta.label}
              </Badge>
              {p.timeframe && (
                <span className="text-[9px] text-slate-500">{p.timeframe}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PatternsPanel;
