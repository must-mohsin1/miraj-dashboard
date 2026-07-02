import { Wallet } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { KeysResponse, PortfolioResponse } from "@/lib/types";
import { ConnectForm } from "@/components/portfolio/connect-form";
import { PortfolioDashboard } from "@/components/portfolio/portfolio-dashboard";

/**
 * Portfolio page — async Server Component.
 *
 * Checks the MEXC exchange connection status via
 * `GET /api/v1/portfolio/mexc/keys`. When connected, it additionally fetches
 * the cached portfolio data via `GET /api/v1/portfolio/mexc` and renders the
 * tabbed dashboard (Balances · Positions · Trades) with Refresh / Disconnect
 * buttons. When not connected, it renders the `ConnectForm`.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders the connect form (safe default) instead of
 * throwing, so the page always loads.
 */

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const token = await getAccessToken();

  let keys: KeysResponse | null = null;
  if (token) {
    try {
      keys = await serverFetch<KeysResponse>(
        "/api/v1/portfolio/mexc/keys",
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
        "/api/v1/portfolio/mexc",
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
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Wallet className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Portfolio
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Connect your MEXC account to view balances, open positions, and recent
          trades.
        </p>
      </header>

      {isConnected ? (
        <PortfolioDashboard
          token={token}
          portfolio={portfolio}
          maskedKey={keys?.masked_key ?? null}
        />
      ) : (
        <ConnectForm token={token} />
      )}
    </div>
  );
}
