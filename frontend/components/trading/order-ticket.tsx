"use client";

import { useState, useMemo } from "react";
import { AlertCircle, Loader2, ShoppingCart } from "lucide-react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * OrderTicket — order placement form.
 *
 * Fields: symbol, type (limit/market), side (buy=green/sell=red), amount,
 * price (disabled for market), reduce-only checkbox, leverage slider.
 *
 * Shows a live order summary (cost = amount × price, margin = cost / leverage).
 * Submit opens a confirmation dialog before placing the order via
 * `POST /api/v1/trading/{exchange}/order`.
 *
 * Error handling maps common HTTP status codes to user-friendly messages
 * (insufficient margin, rate limit, invalid credentials, etc.).
 */

type OrderType = "limit" | "market";
type OrderSide = "buy" | "sell";

interface PlaceOrderBody {
  symbol: string;
  type: OrderType;
  side: OrderSide;
  amount: number;
  price?: number | null;
  reduce_only: boolean;
  leverage?: number | null;
}

export interface OrderResult {
  id: string;
  symbol: string;
  type: string;
  side: string;
  amount: number;
  price?: number | null;
  filled: number;
  remaining: number;
  status: string;
  timestamp?: number | null;
}

interface OrderTicketProps {
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
  /** JWT access token (client-side fetch fallback used if null). */
  token: string | null;
  /** Whether trading is enabled on the backend. */
  tradingEnabled: boolean;
  /** Optional default symbol to pre-fill. */
  defaultSymbol?: string;
  /** Called after a successful order placement. */
  onOrderPlaced?: () => void;
}

const ALLOWED_EXCHANGES = ["mexc", "binance", "bybit"];

