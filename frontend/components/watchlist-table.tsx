"use client";

import { useState } from "react";
import { Loader2, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import useSWR, { useSWRConfig } from "swr";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMutation } from "@/hooks/use-mutation";
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
    ([url, tok]) => fetcher<WatchlistResponse>(url, tok)
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
              <TableHead className="text-slate-400">Added</TableHead>
              <TableHead className="text-slate-400">Status</TableHead>
              <TableHead className="text-right text-slate-400">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={4}
                  className="py-8 text-center text-slate-500"
                >
                  Loading watchlist…
                </TableCell>
              </TableRow>
            ) : error ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={4}
                  className="py-8 text-center text-red-400"
                >
                  Failed to load watchlist: {error.message}
                </TableCell>
              </TableRow>
            ) : pairs.length === 0 ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={4}
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
                return (
                  <TableRow key={pair.id} className="border-slate-800">
                    <TableCell className="font-medium text-slate-100">
                      {pair.pair}
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
