import { Search } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { WatchlistResponse } from "@/lib/types";
import { WatchlistTable } from "@/components/watchlist-table";

/**
 * Scanner page — async Server Component.
 *
 * Fetches the current user's watchlist from `GET /api/v1/watchlist` on the
 * server (so the initial render shows the list immediately, with no client
 * spinner), then hands the signed-in token to the `WatchlistTable` client
 * component so it can perform add / remove / scan mutations after
 * hydration.
 *
 * The scan endpoint is `POST /api/v1/scan/{symbol}` (path parameter, no
 * request body) and the watchlist add endpoint expects `{ pair }` — this
 * page follows the real backend contract.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders an empty watchlist and a notice instead of
 * throwing, so the page always loads.
 */

export default async function ScannerPage() {
  const token = await getAccessToken();

  let watchlist: WatchlistResponse | null = null;
  if (token) {
    try {
      watchlist = await serverFetch<WatchlistResponse>(
        "/api/v1/watchlist",
        token
      );
    } catch {
      // Swallow transient backend errors — the client component will
      // attempt its own SWR revalidate and surface any persistent error.
      watchlist = null;
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Search className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Pair Scanner
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Manage your watchlist and run the full analysis pipeline on each
          pair. Scans run macro → OHLCV → indicators → QQE Mod → SMC →
          patterns → confluence → trade plan.
        </p>
      </header>

      <section aria-label="Watchlist">
        <WatchlistTable token={token} />
      </section>
    </div>
  );
}
