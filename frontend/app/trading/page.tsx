import { CandlestickChart } from "lucide-react";
import { Suspense } from "react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import { ExchangeSelector } from "@/components/portfolio/exchange-selector";
import { TradingDashboard } from "@/components/trading/trading-dashboard";
import { TabsSkeleton } from "@/components/skeletons";

export const dynamic = "force-dynamic";

const KNOWN_EXCHANGES = ["mexc", "binance", "bybit"];

function titleCase(slug: string): string {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

interface PageProps {
  searchParams: Promise<{ exchange?: string }>;
}

/**
 * Trading page — async Server Component.
 *
 * Reads the selected exchange from `searchParams.exchange` (default `"mexc"`),
 * checks whether trading is enabled via `GET /api/v1/trading/status`, and
 * passes both to the client `TradingDashboard`.
 *
 * Degrades gracefully: an unauthenticated user or a transient backend
 * failure renders the dashboard in a disabled state (safe default).
 */
export default async function TradingPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const rawExchange = (params.exchange ?? "mexc").toLowerCase();
  const exchange = KNOWN_EXCHANGES.includes(rawExchange) ? rawExchange : "mexc";

  const token = await getAccessToken();

  // Check whether trading is enabled on the backend.
  let tradingEnabled = false;
  if (token) {
    try {
      const status = await serverFetch<{ enabled: boolean }>(
        "/api/v1/trading/status",
        token,
      );
      tradingEnabled = status?.enabled ?? false;
    } catch {
      // Backend / ccxt unavailable — trading is disabled.
      tradingEnabled = false;
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <CandlestickChart className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Trading
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Place orders, manage positions, and cancel open orders on{" "}
          {titleCase(exchange)}.
        </p>
        <Suspense fallback={null}>
          <ExchangeSelector value={exchange} />
        </Suspense>
      </header>

      <Suspense fallback={<TabsSkeleton />}>
        <TradingDashboard
          token={token}
          exchange={exchange}
          tradingEnabled={tradingEnabled}
        />
      </Suspense>
    </div>
  );
}
