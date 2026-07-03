"use client";

import { useMemo, useRef, useState } from "react";
import { Loader2, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import useSWR, { useSWRConfig } from "swr";
import { useClientToken } from "@/hooks/use-client-token";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LivePriceBadge } from "@/components/live-price-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMutation } from "@/hooks/use-mutation";
import { usePriceStream, type LivePrice } from "@/hooks/use-price-stream";
import type { WatchlistPair, WatchlistResponse } from "@/lib/types";

/**
 * WatchlistTable — Client Component.
 *
 * A self-contained watchlist manager that fetches its own data via SWR and
 * performs add / remove / scan mutations through the `useMutation` hook.
 *
 * The signed-in user's JWT access token is passed in from the (Server
 * Component) parent page; all client-side fetches attach it as a Bearer
 * header. Relative `/api/v1/...` paths are proxied through the Next.js
 * rewrites in `next.config.ts`, so the public API URL is optional.
 *
 * Mutations revalidate the SWR `/api/v1/watchlist` cache key so the table
 * stays in sync automatically.
 *
 * Live prices are streamed over SSE for every watchlist pair and rendered in
 * a dedicated "Live Price" column with a flashing LivePriceBadge. A "LIVE"
 * pill at the top of the table indicates the stream connection state, and
 * each row shows a 24h-style % change comparing the latest tick to the
 * previous one (green for up, red for down).
 *
 * NOTE: The backend stores trading pairs under a `pair` field (not
 * `symbol`), and the scan endpoint is `POST /api/v1/scan/{symbol}` (path
 * parameter, no body). This component follows the real backend contract.
 */

const WATCHLIST_KEY = "/api/v1/watchlist";

