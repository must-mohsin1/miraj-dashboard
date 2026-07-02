"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * AnalysisSearchForm — Client Component.
 *
 * A symbol input + "Analyze" button that navigates to the
 * `/analysis/{symbol}` detail route, which runs the full scan server-side.
 * The form degrades gracefully: an unauthenticated user (no token) still sees
 * the form on the page, and clicking Analyze will navigate to the detail
 * route which will surface the auth error there.
 */

interface AnalysisSearchFormProps {
  /** Signed-in user's access token (null when unauthenticated). Sits unused
   *  here for future direct-fetch ergonomics; current flow navigates to the
   *  server route which fetches itself. */
  token?: string | null;
}

const POPULAR_SYMBOLS = [
  "BTC-USD",
  "ETH-USD",
  "SOL-USD",
  "BNB-USD",
  "XRP-USD",
  "ADA-USD",
];

export function AnalysisSearchForm({ token }: AnalysisSearchFormProps) {
  const router = useRouter();
  const [symbol, setSymbol] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = symbol.trim();
    if (!trimmed) return;
    router.push(`/analysis/${encodeURIComponent(trimmed.toUpperCase())}`);
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label
          htmlFor="symbol-input"
          className="text-sm font-medium text-slate-300"
        >
          Trading Pair
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <Input
              id="symbol-input"
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="e.g. BTC-USD, ETH-USD, SOL-USD"
              className="border-slate-700 bg-slate-950 pl-9 text-slate-100 placeholder:text-slate-600 focus-visible:ring-emerald-500/50"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
            />
          </div>
          <Button
            type="submit"
            disabled={!symbol.trim()}
            className="bg-emerald-600 text-white hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500"
          >
            <Search className="h-4 w-4" />
            Analyze
          </Button>
        </div>
        {/* Quick-select chips */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className="text-xs text-slate-500">Popular:</span>
          {POPULAR_SYMBOLS.map((sym) => (
            <button
              key={sym}
              type="button"
              onClick={() => setSymbol(sym)}
              className="rounded-full border border-slate-700 bg-slate-800/50 px-2.5 py-0.5 text-xs text-slate-300 transition-colors hover:border-emerald-700/50 hover:text-emerald-400"
            >
              {sym}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}

export default AnalysisSearchForm;
