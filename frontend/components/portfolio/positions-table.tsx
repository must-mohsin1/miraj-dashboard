"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AlertTriangle, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PositionItem, PositionAlertItem } from "@/lib/types";
import type { PriceMap } from "@/hooks/use-price-stream";

/**
 * PositionsTable — Client Component.
 *
 * Renders the user's open futures positions. The Side column shows a coloured
 * badge (green for long, red for short). PnL and PnL% are coloured green for
 * profit, red for loss.
 *
 * When a `livePrices` map is supplied (keyed in SSE format, e.g. "BTC-USDT"),
 * the Mark Price and PnL are recalculated on every tick:
 *
 *   liveMark   = livePrices[positionSymbolToPriceKey(symbol)].price
 *   pnl        = (liveMark - entry_price) * size * (LONG ? 1 : -1)
 *   pnl_pct    = (pnl / (entry_price * |size|)) * 100
 *
 * A live mark price cell flashes green/red with each price update, and the
 * PnL cell is colored by the sign of the (live-or-static) PnL.
 */

/**
 * Convert a position symbol (e.g. "BTC/USDT:USDT" or "BTC-USDT") to the SSE
 * price map key used for live lookups ("BTC-USDT").
 */
function positionSymbolToPriceKey(symbol: string): string {
  const s = symbol.toUpperCase();
  // ccxt futures style "BTC/USDT:USDT" → base "BTC", quote "USDT"
  let base = s.split(":")[0].replace("/", "-");
  // "BTC-USDT" → convert to "BTC-USD" for SSE key matching
  if (base.endsWith("-USDT")) {
    return base.slice(0, -5) + "-USD";
  }
  // "SOLUSDT" (no separator) → "SOL-USD"
  if (base.endsWith("USDT") && base.length > 4) {
    return base.slice(0, -4) + "-USD";
  }
  return base;
}

interface PositionsTableProps {
  positions: PositionItem[];
  /** Live prices keyed in SSE format (e.g. "BTC-USDT"). null when not streaming. */
  livePrices?: PriceMap | null;
  /** Optional position alerts keyed by symbol (from /position-alerts endpoint). */
  alertsMap?: Record<string, PositionAlertItem> | null;
}

function sideMeta(side: string) {
  const s = (side ?? "").toUpperCase();
  if (s === "LONG" || s === "BUY") {
    return {
      label: "LONG",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
      arrow: "▲" as const,
    };
  }
  if (s === "SHORT" || s === "SELL") {
    return {
      label: "SHORT",
      className: "bg-red-500/10 text-red-400 border-red-700/50",
      arrow: "▼" as const,
    };
  }
  return {
    label: side || "—",
    className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
    arrow: "■" as const,
  };
}

