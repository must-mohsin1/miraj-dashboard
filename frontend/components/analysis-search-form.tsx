"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useClientToken } from "@/hooks/use-client-token";
import { usePriceStream, type LivePrice } from "@/hooks/use-price-stream";

/**
 * AnalysisSearchForm — Client Component.
 *
 * A symbol input + "Analyze" button that navigates to the
 * `/analysis/{symbol}` detail route, which runs the full scan server-side.
 * The form degrades gracefully: an unauthenticated user (no token) still sees
 * the form on the page, and clicking Analyze will navigate to the detail
 * route which will surface the auth error there.
 *
 * Live prices for popular symbols (BTC-USD, ETH-USD, …) are streamed over
 * SSE while the user is on this page, using the same `useClientToken` +
 * `usePriceStream` pattern as `live-candlestick-chart.tsx`. Each quick-select
 * chip shows the current live price next to the symbol.
 */

interface AnalysisSearchFormProps {
  /** Signed-in user's access token (null when unauthenticated). Sits unused
   *  here for future direct-fetch ergonomics; current flow navigates to the
   *  server route which fetches itself. The SSE stream fetches its own token
   *  client-side via useClientToken. */
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

/** Decide decimal precision based on price magnitude (crypto-friendly). */
function precisionForPrice(price: number | undefined): number {
  if (price == null) return 2;
  if (price >= 1000) return 2;
  if (price >= 1) return 2;
  if (price >= 0.01) return 4;
  return 6;
}

/** Format a live price tick for compact chip display. */
function formatPrice(live?: LivePrice): string {
  if (!live) return "—";
  return live.price.toLocaleString(undefined, {
    minimumFractionDigits: precisionForPrice(live.price),
    maximumFractionDigits: precisionForPrice(live.price),
  });
}

export function AnalysisSearchForm({ token }: AnalysisSearchFormProps) {
  const router = useRouter();
  const [symbol, setSymbol] = useState("");

  // ── Live price streaming for popular symbols ───────────────────────
  // Same pattern as live-candlestick-chart.tsx: fetch token client-side,
  // open an EventSource to /api/v1/stream/prices for the popular set.
  const clientToken = useClientToken();
  const { prices, isConnected } = usePriceStream(
    POPULAR_SYMBOLS,
    clientToken ?? token,
  );

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
        {/* Quick-select chips with live prices */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
            Popular:
            {isConnected && (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase leading-none text-emerald-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span
                    className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                    style={{ animationDuration: "1.5s" }}
                  />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
                </span>
                Live
              </span>
            )}
          </span>
          {POPULAR_SYMBOLS.map((sym) => {
            const live = prices[sym];
            return (
              <button
                key={sym}
                type="button"
                onClick={() => setSymbol(sym)}
                className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-800/50 px-2.5 py-0.5 text-xs text-slate-300 transition-colors hover:border-emerald-700/50 hover:text-emerald-400"
              >
                {sym}
                <span
                  className={`font-mono tabular-nums text-[11px] ${
                    live ? "text-emerald-400" : "text-slate-600"
                  }`}
                >
                  {formatPrice(live)}
                </span>
              </button>
            );
          })}
        </div>
      </form>
    </div>
  );
}

export default AnalysisSearchForm;