/** Fetcher used by SWR for the watchlist list endpoint. */
async function fetcher<T>(url: string, token: string | null): Promise<T> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    throw new Error(`GET ${url} failed: ${res.status} ${res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

interface WatchlistTableProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token: string | null;
}

export function WatchlistTable({ token }: WatchlistTableProps) {
  const { data, error, isLoading } = useSWR<WatchlistResponse>(
    token ? [WATCHLIST_KEY, token] : null,
    ([url, tok]: [string, string | null]) =>
      fetcher<WatchlistResponse>(url, tok)
  );

  // Add a new pair — POST /api/v1/watchlist with body { pair }.
  const {
    trigger: addPair,
    isMutating: isAdding,
    error: addError,
  } = useMutation<WatchlistPair, { pair: string }>(WATCHLIST_KEY, "POST", {
    revalidateKeys: [WATCHLIST_KEY],
  });

  // Remove a pair — DELETE /api/v1/watchlist/{id} (no body).
  const { mutate: mutateCache } = useSWRConfig();

  const [newSymbol, setNewSymbol] = useState("");
  const [rowActionId, setRowActionId] = useState<number | null>(null);
  const [rowMessage, setRowMessage] = useState<{
    id: number;
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanSummary, setScanSummary] = useState<{
    succeeded: number;
    failed: number;
    errors: string[];
  } | null>(null);

  const pairs = data?.pairs ?? [];

  // ── Live price streaming for watchlist pairs ───────────────────────
  // Subscribe to SSE price updates for every pair in the watchlist.
  // The hook debounces symbol-list changes and auto-reconnects on drop.
  const streamSymbols = useMemo(
    () => pairs.map((p) => p.pair),
    [pairs],
  );
  // Get token client-side via direct session fetch
  const clientToken = useClientToken();

  const { prices, isConnected } = usePriceStream(streamSymbols, clientToken ?? token);

  // Track the previous price per symbol so we can show a +X% / -X% change.
  // We keep this in a ref (not state) to avoid re-renders on every tick; the
  // derived change value is computed from `prices` during render.
  const prevPriceRef = useRef<Record<string, number>>({});

  // Snapshot the "anchor" price for each symbol — the first price we see —
  // so the % change reflects movement since the stream started, not just the
  // last tick (which can be noisy and reset on reconnect).
  const anchorPriceRef = useRef<Record<string, number>>({});

  /**
   * Given a symbol and its current LivePrice tick, compute the percent
   * change relative to the anchored first tick. Returns null when there's
   * no previous tick to compare against.
   */
  function getChangePct(symbol: string, live?: LivePrice): number | null {
    if (!live) return null;
    const sym = symbol.toUpperCase();
    const anchor = anchorPriceRef.current[sym];
    // Set anchor on first seen tick
    if (anchor == null) {
      anchorPriceRef.current[sym] = live.price;
      prevPriceRef.current[sym] = live.price;
      return null;
    }
    if (anchor === 0) return null;
    return ((live.price - anchor) / anchor) * 100;
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;
    try {
      await addPair({ pair: symbol }, token);
      setNewSymbol("");
    } catch {
      // Error surfaced inline via `addError`.
    }
  }

  async function handleRemove(pair: WatchlistPair) {
    setRowActionId(pair.id);
    setRowMessage(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`${WATCHLIST_KEY}/${pair.id}`, {
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
          `Remove failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`
        );
      }
      await mutateCache(WATCHLIST_KEY);
      setRowMessage({
        id: pair.id,
        type: "success",
        text: `Removed ${pair.pair}`,
      });
    } catch (err) {
      setRowMessage({
        id: pair.id,
        type: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRowActionId(null);
    }
  }

  async function handleScanOne(pair: WatchlistPair) {
    setRowActionId(pair.id);
    setRowMessage(null);
    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/scan/${pair.pair}`, {
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
          `Scan failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`
        );
      }
      const result = await res.json();
      const score = result?.confluence_score ?? result?.overall_score;
      setRowMessage({
        id: pair.id,
        type: "success",
        text:
          score !== undefined && score !== null
            ? `${pair.pair} scanned — confluence ${score}`
            : `${pair.pair} scanned`,
      });
    } catch (err) {
      setRowMessage({
        id: pair.id,
        type: "error",
        text: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRowActionId(null);
    }
  }

  /** Run the scan endpoint once per watchlist symbol, in parallel. */
  async function handleScanAll() {
    if (pairs.length === 0 || scanning) return;
    setScanning(true);
    setScanSummary(null);

    const headers: HeadersInit = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    const results = await Promise.allSettled(
      pairs.map(async (pair) => {
        const res = await fetch(`/api/v1/scan/${pair.pair}`, {
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
            `${pair.pair}: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`
          );
        }
        return res.json();
      })
    );

    const succeeded = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.filter((r) => r.status === "rejected").length;
    const errors = results
      .map((r, i) =>
        r.status === "rejected"
          ? `${pairs[i].pair}: ${r.reason instanceof Error ? r.reason.message : String(r.reason)}`
          : null
      )
      .filter((e): e is string => e !== null);

    setScanSummary({ succeeded, failed, errors });
    setScanning(false);
  }

  // Determine if any prices are flowing (used for the header pill).
  const hasLivePrices = Object.keys(prices).length > 0;
  const liveLabel = isConnected ? "LIVE" : hasLivePrices ? "IDLE" : "OFFLINE";

  return (
    <div className="flex flex-col gap-4">
      {/* Add pair form + scan-all action */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <form onSubmit={handleAdd} className="flex items-end gap-2">
          <div className="flex flex-col gap-1">
            <label
              htmlFor="add-pair"
              className="text-xs font-medium text-slate-400"
            >
              Add Pair
            </label>
            <Input
              id="add-pair"
              placeholder="e.g. BTCUSDT"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              className="w-48 border-slate-700 bg-slate-900 text-slate-100"
              disabled={isAdding}
              autoComplete="off"
            />
          </div>
          <Button type="submit" size="sm" disabled={isAdding || !newSymbol.trim()}>
            {isAdding ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add
          </Button>
        </form>

        <div className="flex items-center gap-3">
          {/* Live connection indicator */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide transition-colors ${
              isConnected
                ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                : hasLivePrices
                  ? "border-amber-700/40 bg-amber-500/10 text-amber-400"
                  : "border-slate-700 bg-slate-800/50 text-slate-500"
            }`}
            title={
              isConnected
                ? "SSE price stream connected"
                : hasLivePrices
                  ? "Stream idle — last prices shown"
                  : "Price stream offline"
            }
          >
            <span className="relative flex h-2 w-2">
              {isConnected && (
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                  style={{ animationDuration: "1.5s" }}
                />
              )}
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${
                  isConnected
                    ? "bg-emerald-400"
                    : hasLivePrices
                      ? "bg-amber-400"
                      : "bg-slate-500"
                }`}
              />
            </span>
            {liveLabel}
          </span>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleScanAll}
            disabled={scanning || pairs.length === 0}
            className="border-slate-700 text-slate-200 hover:bg-slate-800"
          >
            {scanning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Scan All
          </Button>
        </div>
      </div>

      {/* Inline error / status messages */}
      {addError && (
        <p className="text-xs text-red-400">
          {addError.message}
        </p>
      )}
      {scanSummary && (
        <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3 text-xs">
          <p className="text-slate-300">
            Scan complete —{" "}
            <span className="text-emerald-400">{scanSummary.succeeded} succeeded</span>
            {scanSummary.failed > 0 && (
              <>
                {", "}
                <span className="text-red-400">{scanSummary.failed} failed</span>
              </>
            )}
            {"."}
          </p>
          {scanSummary.errors.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-slate-500">
              {scanSummary.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Watchlist table */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60">
        <Table>
          <TableHeader>
            <TableRow className="border-slate-800 hover:bg-transparent">
              <TableHead className="text-slate-400">Symbol</TableHead>
              <TableHead className="text-slate-400">
                <span className="inline-flex items-center gap-1.5">
                  Live Price
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
              </TableHead>
              <TableHead className="text-right text-slate-400">Change</TableHead>
              <TableHead className="text-slate-400">Added</TableHead>
              <TableHead className="text-slate-400">Status</TableHead>
              <TableHead className="text-right text-slate-400">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-slate-500"
                >
                  Loading watchlist…
                </TableCell>
              </TableRow>
            ) : error ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-red-400"
                >
                  Failed to load watchlist: {error.message}
                </TableCell>
              </TableRow>
            ) : pairs.length === 0 ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={6}
                  className="py-8 text-center text-slate-500"
                >
                  No pairs in your watchlist yet. Add one above to get started.
                </TableCell>
              </TableRow>
            ) : (
              pairs.map((pair) => {
                const isRowBusy = rowActionId === pair.id;
                const rowMsg =
                  rowMessage?.id === pair.id ? rowMessage : null;
                const created = new Date(pair.created_at).toLocaleString(
                  undefined,
                  { dateStyle: "medium", timeStyle: "short" }
                );
                const liveTick = prices[pair.pair.toUpperCase()];
                const changePct = getChangePct(pair.pair, liveTick);
                return (
                  <TableRow key={pair.id} className="border-slate-800">
                    <TableCell className="font-medium text-slate-100">
                      {pair.pair}
                    </TableCell>
                    <TableCell>
                      <LivePriceBadge
                        symbol=""
                        price={liveTick}
                        connected={isConnected}
                        precision={2}
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      {changePct == null ? (
                        <span className="text-slate-600">—</span>
                      ) : (
                        <span
                          className={`font-mono tabular-nums text-xs font-semibold ${
                            changePct >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {changePct >= 0 ? "+" : ""}
                          {changePct.toFixed(2)}%
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-slate-400">{created}</TableCell>
                    <TableCell className="text-slate-400">
                      {pair.status}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleScanOne(pair)}
                          disabled={isRowBusy}
                          className="text-slate-300 hover:bg-slate-800 hover:text-slate-100"
                          title={`Scan ${pair.pair}`}
                        >
                          {isRowBusy ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Search className="h-4 w-4" />
                          )}
                          <span className="sr-only">Scan {pair.pair}</span>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRemove(pair)}
                          disabled={isRowBusy}
                          className="text-red-400 hover:bg-red-500/10 hover:text-red-300"
                          title={`Remove ${pair.pair}`}
                        >
                          <Trash2 className="h-4 w-4" />
                          <span className="sr-only">Remove {pair.pair}</span>
                        </Button>
                      </div>
                      {rowMsg && (
                        <p
                          className={`mt-1 text-xs ${rowMsg.type === "success" ? "text-emerald-400" : "text-red-400"}`}
                        >
                          {rowMsg.text}
                        </p>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export default WatchlistTable;
