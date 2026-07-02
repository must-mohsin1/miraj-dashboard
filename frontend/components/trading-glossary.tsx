"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Info } from "lucide-react";

interface GlossaryTerm {
  abbr: string;
  full: string;
  explanation: string;
  color?: string;
}

const GLOSSARY: GlossaryTerm[] = [
  {
    abbr: "EMA",
    full: "Exponential Moving Average",
    explanation: "A weighted moving average that gives more importance to recent prices. Used to identify trend direction. Price above EMA = uptrend, below = downtrend. The 9/21 EMAs are short-term (fast), 50 is longer-term (slow). When fast EMA crosses above slow EMA, it's a bullish signal.",
    color: "#60a5fa",
  },
  {
    abbr: "OB",
    full: "Order Block",
    explanation: "The last candle before a strong move — a zone where institutions placed large orders. Green OB (bullish) = last red candle before a strong rally up. Red OB (bearish) = last green candle before a strong drop. Traders watch these zones for price to return and bounce.",
    color: "rgba(34, 197, 94, 0.6)",
  },
  {
    abbr: "FVG",
    full: "Fair Value Gap",
    explanation: "A gap left in price action where buying/selling was so aggressive it skipped price levels — the candle's range doesn't overlap with the previous or next candle. These gaps act as magnets — price often returns to 'fill' the gap before continuing. Yellow dashed lines mark FVG zones.",
    color: "rgba(250, 204, 21, 0.6)",
  },
  {
    abbr: "ATR",
    full: "Average True Range",
    explanation: "Measures market volatility — how much price moves on average over a period. Used to set stop losses: a stop at 1.5x ATR is far enough to avoid random noise but close enough to limit losses. Higher ATR = more volatile = wider stops needed.",
    color: "#a78bfa",
  },
  {
    abbr: "R:R",
    full: "Risk-to-Reward Ratio",
    explanation: "How much you risk vs how much you could gain. 1:2 means you risk $1 to make $2. T1 is your first profit target at 1:1 R:R, T2 at 1:2 R:R. Always aim for at least 1:2 — even if you're right only 40% of the time, you'll be profitable.",
    color: "#22c55e",
  },
  {
    abbr: "PnL",
    full: "Profit and Loss",
    explanation: "The unrealized gain or loss on an open position. Green = profit, red = loss. PnL% shows the return relative to your margin (the collateral you put up). A -19% PnL means you've lost 19% of your margin.",
    color: "#22c55e",
  },
  {
    abbr: "L/S Ratio",
    full: "Long/Short Ratio",
    explanation: "The ratio of traders holding long positions vs short positions. Above 1.0 = more longs than shorts (can be a contrarian signal — too many longs may mean a squeeze is coming). Below 1.0 = more shorts.",
    color: "#f59e0b",
  },
];

export function TradingGlossary() {
  const [expanded, setExpanded] = useState(false);
  const [hoveredTerm, setHoveredTerm] = useState<string | null>(null);

  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between p-3 text-sm font-medium text-slate-300 transition-colors hover:bg-slate-800/50"
      >
        <span className="flex items-center gap-2">
          <Info className="h-4 w-4 text-slate-500" />
          Trading Terms Glossary
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-slate-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-500" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-slate-800 p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {GLOSSARY.map((term) => (
              <div
                key={term.abbr}
                className="group relative rounded-lg border border-slate-800 bg-slate-950/50 p-3 transition-colors hover:border-slate-700"
                onMouseEnter={() => setHoveredTerm(term.abbr)}
                onMouseLeave={() => setHoveredTerm(null)}
              >
                <div className="flex items-center gap-2">
                  {term.color && (
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-sm"
                      style={{ backgroundColor: term.color }}
                    />
                  )}
                  <span className="font-semibold text-slate-200">
                    {term.abbr}
                  </span>
                  <span className="text-xs text-slate-500">
                    {term.full}
                  </span>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                  {term.explanation}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick info badges — always visible */}
      {!expanded && (
        <div className="flex flex-wrap gap-2 px-3 pb-3">
          {GLOSSARY.map((term) => (
            <span
              key={term.abbr}
              className="group relative inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800/50 px-2 py-0.5 text-xs text-slate-400 transition-colors hover:text-slate-200"
            >
              {term.color && (
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: term.color }}
                />
              )}
              {term.abbr}
              <Info className="h-3 w-3 text-slate-600 group-hover:text-slate-400" />
              {/* Tooltip on hover */}
              <span className="pointer-events-none absolute bottom-full left-0 z-50 mb-1 hidden w-48 rounded-md border border-slate-700 bg-slate-950 p-2 text-xs text-slate-300 shadow-lg group-hover:block">
                <span className="font-semibold text-slate-200">
                  {term.abbr} — {term.full}
                </span>
                <br />
                <span className="mt-1 block leading-relaxed text-slate-400">
                  {term.explanation.substring(0, 120)}...
                </span>
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
