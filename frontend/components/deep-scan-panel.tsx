"use client";

import { useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  Loader2,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useClientToken } from "@/hooks/use-client-token";
import type { DeepAnalysis, DeepAnalysisSection, DeepScanResult } from "@/lib/types";

interface DeepScanPanelProps {
  symbol: string;
}

/**
 * DeepScanPanel — Client Component.
 *
 * Shows a "Deep Scan" button that triggers `POST /api/v1/scan/{symbol}/deep`
 * and displays the narrative analysis in an expandable panel.
 */
export function DeepScanPanel({ symbol }: DeepScanPanelProps) {
  const token = useClientToken();
  const [loading, setLoading] = useState(false);
  const [deep, setDeep] = useState<DeepAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  async function handleDeepScan() {
    setLoading(true);
    setError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/scan/${encodeURIComponent(symbol)}/deep`, {
        method: "POST",
        headers,
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(
          `Deep scan failed: ${res.status}${detail ? ` — ${detail}` : ""}`
        );
      }
      const data = (await res.json()) as DeepScanResult;
      setDeep(data.deep_analysis);
      setExpanded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const biasPct = deep?.bias_percent ?? 50;
  const biasLabel =
    biasPct >= 65 ? "Bullish" : biasPct <= 35 ? "Bearish" : "Neutral";
  const biasColor =
    biasPct >= 65
      ? "text-emerald-400 border-emerald-700/50"
      : biasPct <= 35
        ? "text-red-400 border-red-700/50"
        : "text-slate-400 border-slate-700/50";
  const biasBg =
    biasPct >= 65
      ? "bg-emerald-500/10"
      : biasPct <= 35
        ? "bg-red-500/10"
        : "bg-slate-800/50";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-violet-400" />
          <h3 className="text-sm font-medium text-slate-300">
            Deep Analysis
          </h3>
        </div>

        {deep ? (
          <div className="flex items-center gap-2">
            <div className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${biasColor} ${biasBg}`}>
              {biasPct >= 65 ? (
                <TrendingUp className="h-3 w-3" />
              ) : biasPct <= 35 ? (
                <TrendingDown className="h-3 w-3" />
              ) : null}
              {biasLabel} {biasPct}%
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setExpanded(!expanded)}
              className="h-7 px-2 text-slate-400 hover:text-slate-200"
            >
              {expanded ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={handleDeepScan}
            disabled={loading}
            className="border-violet-700/50 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20"
          >
            {loading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Scanning...
              </>
            ) : (
              <>
                <Brain className="h-3.5 w-3.5" />
                Deep Scan
              </>
            )}
          </Button>
        )}
      </div>

      {/* Error state */}
      {error && (
        <p className="mt-2 text-xs text-red-400">{error}</p>
      )}

      {/* Loading indicator */}
      {loading && !deep && (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-3 w-3 animate-spin" />
          Running deep analysis pipeline — bypassing cache...
        </div>
      )}

      {/* Deep analysis results */}
      {deep && expanded && (
        <div className="mt-4 space-y-4">
          {/* Summary */}
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-3">
            <p className="text-sm leading-relaxed text-slate-200">
              {deep.summary}
            </p>
          </div>

          {/* Signal counts */}
          <div className="flex gap-3">
            <div className="flex items-center gap-1.5 rounded-md bg-emerald-500/10 px-3 py-1.5 text-xs">
              <TrendingUp className="h-3 w-3 text-emerald-400" />
              <span className="text-emerald-300">{deep.bullish_signals}</span>
              <span className="text-slate-400">bullish</span>
            </div>
            <div className="flex items-center gap-1.5 rounded-md bg-red-500/10 px-3 py-1.5 text-xs">
              <TrendingDown className="h-3 w-3 text-red-400" />
              <span className="text-red-300">{deep.bearish_signals}</span>
              <span className="text-slate-400">bearish</span>
            </div>
            <div className="flex items-center gap-1.5 rounded-md bg-slate-800 px-3 py-1.5 text-xs">
              <span className="text-slate-300">{deep.neutral_signals}</span>
              <span className="text-slate-500">neutral</span>
            </div>
          </div>

          {/* Detailed sections */}
          {deep.detailed_analysis.map((section, i) => (
            <DeepSection key={i} section={section} />
          ))}

          {/* Risk factors */}
          {deep.risk_factors.length > 0 && (
            <div className="rounded-lg border border-amber-800/30 bg-amber-500/5 p-3">
              <div className="mb-2 flex items-center gap-1.5">
                <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
                <span className="text-xs font-medium text-amber-300">
                  Risk Factors
                </span>
              </div>
              <ul className="space-y-1">
                {deep.risk_factors.map((rf, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-xs text-slate-400"
                  >
                    <span className="mt-0.5 h-1 w-1 flex-shrink-0 rounded-full bg-amber-500/50" />
                    {rf}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Timeframe breakdown */}
          {Object.keys(deep.timeframe_breakdown).length > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                Timeframes
              </h4>
              <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5">
                {Object.entries(deep.timeframe_breakdown).map(([tf, desc]) => (
                  <div
                    key={tf}
                    className="rounded border border-slate-700/50 bg-slate-800/30 px-2.5 py-2"
                  >
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      {tf}
                    </div>
                    <div className="mt-0.5 text-[11px] leading-tight text-slate-300">
                      {desc || "—"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Cached note */}
          <p className="text-[10px] text-slate-600">
            Deep analysis is generated from live scan data. Refresh the page
            and run Deep Scan again for an updated analysis.
          </p>
        </div>
      )}

      {/* Collapsed state hint */}
      {deep && !expanded && (
        <p className="mt-2 text-xs text-slate-500">
          {/* key_levels summary */}
          {deep.key_levels?.entry && (
            <span className="text-slate-400">
              Entry ${Number(deep.key_levels.entry).toLocaleString()}
              {deep.key_levels.stop_loss && (
                <> &middot; Stop ${Number(deep.key_levels.stop_loss).toLocaleString()}</>
              )}
              {" &middot; "}
            </span>
          )}
          {deep.risk_factors.length > 0 && (
            <span className="text-amber-400/70">
              {deep.risk_factors.length} risk factor{deep.risk_factors.length !== 1 ? "s" : ""}
            </span>
          )}
        </p>
      )}
    </div>
  );
}

/** Render a single deep analysis section. */
function DeepSection({ section }: { section: DeepAnalysisSection }) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-3">
      <h4 className="mb-1.5 text-xs font-medium text-slate-400">
        {section.heading}
      </h4>
      <p className="text-xs leading-relaxed text-slate-300">{section.body}</p>
    </div>
  );
}
