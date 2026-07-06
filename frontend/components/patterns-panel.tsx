"use client";

import { useMemo } from "react";
import type { Pattern } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

interface PatternsPanelProps {
  /** Backend sends `{ detected: Pattern[] } | null`; also accept a bare array. */
  patterns: Pattern[] | Record<string, unknown> | null | undefined;
}

function coerceToArray(
  raw: Pattern[] | Record<string, unknown> | null | undefined,
): Pattern[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as Pattern[];
  const detected = (raw as Record<string, unknown>)["detected"];
  if (Array.isArray(detected)) return detected as Pattern[];
  return [];
}

function directionMeta(dir: string) {
  const d = dir.toLowerCase();
  if (d.includes("bull")) return { label: "Bullish", className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50" };
  if (d.includes("bear")) return { label: "Bearish", className: "bg-red-500/10 text-red-400 border-red-700/50" };
  return { label: dir || "Neutral", className: "bg-slate-500/10 text-slate-400 border-slate-700/50" };
}

export function PatternsPanel({ patterns }: PatternsPanelProps) {
  const list = useMemo(() => coerceToArray(patterns), [patterns]);

  if (list.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-300">Chart Patterns</h3>
        <p className="text-xs text-slate-500">No patterns detected</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">Chart Patterns</h3>
      <div className="flex flex-wrap gap-2">
        {list.map((p, i) => {
          const dir = p.direction || p.signal || "";
          const meta = directionMeta(dir);
          const label = p.name || p.pattern || "Unknown";
          const detail =
            typeof p.details === "string"
              ? p.details
              : p.levels
                ? JSON.stringify(p.levels)
                : "";
          return (
            <div
              key={i}
              className="flex items-center gap-2 rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2"
              title={detail}
            >
              <span className="text-xs font-medium text-slate-200">{label}</span>
              <Badge variant="outline" className={`text-[9px] ${meta.className}`}>
                {meta.label}
              </Badge>
              {p.confirmed !== undefined && (
                <span className={`text-[9px] ${p.confirmed ? "text-emerald-400" : "text-amber-400"}`}>
                  {p.confirmed ? "✓ confirmed" : "unconfirmed"}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PatternsPanel;
