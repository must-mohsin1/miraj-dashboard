import { Wallet } from "lucide-react";
import { Suspense } from "react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { KeysResponse, PortfolioResponse } from "@/lib/types";
import { ConnectForm } from "@/components/portfolio/connect-form";
import { PortfolioDashboard } from "@/components/portfolio/portfolio-dashboard";
import { ExchangeSelector } from "@/components/portfolio/exchange-selector";
import { TabsSkeleton } from "@/components/skeletons";

/**
 * Portfolio page — async Server Component.
 *
 * Reads the selected exchange from `searchParams.exchange` (default `"mexc"`),
 * checks the connection status via `GET /api/v1/portfolio/{exchange}/keys`.
 * When connected, it additionally fetches the cached portfolio data via
 * `GET /api/v1/portfolio/{exchange}` and renders the tabbed dashboard
 * (Balances · Positions · Trades) with Refresh / Disconnect buttons.
 * When not connected, it renders the `ConnectForm`.
 *
 * The `ExchangeSelector` dropdown is rendered above both states so the user
 * can switch exchanges at any time; the selection is persisted to the URL
 * (`/portfolio?exchange=binance`).
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders the connect form (safe default) instead of
 * throwing, so the page always loads.
 */

export const dynamic = "force-dynamic";

/** Canonical list used to validate the `exchange` search param. */
const KNOWN_EXCHANGES = ["mexc", "binance", "bybit"];

function titleCase(slug: string): string {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

interface PageProps {
  searchParams: Promise<{ exchange?: string }>;
}

export default async function PortfolioPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const rawExchange = (params.exchange ?? "mexc").toLowerCase();
  const exchange = KNOWN_EXCHANGES.includes(rawExchange) ? rawExchange : "mexc";

  const token = await getAccessToken();

  let keys: KeysResponse | null = null;
  if (token) {
    try {
      keys = await serverFetch<KeysResponse>(
        `/api/v1/portfolio/${exchange}/keys`,
        token
      );
    } catch {
      // Backend / ccxt unavailable → treat as not connected.
      keys = null;
    }
  }

  const isConnected = keys?.connected ?? false;

  // If connected, prefetch the cached portfolio data so the initial render
  // is populated (the client component can refresh later).
  let portfolio: PortfolioResponse | null = null;
  if (isConnected && token) {
    try {
      portfolio = await serverFetch<PortfolioResponse>(
        `/api/v1/portfolio/${exchange}`,
        token
      );
    } catch {
      // Keys exist but cached data is empty / endpoint failed → show the
      // dashboard with empty tables and a "Refresh" prompt.
      portfolio = null;
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Wallet className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Portfolio
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Connect your {titleCase(exchange)} account to view balances, open
          positions, and recent trades.
        </p>
        <Suspense fallback={null}>
          <ExchangeSelector value={exchange} />
        </Suspense>
      </header>

      {isConnected ? (
        <Suspense fallback={<TabsSkeleton />}>
          <PortfolioDashboard
            token={token}
            portfolio={portfolio}
            maskedKey={keys?.masked_key ?? null}
            exchange={exchange}
          />
        </Suspense>
      ) : (
        <ConnectForm token={token} exchange={exchange} />
      )}
    </div>
  );
}