export function OrderTicket({
  exchange,
  token,
  tradingEnabled,
  defaultSymbol = "",
  onOrderPlaced,
}: OrderTicketProps) {
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [side, setSide] = useState<OrderSide>("buy");
  const [amount, setAmount] = useState("");
  const [price, setPrice] = useState("");
  const [reduceOnly, setReduceOnly] = useState(false);
  const [leverage, setLeverage] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isLimit = orderType === "limit";

  // Live order summary: cost and margin required.
  const summary = useMemo(() => {
    const amt = parseFloat(amount);
    const px = isLimit ? parseFloat(price) : parseFloat(price);
    if (!amt || amt <= 0) return null;
    if (isLimit && (!px || px <= 0)) return null;
    const effectivePrice = isLimit ? px : px || 0;
    const cost = amt * effectivePrice;
    const margin = leverage > 0 ? cost / leverage : cost;
    return { cost, margin, price: effectivePrice };
  }, [amount, price, isLimit, leverage]);

  const canSubmit = useMemo(() => {
    if (!tradingEnabled) return false;
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return false;
    if (isLimit) {
      const px = parseFloat(price);
      if (!px || px <= 0) return false;
    }
    return true;
  }, [amount, price, isLimit, tradingEnabled]);

  async function fetchToken(): Promise<string | null> {
    if (token) return token;
    try {
      const res = await fetch("/api/auth/session");
      const data = await res.json();
      return data?.user?.accessToken ?? null;
    } catch {
      return null;
    }
  }

  function handleSubmitClick() {
    setError(null);
    setSuccess(null);
    if (!canSubmit) return;
    setConfirmOpen(true);
  }

  async function handleConfirmPlace() {
    setConfirmOpen(false);
    const authToken = await fetchToken();
    if (!authToken) {
      setError("Not authenticated. Please log in again.");
      return;
    }

    const body: PlaceOrderBody = {
      symbol: symbol.trim().toUpperCase(),
      type: orderType,
      side,
      amount: parseFloat(amount),
      price: isLimit ? parseFloat(price) : null,
      reduce_only: reduceOnly,
      leverage: leverage > 1 ? leverage : null,
    };

    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/trading/${exchange}/order`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        let detail = "";
        try {
          const errBody = await res.json();
          detail = errBody?.detail ?? "";
        } catch {
          /* no body */
        }
        const friendly = mapOrderError(res.status, detail);
        throw new Error(friendly);
      }

      const result: OrderResult = await res.json();
      setSuccess(
        `Order placed: ${result.side.toUpperCase()} ${result.amount} ${result.symbol} @ ${
          result.price ?? "market"
        } — ID: ${result.id}`,
      );
      // Reset amount/price but keep symbol/type/side.
      setAmount("");
      setPrice("");
      onOrderPlaced?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-100">Order Ticket</h3>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="border-slate-700 bg-slate-900/60 text-slate-400"
          >
            {exchange.toUpperCase()}
          </Badge>
          {tradingEnabled ? (
            <Badge
              variant="outline"
              className="border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
            >
              Live
            </Badge>
          ) : (
            <Badge
              variant="outline"
              className="border-amber-700/50 bg-amber-500/10 text-amber-400"
            >
              Disabled
            </Badge>
          )}
        </div>
      </div>

      {!tradingEnabled && (
        <div className="rounded-md border border-amber-800/50 bg-amber-500/10 p-3 text-xs text-amber-400">
          Trading is disabled. Set <code className="font-mono">MIRAJ_TRADING_ENABLED=true</code> in the backend
          environment to enable live order execution.
        </div>
      )}

      {/* Symbol + Type */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ot-symbol" className="text-xs text-slate-400">
            Symbol
          </Label>
          <Input
            id="ot-symbol"
            type="text"
            placeholder="BTC/USDT:USDT"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            disabled={submitting}
            className="border-slate-700 bg-slate-950/50 text-sm text-slate-100 placeholder:text-slate-600"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ot-type" className="text-xs text-slate-400">
            Type
          </Label>
          <Select
            value={orderType}
            onValueChange={(v) => setOrderType(v as OrderType)}
            disabled={submitting}
          >
            <SelectTrigger
              id="ot-type"
              className="border-slate-700 bg-slate-950/50 text-sm text-slate-100"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="border-slate-700 bg-slate-900">
              <SelectItem value="limit" className="text-slate-200">
                Limit
              </SelectItem>
              <SelectItem value="market" className="text-slate-200">
                Market
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Side toggle */}
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => setSide("buy")}
          disabled={submitting}
          className={cn(
            "min-h-11 rounded-md border px-4 py-2 text-sm font-semibold transition-colors",
            side === "buy"
              ? "border-emerald-600 bg-emerald-600/20 text-emerald-400"
              : "border-slate-700 bg-slate-950/50 text-slate-400 hover:bg-slate-800",
          )}
        >
          Buy / Long
        </button>
        <button
          type="button"
          onClick={() => setSide("sell")}
          disabled={submitting}
          className={cn(
            "min-h-11 rounded-md border px-4 py-2 text-sm font-semibold transition-colors",
            side === "sell"
              ? "border-red-600 bg-red-600/20 text-red-400"
              : "border-slate-700 bg-slate-950/50 text-slate-400 hover:bg-slate-800",
          )}
        >
          Sell / Short
        </button>
      </div>

      {/* Amount + Price */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ot-amount" className="text-xs text-slate-400">
            Amount
          </Label>
          <Input
            id="ot-amount"
            type="number"
            step="any"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            disabled={submitting}
            className="border-slate-700 bg-slate-950/50 text-sm text-slate-100 placeholder:text-slate-600"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="ot-price" className="text-xs text-slate-400">
            Price {isLimit ? "" : "(market)"}
          </Label>
          <Input
            id="ot-price"
            type="number"
            step="any"
            placeholder={isLimit ? "0.00" : "Market price"}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            disabled={submitting || !isLimit}
            className={cn(
              "border-slate-700 bg-slate-950/50 text-sm text-slate-100 placeholder:text-slate-600",
              !isLimit && "text-slate-600",
            )}
          />
        </div>
      </div>

      {/* Leverage slider */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor="ot-leverage" className="text-xs text-slate-400">
            Leverage
          </Label>
          <span className="font-mono text-xs text-slate-300">{leverage}x</span>
        </div>
        <input
          id="ot-leverage"
          type="range"
          min={1}
          max={100}
          step={1}
          value={leverage}
          onChange={(e) => setLeverage(parseInt(e.target.value, 10))}
          disabled={submitting}
          className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-700 accent-emerald-500"
        />
      </div>

      {/* Reduce-only checkbox */}
      <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
        <input
          type="checkbox"
          checked={reduceOnly}
          onChange={(e) => setReduceOnly(e.target.checked)}
          disabled={submitting}
          className="h-4 w-4 rounded border-slate-700 bg-slate-950/50 accent-emerald-500"
        />
        Reduce only (can only decrease an existing position)
      </label>

      {/* Order summary */}
      {summary && (
        <div className="rounded-md border border-slate-700/50 bg-slate-950/30 p-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Cost</span>
            <span className="font-mono text-slate-200">
              ${summary.cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-slate-500">Margin required</span>
            <span className="font-mono text-slate-200">
              ${summary.margin.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      )}

      {/* Error / success messages */}
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-xs text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="rounded-md border border-emerald-800/50 bg-emerald-500/10 p-3 text-xs text-emerald-400">
          {success}
        </div>
      )}

      {/* Submit */}
      <Button
        onClick={handleSubmitClick}
        disabled={!canSubmit || submitting}
        className={cn(
          "min-h-11 w-full font-semibold",
          side === "buy"
            ? "bg-emerald-600 text-white hover:bg-emerald-700"
            : "bg-red-600 text-white hover:bg-red-700",
          submitting && "opacity-70",
        )}
      >
        {submitting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ShoppingCart className="h-4 w-4" />
        )}
        {side === "buy" ? "Buy" : "Sell"} {amount || "0"} {symbol || "—"}
      </Button>

      {/* Confirmation dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="border-slate-800 bg-slate-900 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-slate-100">Confirm Order</DialogTitle>
            <DialogDescription className="text-slate-400">
              Review the order details before submitting.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 text-sm text-slate-300">
            <div className="flex justify-between">
              <span className="text-slate-500">Side</span>
              <span className={side === "buy" ? "text-emerald-400" : "text-red-400"}>
                {side === "buy" ? "BUY" : "SELL"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Symbol</span>
              <span className="font-mono">{symbol || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Type</span>
              <span>{orderType}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Amount</span>
              <span className="font-mono">{amount}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Price</span>
              <span className="font-mono">
                {isLimit ? price : "Market"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Leverage</span>
              <span className="font-mono">{leverage}x</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Reduce only</span>
              <span>{reduceOnly ? "Yes" : "No"}</span>
            </div>
            {summary && (
              <>
                <div className="flex justify-between border-t border-slate-700 pt-2">
                  <span className="text-slate-500">Est. cost</span>
                  <span className="font-mono text-slate-200">
                    ${summary.cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Margin</span>
                  <span className="font-mono text-slate-200">
                    ${summary.margin.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={submitting}
              className="min-h-11 border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800"
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmPlace}
              disabled={submitting}
              className={cn(
                "min-h-11 font-semibold",
                side === "buy"
                  ? "bg-emerald-600 text-white hover:bg-emerald-700"
                  : "bg-red-600 text-white hover:bg-red-700",
              )}
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Confirm {side === "buy" ? "Buy" : "Sell"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default OrderTicket;

/** Map HTTP error status codes to user-friendly messages. */
function mapOrderError(status: number, detail: string): string {
  switch (status) {
    case 400:
      return `Order rejected: ${detail || "Invalid parameters"}`;
    case 403:
      return "Trading is disabled on the backend";
    case 404:
      return detail || "Exchange or API keys not found. Please reconnect your account.";
    case 429:
      return "Rate limited by the exchange. Please wait a few seconds and try again.";
    case 502:
      return detail || "Exchange error. Your API key may be invalid — try reconnecting.";
    default:
      return `Order failed: ${status} ${detail || ""}`.trim();
  }
}
