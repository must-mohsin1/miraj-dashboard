"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, LogOut, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { BalancesTable } from "@/components/portfolio/balances-table";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { TradesTable } from "@/components/portfolio/trades-table";
import { LivePortfolioHeader } from "@/components/portfolio/live-portfolio-header";
import type { PortfolioResponse } from "@/lib/types";
import type { PriceMap } from "@/hooks/use-price-stream";

/**
 * PortfolioDashboard — Client Component.
 *
 * Renders the three-tab portfolio view (Balances · Positions · Trades) with
 * Refresh and Disconnect action buttons in the header.
 *
 *  - **Refresh** → `POST /api/v1/portfolio/{exchange}/refresh`, then
 *    `router.refresh()` re-renders the server component with fresh cached data.
 *  - **Disconnect** → `DELETE /api/v1/portfolio/{exchange}/disconnect`, then
 *    `router.refresh()` flips the server component back to the connect form.
 *
 * Both actions use inline fetch (no SWR) because they are one-shot mutations
 * whose result replaces the entire page state — `router.refresh()` handles
 * revalidation.
 *
 * ## Live price streaming
 *
 * The dashboard subscribes to the FastAPI SSE endpoint
 * ``GET /api/v1/stream/prices?symbols=…&token=…`` for every balance asset
 * and every position symbol, converting them to SSE format:
 *  - Balance asset "BTC"  → "BTC-USD"
 *  - Position symbol "BTC/USDT:USDT" → "BTC-USDT"
 *  - Position symbol "BTC-USDT"       → "BTC-USDT"
 *
 * The JWT token is fetched client-side via ``fetch('/api/auth/session')``
 * (same pattern as `live-candlestick-chart.tsx`) because ``EventSource``
 * cannot set custom Authorization headers. The resulting live price map is
 * passed down to ``BalancesTable`` and ``PositionsTable`` which recalculate
 * USD value, PnL and PnL% in real-time.
 */

function titleCase(slug: string): string {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

const STABLECOINS = new Set([
  "USDT",
  "USDC",
  "BUSD",
  "DAI",
  "TUSD",
  "FDUSD",
  "USDP",
  "PAX",
  "GUSD",
  "UST",
  "SUSD",
]);

/** Convert a balance asset ("BTC") to its SSE symbol ("BTC-USD"). */
function balanceSymbol(asset: string): string {
  return `${asset.toUpperCase()}-USD`;
}

/**
 * Convert a position symbol (e.g. "BTC/USDT:USDT" or "BTC-USDT") to the SSE
 * symbol format that matches the user's watchlist ("BTC-USD").
 * Uses -USD suffix for USDT-quoted pairs so the watchlist filter passes.
 */
function positionSymbol(symbol: string): string {
  const s = symbol.toUpperCase();
  // ccxt futures style "BTC/USDT:USDT" → base "BTC", quote "USDT"
  // Strip the ":USDT" settlement part
  let base = s.split(":")[0].replace("/", "-");
  // "BTC-USDT" → convert USDT to USD for watchlist compatibility
  if (base.endsWith("-USDT")) {
    return base.slice(0, -5) + "-USD";
  }
  // "SOLUSDT" (no separator) → split off USDT suffix → "SOL-USD"
  if (base.endsWith("USDT") && base.length > 4) {
    return base.slice(0, -4) + "-USD";
  }
  return base;
}

/** Build the sorted, de-duplicated SSE symbol list from balances + positions. */
function buildStreamSymbols(
  balances: PortfolioResponse["balances"],
  positions: PortfolioResponse["positions"],
): string[] {
  const set = new Set<string>();
  for (const b of balances) {
    // Stablecoins already have a $1 peg — no need to stream them (saves a slot).
    if (b.total <= 0 && b.free <= 0 && b.locked <= 0) continue;
    const upper = b.asset.toUpperCase();
    if (STABLECOINS.has(upper)) continue;
    set.add(balanceSymbol(b.asset));
  }
  for (const p of positions) {
    set.add(positionSymbol(p.symbol));
  }
  return Array.from(set);
}

interface PortfolioDashboardProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token: string | null;
  /** Initial cached portfolio data from the server component. */
  portfolio: PortfolioResponse | null;
  /** Masked API key preview to display in the header. */
  maskedKey: string | null;
  /** Exchange slug (e.g. "mexc", "binance", "bybit"). */
  exchange: string;
}

