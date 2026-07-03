"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import { AlertCircle, Loader2, X, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { PositionItem } from "@/lib/types";

/**
 * PositionManager — list open positions with Close + Leverage adjust.
 *
 * Fetches open positions from `GET /api/v1/portfolio/{exchange}` (cached data
 * from the portfolio router). Each position row shows symbol, side, size,
 * PnL, and provides:
 *  - **Close** button → `POST /api/v1/trading/{exchange}/position/close`
 *  - **Leverage** input → `POST /api/v1/trading/{exchange}/position/leverage`
 *
 * Both actions show a confirmation dialog before executing.
 */

interface PositionManagerProps {
  exchange: string;
  token: string | null;
  tradingEnabled: boolean;
  /** Polling interval for position refresh (ms). */
  refreshInterval?: number;
}

interface CloseDialogState {
  open: boolean;
  position: PositionItem | null;
}

interface LeverageDialogState {
  open: boolean;
  position: PositionItem | null;
  value: string;
}

export function PositionManager({
  exchange,
  token,
  tradingEnabled,
  refreshInterval = 15000,
}: PositionManagerProps) {
  // Fetch positions via SWR (uses the portfolio endpoint's cached data).
  const fetcher = useCallback(async () => {
    const authToken = token ?? (await fetchToken());
    if (!authToken) return null;
    const res = await fetch(`/api/v1/portfolio/${exchange}`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (!res.ok) return null;
    return res.json();
  }, [token, exchange]);

  const { data, error, isLoading, mutate } = useSWR(
    token ? `positions-${exchange}` : null,
    fetcher,
    { refreshInterval },
  );

  const positions: PositionItem[] = data?.positions ?? [];

  const [closeDialog, setCloseDialog] = useState<CloseDialogState>({
    open: false,
    position: null,
  });
  const [leverageDialog, setLeverageDialog] = useState<LeverageDialogState>({
    open: false,
    position: null,
    value: "",
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function fetchToken(): Promise<string | null> {
    try {
      const res = await fetch("/api/auth/session");
      const data = await res.json();
      return data?.user?.accessToken ?? null;
    } catch {
      return null;
    }
  }

  async function handleClosePosition() {
    const pos = closeDialog.position;
    if (!pos) return;
    const authToken = await fetchToken();
    if (!authToken) {
      setActionError("Not authenticated. Please log in again.");
      return;
    }

    setSubmitting(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/v1/trading/${exchange}/position/close`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          symbol: pos.symbol,
          side: pos.side,
        }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(mapError(res.status, detail));
      }
      const result = await res.json();
      setActionSuccess(result?.message || `Position ${pos.symbol} closed.`);
      setCloseDialog({ open: false, position: null });
      // Trigger SWR revalidation.
      void mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSetLeverage() {
    const pos = leverageDialog.position;
    if (!pos) return;
    const lev = parseInt(leverageDialog.value, 10);
    if (!lev || lev < 1 || lev > 125) {
      setActionError("Leverage must be between 1 and 125");
      return;
    }
    const authToken = await fetchToken();
    if (!authToken) {
      setActionError("Not authenticated. Please log in again.");
      return;
    }

    setSubmitting(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/v1/trading/${exchange}/position/leverage`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          symbol: pos.symbol,
          leverage: lev,
        }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(mapError(res.status, detail));
      }
      setActionSuccess(`Leverage set to ${lev}x for ${pos.symbol}`);
      setLeverageDialog({ open: false, position: null, value: "" });
      void mutate();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-100">Open Positions</h3>
        <Badge
          variant="outline"
          className="border-slate-700 bg-slate-900/60 text-slate-400"
        >
          {positions.length} active
        </Badge>
      </div>

      {actionError && (
        <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-xs text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{actionError}</span>
          <button
            onClick={() => setActionError(null)}
            className="ml-auto text-red-400 hover:text-red-300"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
      {actionSuccess && (
        <div className="flex items-start gap-2 rounded-md border border-emerald-800/50 bg-emerald-500/10 p-3 text-xs text-emerald-400">
          <span>{actionSuccess}</span>
          <button
            onClick={() => setActionSuccess(null)}
            className="ml-auto text-emerald-400 hover:text-emerald-300"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
        </div>
      ) : positions.length === 0 ? (
        <div className="py-8 text-center text-sm text-slate-500">
          No open positions
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-2 py-2 font-medium">Symbol</th>
                <th className="px-2 py-2 font-medium">Side</th>
                <th className="px-2 py-2 font-medium text-right">Size</th>
                <th className="px-2 py-2 font-medium text-right">Entry</th>
                <th className="px-2 py-2 font-medium text-right">Mark</th>
                <th className="px-2 py-2 font-medium text-right">PnL</th>
                <th className="px-2 py-2 font-medium text-center">Lev</th>
                <th className="px-2 py-2 font-medium text-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, i) => (
                <tr
                  key={`${pos.symbol}-${pos.side}-${i}`}
                  className="border-b border-slate-800/50 text-slate-300"
                >
                  <td className="px-2 py-2 font-mono text-xs">{pos.symbol}</td>
                  <td className="px-2 py-2">
                    <span
                      className={cn(
                        "font-semibold",
                        pos.side === "long" ? "text-emerald-400" : "text-red-400",
                      )}
                    >
                      {pos.side?.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {pos.size}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {pos.entry_price}
                  </td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {pos.mark_price}
                  </td>
                  <td
                    className={cn(
                      "px-2 py-2 text-right font-mono text-xs",
                      pos.pnl >= 0 ? "text-emerald-400" : "text-red-400",
                    )}
                  >
                    {pos.pnl >= 0 ? "+" : ""}
                    {pos.pnl?.toFixed(2)} ({pos.pnl_percent?.toFixed(2)}%)
                  </td>
                  <td className="px-2 py-2 text-center font-mono text-xs">
                    {pos.leverage}x
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center justify-center gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!tradingEnabled || submitting}
                        onClick={() =>
                          setLeverageDialog({
                            open: true,
                            position: pos,
                            value: String(pos.leverage ?? 1),
                          })
                        }
                        className="h-7 border-slate-700 bg-slate-900/60 px-2 text-xs text-slate-300 hover:bg-slate-800"
                      >
                        <Zap className="h-3 w-3" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!tradingEnabled || submitting}
                        onClick={() =>
                          setCloseDialog({ open: true, position: pos })
                        }
                        className="h-7 border-red-800/50 bg-red-500/10 px-2 text-xs text-red-400 hover:bg-red-500/20 hover:text-red-300"
                      >
                        Close
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Close position confirmation */}
      <Dialog open={closeDialog.open} onOpenChange={(o) => setCloseDialog({ open: o, position: closeDialog.position })}>
        <DialogContent className="border-slate-800 bg-slate-900 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-slate-100">Close Position</DialogTitle>
            <DialogDescription className="text-slate-400">
              This will close your {closeDialog.position?.side} position on{" "}
              {closeDialog.position?.symbol} at market price.
            </DialogDescription>
          </DialogHeader>
          {closeDialog.position && (
            <div className="space-y-2 text-sm text-slate-300">
              <div className="flex justify-between">
                <span className="text-slate-500">Symbol</span>
                <span className="font-mono">{closeDialog.position.symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Side</span>
                <span className={closeDialog.position.side === "long" ? "text-emerald-400" : "text-red-400"}>
                  {closeDialog.position.side?.toUpperCase()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Size</span>
                <span className="font-mono">{closeDialog.position.size}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Current PnL</span>
                <span className={cn("font-mono", closeDialog.position.pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {closeDialog.position.pnl >= 0 ? "+" : ""}
                  {closeDialog.position.pnl?.toFixed(2)} ({closeDialog.position.pnl_percent?.toFixed(2)}%)
                </span>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCloseDialog({ open: false, position: null })}
              disabled={submitting}
              className="min-h-11 border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800"
            >
              Cancel
            </Button>
            <Button
              onClick={handleClosePosition}
              disabled={submitting}
              className="min-h-11 bg-red-600 font-semibold text-white hover:bg-red-700"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Confirm Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Leverage adjustment dialog */}
      <Dialog
        open={leverageDialog.open}
        onOpenChange={(o) => setLeverageDialog((prev) => ({ ...prev, open: o }))}
      >
        <DialogContent className="border-slate-800 bg-slate-900 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-slate-100">Adjust Leverage</DialogTitle>
            <DialogDescription className="text-slate-400">
              Set the leverage for {leverageDialog.position?.symbol}.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="pm-lev" className="text-xs text-slate-400">
              Leverage (1–125)
            </Label>
            <Input
              id="pm-lev"
              type="number"
              min={1}
              max={125}
              step={1}
              value={leverageDialog.value}
              onChange={(e) =>
                setLeverageDialog((prev) => ({ ...prev, value: e.target.value }))
              }
              disabled={submitting}
              className="border-slate-700 bg-slate-950/50 text-sm text-slate-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setLeverageDialog({ open: false, position: null, value: "" })}
              disabled={submitting}
              className="min-h-11 border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800"
            >
              Cancel
            </Button>
            <Button
              onClick={handleSetLeverage}
              disabled={submitting}
              className="min-h-11 bg-emerald-600 font-semibold text-white hover:bg-emerald-700"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Set Leverage
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default PositionManager;

function mapError(status: number, detail: string): string {
  switch (status) {
    case 400:
      return `Rejected: ${detail || "Invalid parameters"}`;
    case 403:
      return "Trading is disabled on the backend";
    case 404:
      return detail || "Position or exchange not found";
    case 429:
      return "Rate limited by the exchange. Please wait and try again.";
    case 502:
      return detail || "Exchange error. Try reconnecting your account.";
    default:
      return `Action failed: ${status} ${detail}`.trim();
  }
}
