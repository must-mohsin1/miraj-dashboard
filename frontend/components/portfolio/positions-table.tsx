"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PositionItem } from "@/lib/types";
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

export function PositionsTable({ positions, livePrices = null }: PositionsTableProps) {
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
            // Calculate real-time PnL using contract_size multiplier
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
}: PositionRowProps) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prevMarkRef = useRef<number | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (liveMark == null) return;
    const prev = prevMarkRef.current;
    if (prev != null && liveMark > prev) {
      setFlash("up");
    } else if (prev != null && liveMark < prev) {
      setFlash("down");
    }
    prevMarkRef.current = liveMark;

    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlash(null), 600);

    return () => {
      if (flashTimerRef.current) {
        clearTimeout(flashTimerRef.current);
        flashTimerRef.current = null;
      }
    };
  }, [liveMark]);

  const markColor =
    flash === "up"
      ? "text-emerald-400"
      : flash === "down"
        ? "text-red-400"
        : "text-slate-300";

  return (
    <TableRow
      className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
    >
      <TableCell className="font-medium text-slate-100">
        <span className="inline-flex items-center gap-2">
          {position.symbol}
          {liveMark != null && (
            <span className="relative flex h-1.5 w-1.5" aria-hidden title="Live price">
              <span
                className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
                style={{ animationDuration: "1.5s" }}
              />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
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
