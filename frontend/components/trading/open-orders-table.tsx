"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import { Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { OrderResult } from "@/components/trading/order-ticket";

/**
 * OpenOrdersTable — lists open orders with cancel buttons.
 *
 * Fetches from `GET /api/v1/trading/{exchange}/orders/open`.
 * Cancel via `DELETE /api/v1/trading/{exchange}/order/{order_id}?symbol=...`.
 */

interface OpenOrdersTableProps {
  exchange: string;
  token: string | null;
  tradingEnabled: boolean;
  refreshInterval?: number;
}

export function OpenOrdersTable({
  exchange,
  token,
  tradingEnabled,
  refreshInterval = 15000,
}: OpenOrdersTableProps) {
  const fetcher = useCallback(async () => {
    const authToken = token ?? (await fetchToken());
    if (!authToken) return [];
    const res = await fetch(
      `/api/v1/trading/${exchange}/orders/open`,
      { headers: { Authorization: `Bearer ${authToken}` } },
    );
    if (!res.ok) return [];
    return res.json();
  }, [token, exchange]);

  const { data, isLoading, mutate } = useSWR<OrderResult[]>(
    token && tradingEnabled ? `open-orders-${exchange}` : null,
    fetcher,
    { refreshInterval },
  );

  const orders: OrderResult[] = data ?? [];
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  async function fetchToken(): Promise<string | null> {
    try {
      const res = await fetch("/api/auth/session");
      const data = await res.json();
      return data?.user?.accessToken ?? null;
    } catch {
      return null;
    }
  }

  async function handleCancel(orderId: string, symbol: string) {
    const authToken = await fetchToken();
    if (!authToken) return;
    setCancellingId(orderId);
    try {
      const res = await fetch(
        `/api/v1/trading/${exchange}/order/${orderId}?symbol=${encodeURIComponent(symbol)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${authToken}` },
        },
      );
      if (res.ok) {
        void mutate();
      }
    } catch {
      // ignore
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-100">Open Orders</h3>
        <Badge
          variant="outline"
          className="border-slate-700 bg-slate-900/60 text-slate-400"
        >
          {orders.length} pending
        </Badge>
      </div>

      {!tradingEnabled ? (
        <div className="py-6 text-center text-sm text-slate-500">
          Trading is disabled — enable it to view and cancel open orders.
        </div>
      ) : isLoading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
        </div>
      ) : orders.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">
          No open orders
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-2 py-2 font-medium">Symbol</th>
                <th className="px-2 py-2 font-medium">Side</th>
                <th className="px-2 py-2 font-medium">Type</th>
                <th className="px-2 py-2 font-medium text-right">Amount</th>
                <th className="px-2 py-2 font-medium text-right">Price</th>
                <th className="px-2 py-2 font-medium text-right">Filled</th>
                <th className="px-2 py-2 font-medium text-center">Status</th>
                <th className="px-2 py-2 font-medium text-center">Cancel</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr
                  key={order.id}
                  className="border-b border-slate-800/50 text-slate-300"
                >
                  <td className="px-2 py-2 font-mono text-xs">{order.symbol}</td>
                  <td className="px-2 py-2">
                    <span
                      className={cn(
                        "font-semibold",
                        order.side === "buy"
                          ? "text-emerald-400"
                          : "text-red-400",
                      )}
                    >
                      {order.side?.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-xs text-slate-400">
                    {order.type}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {order.amount}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {order.price ?? "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {order.filled} / {order.amount}
                  </td>
                  <td className="px-2 py-2 text-center">
                    <Badge
                      variant="outline"
                      className="border-slate-600 bg-slate-800/50 text-slate-400"
                    >
                      {order.status}
                    </Badge>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={cancellingId === order.id}
                      onClick={() => handleCancel(order.id, order.symbol)}
                      className="h-7 border-red-800/50 bg-red-500/10 px-2 text-xs text-red-400 hover:bg-red-500/20 hover:text-red-300"
                    >
                      {cancellingId === order.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <X className="h-3 w-3" />
                      )}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default OpenOrdersTable;