export function PositionsTable({
  positions,
  livePrices = null,
  alertsMap = null,
}: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No open positions.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Symbol</TableHead>
            <TableHead className="text-slate-500">Side</TableHead>
            <TableHead className="text-right text-slate-500">Size</TableHead>
            <TableHead className="text-right text-slate-500">Entry Price</TableHead>
            <TableHead className="text-right text-slate-500">Mark Price</TableHead>
            <TableHead className="text-right text-slate-500">PnL (USD)</TableHead>
            <TableHead className="text-right text-slate-500">PnL %</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Leverage</TableHead>
            <TableHead className="hidden text-right text-slate-500 md:table-cell">Liq Price</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p, i) => {
            const meta = sideMeta(p.side);
            const dir = meta.label === "LONG" ? 1 : meta.label === "SHORT" ? -1 : 0;
            const priceKey = positionSymbolToPriceKey(p.symbol);
            const liveTick = livePrices?.[priceKey];
            const liveMark = liveTick?.price ?? null;

            // Use live mark price for display + flash
            const markPrice = liveMark ?? p.mark_price;
            // Calculate real-time PnL using contract size multiplier
            // Formula: (liveMark - entry) * contracts * contractSize * dir
            const contractSize = p.contract_size ?? 1;
            const pnl =
              liveMark != null && dir !== 0
                ? (liveMark - p.entry_price) * p.size * contractSize * dir
                : p.pnl;
            // PnL% = ROI on margin (matches MEXC's display)
            const pnlPercent =
              liveMark != null && dir !== 0
                ? p.margin > 0
                  ? (pnl / p.margin) * 100
                  : 0
                : p.pnl_percent;
            const pnlPositive = pnl >= 0;

            // Look up alerts for this symbol (keyed by exact position symbol).
            // Fallback to a normalized lookup (strip quote/settlement suffixes).
            const symbolAlert =
              alertsMap?.[p.symbol] ??
              alertsMap?.[p.symbol.split(":")[0]] ??
              null;

            return (
              <PositionRow
                key={`${p.symbol}-${i}`}
                position={p}
                dir={dir}
                meta={meta}
                markPrice={markPrice}
                liveMark={liveMark}
                pnl={pnl}
                pnlPercent={pnlPercent}
                pnlPositive={pnlPositive}
                alert={symbolAlert}
              />
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Single position row. Isolated per row so the mark-price flash animation
 * (green/red) only fires for the symbol whose price just ticked.
 */
interface PositionRowProps {
  position: PositionItem;
  dir: number;
  meta: ReturnType<typeof sideMeta>;
  markPrice: number | null;
  liveMark: number | null;
  pnl: number;
  pnlPercent: number;
  pnlPositive: boolean;
  alert?: PositionAlertItem | null;
}

function PositionRow({
  position,
  dir: _dir,
  meta,
  markPrice,
  liveMark,
  pnl,
  pnlPercent,
  pnlPositive,
  alert = null,
}: PositionRowProps) {
  const [showAlertTooltip, setShowAlertTooltip] = useState(false);

  // Kill tick urgency (DESIGN.md): live numbers update silently. Direction
  // color belongs to verdicts and P&L, never to per-tick price movement.
  const markColor = "text-slate-300";

  const hasAlert = alert && alert.alerts && alert.alerts.length > 0;
  const isDanger = alert?.max_severity === "DANGER";
  const alertTooltip = hasAlert
    ? alert!.alerts
        .map(
          (a) =>
            `[${a.severity}] ${a.type.replace("_", " ")}: ${a.message}${a.action ? ` → ${a.action}` : ""}`,
        )
        .join("\n")
    : "";

  return (
    <TableRow
      className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
    >
      <TableCell className="font-medium text-slate-100">
        <span className="inline-flex items-center gap-2">
          {position.symbol}
          {liveMark != null && (
            <span className="relative flex h-1.5 w-1.5" aria-hidden title="Live price">
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
          )}
          {hasAlert && (
            <span
              className="relative inline-flex cursor-help"
              onMouseEnter={() => setShowAlertTooltip(true)}
              onMouseLeave={() => setShowAlertTooltip(false)}
              onFocus={() => setShowAlertTooltip(true)}
              onBlur={() => setShowAlertTooltip(false)}
              tabIndex={0}
              role="button"
              aria-label={`${alert!.alerts.length} position alert${alert!.alerts.length > 1 ? "s" : ""}`}
            >
              {isDanger ? (
                <ShieldAlert className="h-4 w-4 text-red-400" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-amber-400" />
              )}
              <span
                className={`absolute -right-1 -top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full px-0.5 text-[9px] font-bold ${
                  isDanger
                    ? "bg-red-500 text-white"
                    : "bg-amber-500 text-black"
                }`}
              >
                {alert!.alerts.length}
              </span>
              {showAlertTooltip && (
                <span
                  className="absolute left-full top-0 z-50 ml-2 w-64 whitespace-pre-line rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300 shadow-xl"
                  role="tooltip"
                >
                  {alertTooltip}
                </span>
              )}
            </span>
          )}
        </span>
      </TableCell>
      <TableCell>
        <Badge variant="outline" className={meta.className}>
          {meta.arrow} {meta.label}
        </Badge>
      </TableCell>
      <TableCell className="text-right text-slate-300 tabular-nums">
        {fmt(position.size)}
      </TableCell>
      <TableCell className="text-right text-slate-300 tabular-nums">
        {fmt(position.entry_price)}
      </TableCell>
      <TableCell
        className={`text-right tabular-nums transition-colors duration-300 ${markColor}`}
      >
        {markPrice != null ? fmt(markPrice) : "—"}
      </TableCell>
      <TableCell
        className={`text-right font-semibold tabular-nums ${
          pnlPositive ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {pnlPositive ? "+" : ""}
        {fmt(pnl)}
      </TableCell>
      <TableCell
        className={`text-right font-semibold tabular-nums ${
          pnlPositive ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {pnlPositive ? "+" : ""}
        {pnlPercent.toFixed(2)}%
      </TableCell>
      <TableCell className="hidden text-right text-slate-300 tabular-nums md:table-cell">
        {position.leverage}x
      </TableCell>
      <TableCell className="hidden text-right text-slate-400 tabular-nums md:table-cell">
        {position.liquidation_price != null
          ? fmt(position.liquidation_price)
          : "—"}
      </TableCell>
    </TableRow>
  );
}

/** Format a number with up to 8 decimal places, trimming trailing zeros. */
function fmt(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  return parseFloat(n.toFixed(8)).toString();
}

export default PositionsTable;
