import { BookOpen } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { JournalDashboard } from "@/components/journal/journal-dashboard";

/**
 * Journal page — async Server Component.
 *
 * Route `/journal` — renders the `JournalDashboard` client component which
 * fetches from `/api/v1/journal` and `/api/v1/analytics/{exchange}/journal-summary`.
 *
 * The `exchange` search param (default `"mexc"`) controls which exchange's
 * tag summary is shown; the journal entries list itself is
 * exchange-agnostic (covers all of the user's entries) so a user with no
 * connected exchange can still use the journal.
 *
 * Degrades gracefully: an unauthenticated user (no token) still renders the
 * dashboard — the client component fetches its own token via
 * `/api/auth/session` and shows empty state / login prompts as needed.
 */

export const dynamic = "force-dynamic";

/** Canonical list used to validate the `exchange` search param. */
const KNOWN_EXCHANGES = ["mexc", "binance", "bybit"];

interface PageProps {
  searchParams: Promise<{ exchange?: string; symbol?: string }>;
}

export default async function JournalPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const rawExchange = (params.exchange ?? "mexc").toLowerCase();
  const exchange = KNOWN_EXCHANGES.includes(rawExchange) ? rawExchange : "mexc";
  const requestedSymbol = (params.symbol ?? "").trim().toUpperCase();
  // A navigation prefill is display-only and constrained to an exchange symbol shape.
  const prefillSymbol = /^[A-Z0-9_-]{1,30}$/.test(requestedSymbol) ? requestedSymbol : undefined;

  const token = await getAccessToken();

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Trading Journal
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Document your trades, tag them for analysis, and review lessons
          learned. Screenshot uploads and per-tag PnL analytics help you spot
          what's working.
        </p>
      </header>

      <JournalDashboard token={token} exchange={exchange} prefillSymbol={prefillSymbol} />
    </div>
  );
}