export function PortfolioDashboard({
  token,
  portfolio,
  maskedKey,
  exchange,
}: PortfolioDashboardProps) {
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live prices state (SSE).
  const [prices, setPrices] = useState<PriceMap>({});
  const [isConnected, setIsConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const exchangeName = titleCase(exchange);

  const balances = portfolio?.balances ?? [];
  const positions = portfolio?.positions ?? [];
  const trades = portfolio?.trades ?? [];
  const snapshot = portfolio?.snapshot ?? null;
  const isStale = portfolio?.stale ?? true;
  const lastRefreshed = portfolio?.last_refreshed ?? null;

  // Compute the SSE symbol list whenever balances/positions change.
  const streamSymbols = useMemo(
    () => buildStreamSymbols(balances, positions),
    [balances, positions],
  );

  // Subscribe to live prices via EventSource (same pattern as
  // live-candlestick-chart.tsx: fetch token client-side, pass via ?token=).
  useEffect(() => {
    let cancelled = false;

    async function connect() {
      if (cancelled) return;
      if (streamSymbols.length === 0) {
        console.log("[portfolio] No stream symbols — skipping SSE");
        return;
      }

      console.log("[portfolio] Stream symbols:", streamSymbols);

      // Fetch token client-side (EventSource can't set Authorization header).
      try {
        const res = await fetch("/api/auth/session");
        const data = await res.json();
        const token = data?.user?.accessToken;
        if (!token || cancelled) {
          console.log("[portfolio] No token for SSE");
          return;
        }

        const symParam = streamSymbols.map((s) => s.toUpperCase()).join(",");
        const url = `/api/v1/stream/prices?symbols=${encodeURIComponent(
          symParam,
        )}&token=${encodeURIComponent(token)}`;

        // Close any prior connection before opening a new one.
        if (esRef.current) {
          esRef.current.close();
        }

        const es = new EventSource(url);
        esRef.current = es;

        es.onopen = () => {
          if (!cancelled) setIsConnected(true);
        };

        es.onmessage = (event) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(event.data);
            if (data.symbol && typeof data.price === "number") {
              const sym = data.symbol.toUpperCase();
              setPrices((prev) => ({
                ...prev,
                [sym]: { price: data.price, timestamp: data.timestamp },
              }));
            }
          } catch {
            /* ignore malformed lines */
          }
        };

        es.onerror = () => {
          if (!cancelled) setIsConnected(false);
          es.close();
          // Reconnect after 3s backoff.
          setTimeout(() => {
            if (!cancelled) connect();
          }, 3000);
        };
      } catch {
        if (!cancelled) {
          setTimeout(() => {
            if (!cancelled) connect();
          }, 3000);
        }
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [streamSymbols]);

  // The price map is only "live" once the stream is open and we have data.
  const livePrices: PriceMap | null =
    isConnected && Object.keys(prices).length > 0 ? prices : null;

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/portfolio/${exchange}/refresh`, {
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
          `Refresh failed: ${res.status} ${res.statusText}${
            detail ? ` — ${detail}` : ""
          }`,
        );
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  async function handleDisconnect() {
    if (
      !window.confirm(
        `Disconnect ${exchangeName}? This removes your stored API keys and all cached portfolio data.`
      )
    ) {
      return;
    }
    setDisconnecting(true);
    setError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/portfolio/${exchange}/disconnect`, {
        method: "DELETE",
        headers,
      });
      if (!res.ok && res.status !== 204) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(
          `Disconnect failed: ${res.status} ${res.statusText}${
            detail ? ` — ${detail}` : ""
          }`,
        );
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header row: connection info + actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {maskedKey && (
            <Badge
              variant="outline"
              className="border-slate-700 bg-slate-900/60 text-slate-300"
            >
              Key: <span className="font-mono">{maskedKey}</span>
            </Badge>
          )}
          {lastRefreshed && (
            <Badge
              variant="outline"
              className="border-slate-700 bg-slate-900/60 text-slate-300"
            >
              Updated: {formatRelative(lastRefreshed)}
            </Badge>
          )}
          {isStale && (
            <Badge
              variant="outline"
              className="border-amber-700/50 bg-amber-500/10 text-amber-400"
            >
              Stale — click Refresh
            </Badge>
          )}
          {snapshot && snapshot.total_balance_usd != null && !isConnected && (
            <Badge
              variant="outline"
              className="border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
            >
              Total: ${snapshot.total_balance_usd.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </Badge>
          )}
          {isConnected && (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-700/50 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-400">
              <span className="relative flex h-2 w-2" aria-hidden>
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                  style={{ animationDuration: "1.5s" }}
                />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              Live
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing || disconnecting}
            className="min-h-11 border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800 hover:text-slate-100"
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDisconnect}
            disabled={refreshing || disconnecting}
            className="min-h-11 border-red-800/50 bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300"
          >
            {disconnecting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <LogOut className="h-4 w-4" />
            )}
            Disconnect
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Live portfolio summary header — recalculates total value + PnL in real-time */}
      <LivePortfolioHeader
        balances={balances}
        positions={positions}
        livePrices={livePrices}
        isConnected={isConnected}
      />

      {/* Tabs */}
      <Tabs defaultValue="balances" className="w-full">
        <TabsList>
          <TabsTrigger value="balances">
            Balances ({balances.length})
          </TabsTrigger>
          <TabsTrigger value="positions">
            Positions ({positions.length})
          </TabsTrigger>
          <TabsTrigger value="trades">
            Trades ({trades.length})
          </TabsTrigger>
        </TabsList>
        <TabsContent value="balances">
          <BalancesTable balances={balances} livePrices={livePrices} />
        </TabsContent>
        <TabsContent value="positions">
          <PositionsTable positions={positions} livePrices={livePrices} />
        </TabsContent>
        <TabsContent value="trades">
          <TradesTable trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Format an ISO timestamp as a compact human-readable string. */
function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default PortfolioDashboard;
