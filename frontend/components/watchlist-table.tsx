"use client";

import { useMemo, useRef, useState } from "react";
import {
  Bell,
  BellRing,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import useSWR, { useSWRConfig } from "swr";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LivePriceBadge } from "@/components/live-price-badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { useClientToken } from "@/hooks/use-client-token";

import type {
  PriceAlertResponse,
  PriceAlertListResponse,
  WatchlistPair,
  WatchlistResponse,
} from "@/lib/types";

/**
 * WatchlistTable — Client Component.
 *
 * Self-contained watchlist manager with:
 *  - Live price streaming (SSE) per pair
 *  - Price alert creation (bell icon → dialog)
 *  - Active alert count badges per pair
 *  - Add / remove / scan mutations
 *
 * The signed-in user's JWT access token is passed in from the (Server
 * Component) parent page; all client-side fetches attach it as a Bearer
 * header. Relative ``/api/v1/...`` paths are proxied through the Next.js
 * rewrites in ``next.config.ts``.
 */

const WATCHLIST_KEY = "/api/v1/watchlist";
const ALERTS_KEY = "/api/v1/alerts/price?status=active";

/** Fetcher used by SWR. */
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

  // ── Active price alerts (for badge counts) ──────────────────────────────
  const clientToken = useClientToken();
  const effectiveToken = clientToken ?? token;

  const { data: alertsData } = useSWR<PriceAlertListResponse>(
    effectiveToken ? [ALERTS_KEY, effectiveToken] : null,
    ([url, tok]: [string, string | null]) =>
      fetcher<PriceAlertListResponse>(url, tok)
  );

  // Build a map of symbol → active alert count
  const alertCountMap = useMemo(() => {
    const map: Record<string, number> = {};
    if (alertsData?.alerts) {
      for (const a of alertsData.alerts) {
        const sym = a.symbol.toUpperCase();
        map[sym] = (map[sym] ?? 0) + 1;
      }
    }
    return map;
  }, [alertsData]);

  // ── Watchlist mutations ──────────────────────────────────────────────────
  const {
    trigger: addPair,
    isMutating: isAdding,
    error: addError,
  } = useMutation<WatchlistPair, { pair: string }>(WATCHLIST_KEY, "POST", {
    revalidateKeys: [WATCHLIST_KEY],
  });

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

  // ── Live price streaming for watchlist pairs ───────────────────────────
  const streamSymbols = useMemo(() => pairs.map((p) => p.pair), [pairs]);
  const { prices, isConnected } = usePriceStream(streamSymbols, effectiveToken);

  // Snapshot the "anchor" price for each symbol — the first price we see —
  // so the % change reflects movement since the stream started, rather than
  // just the last tick (which can be noisy and reset on reconnect).
  const anchorPriceRef = useRef<Record<string, number>>({});

  /**
   * Given a symbol and its current LivePrice tick, compute the percent
   * change relative to the anchored first tick. Returns null until a
   * second tick arrives (so we have something to compare against).
   */
  function getChangePct(symbol: string, live?: LivePrice): number | null {
    if (!live) return null;
    const sym = symbol.toUpperCase();
    const anchor = anchorPriceRef.current[sym];
    // Set anchor on first seen tick
    if (anchor == null) {
      anchorPriceRef.current[sym] = live.price;
      return null;
    }
    if (anchor === 0) return null;
    return ((live.price - anchor) / anchor) * 100;
  }

  // ── Alert dialog state ───────────────────────────────────────────────────
  const [alertDialogOpen, setAlertDialogOpen] = useState(false);
  const [alertPair, setAlertPair] = useState<WatchlistPair | null>(null);
  const [alertPrice, setAlertPrice] = useState("");
  const [alertDirection, setAlertDirection] = useState("above");
  const [alertMessage, setAlertMessage] = useState("");
  const [alertSubmitting, setAlertSubmitting] = useState(false);
  const [alertError, setAlertError] = useState<string | null>(null);
  const [alertSuccess, setAlertSuccess] = useState<string | null>(null);

  // Test Telegram alert state
  const [testingTelegram, setTestingTelegram] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);

  function openAlertDialog(pair: WatchlistPair) {
    setAlertPair(pair);
    // Pre-fill with current live price if available
    const livePrice = prices[pair.pair.toUpperCase()];
    setAlertPrice(livePrice ? String(livePrice.price) : "");
    setAlertDirection("above");
    setAlertMessage("");
    setAlertError(null);
    setAlertSuccess(null);
    setAlertDialogOpen(true);
  }

  async function handleCreateAlert(e: React.FormEvent) {
    e.preventDefault();
    if (!alertPair) return;
    const price = parseFloat(alertPrice);
    if (isNaN(price) || price <= 0) {
      setAlertError("Enter a valid price greater than 0");
      return;
    }
    setAlertSubmitting(true);
    setAlertError(null);
    setAlertSuccess(null);
    try {
      const headers: HeadersInit = { "Content-Type": "application/json" };
      if (effectiveToken) headers.Authorization = `Bearer ${effectiveToken}`;
      const res = await fetch("/api/v1/alerts/price", {
        method: "POST",
        headers,
        body: JSON.stringify({
          symbol: alertPair.pair,
          price_level: price,
          direction: alertDirection,
          alert_type: "price",
          message: alertMessage.trim() || null,
        }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(
          `Failed to create alert: ${res.status}${detail ? ` — ${detail}` : ""}`
        );
      }
      setAlertSuccess(
        `Alert set: ${alertPair.pair} ${alertDirection} ${price}`
      );
      // Revalidate alerts cache so badge count updates
      await mutateCache(ALERTS_KEY);
    } catch (err) {
      setAlertError(err instanceof Error ? err.message : String(err));
    } finally {
      setAlertSubmitting(false);
    }
  }

  async function handleTestTelegram() {
    setTestingTelegram(true);
    setTestResult(null);
    try {
      const headers: HeadersInit = {};
      if (effectiveToken) headers.Authorization = `Bearer ${effectiveToken}`;
      const res = await fetch("/api/v1/alerts/price/test", {
        method: "POST",
        headers,
      });
      if (!res.ok) {
        throw new Error(`Test failed: ${res.status}`);
      }
      const data = await res.json();
      setTestResult(data);
    } catch (err) {
      setTestResult({ ok: false, error: err instanceof Error ? err.message : String(err) });
    } finally {
      setTestingTelegram(false);
    }
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
      setRowMessage({ id: pair.id, type: "success", text: `Removed ${pair.pair}` });
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

        <div className="flex items-center gap-3">
          {/* Live connection indicator */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide transition-colors ${
              isConnected
                ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                : "border-slate-700 bg-slate-800/50 text-slate-500"
            }`}
            title={
              isConnected
                ? "SSE price stream connected"
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
                  isConnected ? "bg-emerald-400" : "bg-slate-500"
                }`}
              />
            </span>
            {isConnected ? "Live" : "Offline"}
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
        <p className="text-xs text-red-400">{addError.message}</p>
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
              <TableHead className="text-slate-400">Alerts</TableHead>
              <TableHead className="text-slate-400">Added</TableHead>
              <TableHead className="text-slate-400">Status</TableHead>
              <TableHead className="text-right text-slate-400">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-slate-500"
                >
                  Loading watchlist…
                </TableCell>
              </TableRow>
            ) : error ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-red-400"
                >
                  Failed to load watchlist: {error.message}
                </TableCell>
              </TableRow>
            ) : pairs.length === 0 ? (
              <TableRow className="border-slate-800">
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-slate-500"
                >
                  No pairs in your watchlist yet. Add one above to get started.
                </TableCell>
              </TableRow>
            ) : (
              pairs.map((pair) => {
                const isRowBusy = rowActionId === pair.id;
                const rowMsg = rowMessage?.id === pair.id ? rowMessage : null;
                const created = new Date(pair.created_at).toLocaleString(
                  undefined,
                  { dateStyle: "medium", timeStyle: "short" }
                );
                const livePrice = prices[pair.pair.toUpperCase()];
                const alertCount = alertCountMap[pair.pair.toUpperCase()] ?? 0;
                const changePct = getChangePct(pair.pair, livePrice);
                return (
                  <TableRow key={pair.id} className="border-slate-800">
                    <TableCell className="font-medium text-slate-100">
                      {pair.pair}
                    </TableCell>
                    <TableCell>
                      <LivePriceBadge
                        symbol={pair.pair}
                        price={livePrice}
                        connected={isConnected}
                        precision={pair.pair.includes("BTC") ? 0 : 2}
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
                    <TableCell>
                      {alertCount > 0 ? (
                        <Badge
                          variant="outline"
                          className="border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                        >
                          <BellRing className="mr-1 h-3 w-3" />
                          {alertCount} active
                        </Badge>
                      ) : (
                        <span className="text-xs text-slate-600">—</span>
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
                          onClick={() => openAlertDialog(pair)}
                          disabled={isRowBusy}
                          className="text-slate-300 hover:bg-slate-800 hover:text-slate-100"
                          title={`Set price alert for ${pair.pair}`}
                        >
                          <Bell className="h-4 w-4" />
                          <span className="sr-only">Set alert for {pair.pair}</span>
                        </Button>
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

      {/* ── Alert Creation Dialog ─────────────────────────────────────────── */}
      <Dialog open={alertDialogOpen} onOpenChange={setAlertDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5 text-emerald-400" />
              Set Price Alert
            </DialogTitle>
            <DialogDescription>
              {alertPair && (
                <>
                  Get a Telegram notification when{" "}
                  <span className="font-semibold text-slate-200">
                    {alertPair.pair}
                  </span>{" "}
                  crosses your target price.
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleCreateAlert} className="flex flex-col gap-4">
            {/* Current price hint */}
            {alertPair && prices[alertPair.pair.toUpperCase()] && (
              <div className="rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs text-slate-400">
                Current price:{" "}
                <span className="font-mono text-slate-200">
                  {prices[alertPair.pair.toUpperCase()].price.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </div>
            )}

            {/* Price level */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="alert-price" className="text-slate-200">
                Target Price
              </Label>
              <Input
                id="alert-price"
                type="number"
                step="any"
                min="0"
                placeholder="e.g. 65000"
                value={alertPrice}
                onChange={(e) => setAlertPrice(e.target.value)}
                className="border-slate-700 bg-slate-950/50 text-slate-100"
                disabled={alertSubmitting}
                autoFocus
              />
            </div>

            {/* Direction */}
            <div className="flex flex-col gap-1.5">
              <Label className="text-slate-200">Trigger When Price Goes</Label>
              <Select
                value={alertDirection}
                onValueChange={setAlertDirection}
                disabled={alertSubmitting}
              >
                <SelectTrigger className="border-slate-700 bg-slate-950/50 text-slate-100">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="above">Above (price rises to target)</SelectItem>
                  <SelectItem value="below">Below (price drops to target)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Optional message */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="alert-message" className="text-slate-200">
                Note (optional)
              </Label>
              <Input
                id="alert-message"
                type="text"
                placeholder="e.g. Take profit target"
                value={alertMessage}
                onChange={(e) => setAlertMessage(e.target.value)}
                maxLength={500}
                className="border-slate-700 bg-slate-950/50 text-slate-100"
                disabled={alertSubmitting}
              />
            </div>

            {/* Error / success messages */}
            {alertError && (
              <p className="text-xs text-red-400">{alertError}</p>
            )}
            {alertSuccess && (
              <p className="text-xs text-emerald-400">{alertSuccess}</p>
            )}

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleTestTelegram}
                disabled={testingTelegram || alertSubmitting}
                className="border-slate-700 text-slate-200"
              >
                {testingTelegram ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Bell className="h-4 w-4" />
                )}
                Test Telegram
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={alertSubmitting || !alertPrice.trim()}
                className="bg-emerald-600 text-white hover:bg-emerald-500"
              >
                {alertSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <BellRing className="h-4 w-4" />
                )}
                Create Alert
              </Button>
            </DialogFooter>
          </form>

          {/* Test Telegram result */}
          {testResult && (
            <div
              className={`rounded-md border p-3 text-xs ${
                testResult.ok
                  ? "border-emerald-800/50 bg-emerald-500/10 text-emerald-400"
                  : "border-red-800/50 bg-red-500/10 text-red-400"
              }`}
            >
              {testResult.ok
                ? "✅ Test message sent to your Telegram! Check your chat."
                : `❌ ${testResult.error ?? "Test failed. Check your Telegram channel settings."}`}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default WatchlistTable;
