import { AlertTriangle, Clock } from "lucide-react";
import { Suspense } from "react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { MacroResponse } from "@/lib/types";
import { MacroCards } from "@/components/macro-cards";
import { MacroChart } from "@/components/macro-chart";
import { FundingRatesCard } from "@/components/funding-rates-card";
import { CMEGapsCard } from "@/components/cme-gaps-card";
import { CardSkeleton } from "@/components/skeletons";
import { Badge } from "@/components/ui/badge";

/**
 * Macro dashboard page — async Server Component.
 *
 * Fetches the latest macro snapshot from `GET /api/v1/macro` using the
 * signed-in user's access token, then renders:
 *
 *  - the four large stat cards (delegated to `MacroCards`, shared with the
 *    home page for visual consistency),
 *  - a recharts pie chart for BTC vs. altcoin dominance and a radial gauge
 *    for the Fear & Greed index (both inside the `MacroChart` client
 *    component),
 *  - a "Last updated" timestamp and a "Data may be stale" badge when the
 *    backend reports `stale: true`.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders placeholder cards/charts instead of throwing, so
 * the page always loads.
 */

/** Format an ISO-8601 cache timestamp as a human-readable "time ago" string. */
function formatRelative(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default async function MacroPage() {
  const token = await getAccessToken();

  let macro: MacroResponse | null = null;
  if (token) {
    try {
      macro = await serverFetch<MacroResponse>("/api/v1/macro", token);
    } catch {
      // Swallow transient backend errors — render placeholder UI.
      macro = null;
    }
  }

  const updatedAt = formatRelative(macro?.cached_at);
  const isStale = macro?.stale ?? false;
  const data = macro?.data ?? null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      {/* Heading + status badges */}
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">
              Macro Dashboard
            </h1>
            <p className="text-sm text-slate-400">
              Live crypto market macro indicators and sentiment.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {updatedAt && (
              <Badge
                variant="outline"
                className="border-slate-700 bg-slate-900/60 text-slate-300"
              >
                <Clock className="h-3 w-3" />
                Last updated {updatedAt}
              </Badge>
            )}
            {isStale && (
              <Badge
                variant="outline"
                className="border-amber-700/50 bg-amber-500/10 text-amber-400"
              >
                <AlertTriangle className="h-3 w-3" />
                Data may be stale
              </Badge>
            )}
          </div>
        </div>
      </header>

      {/* Stat cards */}
      <section aria-label="Macro indicators">
        <Suspense fallback={<CardSkeleton />}>
          <MacroCards data={data} />
        </Suspense>
      </section>

      {/* Funding rates + CME gaps */}
      <section
        aria-label="Funding rates and CME gaps"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        <FundingRatesCard rates={data?.funding_rates ?? null} />
        <CMEGapsCard gaps={data?.cme_gaps ?? null} />
      </section>

      {/* Charts */}
      <section aria-label="Macro charts">
        <MacroChart data={data} />
      </section>
    </div>
  );
}
