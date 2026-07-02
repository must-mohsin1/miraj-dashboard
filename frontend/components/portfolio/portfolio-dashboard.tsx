"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
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
import type { PortfolioResponse } from "@/lib/types";

/**
 * PortfolioDashboard — Client Component.
 *
 * Renders the three-tab portfolio view (Balances · Positions · Trades) with
 * Refresh and Disconnect action buttons in the header.
 *
 *  - **Refresh** → `POST /api/v1/portfolio/mexc/refresh`, then
 *    `router.refresh()` re-renders the server component with fresh cached data.
 *  - **Disconnect** → `DELETE /api/v1/portfolio/mexc/disconnect`, then
 *    `router.refresh()` flips the server component back to the connect form.
 *
 * Both actions use inline fetch (no SWR) because they are one-shot mutations
 * whose result replaces the entire page state — `router.refresh()` handles
 * revalidation.
 */

interface PortfolioDashboardProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token: string | null;
  /** Initial cached portfolio data from the server component. */
  portfolio: PortfolioResponse | null;
  /** Masked API key preview to display in the header. */
  maskedKey: string | null;
}

export function PortfolioDashboard({
  token,
  portfolio,
  maskedKey,
}: PortfolioDashboardProps) {
  const router = useRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const balances = portfolio?.balances ?? [];
  const positions = portfolio?.positions ?? [];
  const trades = portfolio?.trades ?? [];
  const snapshot = portfolio?.snapshot ?? null;
  const isStale = portfolio?.stale ?? true;
  const lastRefreshed = portfolio?.last_refreshed ?? null;

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch("/api/v1/portfolio/mexc/refresh", {
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
          }`
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
        "Disconnect MEXC? This removes your stored API keys and all cached portfolio data."
      )
    ) {
      return;
    }
    setDisconnecting(true);
    setError(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch("/api/v1/portfolio/mexc/disconnect", {
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
          }`
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
          {snapshot && snapshot.total_balance_usd != null && (
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
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={refreshing || disconnecting}
            className="border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800 hover:text-slate-100"
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
            className="border-red-800/50 bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300"
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
          <BalancesTable balances={balances} />
        </TabsContent>
        <TabsContent value="positions">
          <PositionsTable positions={positions} />
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
