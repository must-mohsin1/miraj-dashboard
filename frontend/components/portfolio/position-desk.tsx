"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import type { PositionDeskResponse, PositionDeskRow } from "@/lib/types";

/**
 * PositionDesk — Client Component.
 *
 * The portfolio page's decision layer: one ruling per open position, joined
 * from the typed scan verdict and the DCA engine by
 * `GET /api/v1/portfolio/{exchange}/position-desk`. The ruling renders in
 * the verdict voice (serif, full stop); position facts and key levels render
 * in tabular numerals. Auto-refreshes every 5 minutes alongside the
 * dashboard — silently, per the no-tick-urgency rule.
 */

interface PositionDeskProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

const REC_CHIP: Record<string, string> = {
  ADD: "border-emerald-700/50 bg-emerald-500/10 text-emerald-400",
  HOLD: "border-slate-600/60 bg-slate-500/10 text-slate-300",
  REDUCE: "border-amber-700/50 bg-amber-500/10 text-amber-400",
  CLOSE: "border-red-700/50 bg-red-500/10 text-red-400",
};

const SIDE_CHIP: Record<string, string> = {
  long: "border-emerald-700/50 bg-emerald-500/10 text-emerald-400",
  short: "border-red-700/50 bg-red-500/10 text-red-400",
};

function fmtPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1000)
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (value >= 1)
    return value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  return value.toFixed(4);
}

export function PositionDesk({ token, exchange }: PositionDeskProps) {
  const [data, setData] = useState<PositionDeskResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchDesk() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/portfolio/${exchange}/position-desk`, {
        headers,
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: PositionDeskResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    async function load() {
      if (cancelled) return;
      await fetchDesk();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchDesk();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Ruling on open positions…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="border border-red-800/50 bg-red-500/10 p-4 text-sm text-red-400">
        Position desk unavailable: {error}
      </div>
    );
  }

  const rows = data?.positions ?? [];

  return (
    <section className="border border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
          Position Desk
        </h2>
        <button
          type="button"
          onClick={() => fetchDesk()}
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300"
          aria-label="Refresh position desk"
        >
          {refreshing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-500">No open positions.</p>
      ) : (
        <div className="divide-y divide-slate-800">
          {rows.map((row) => (
            <DeskRow key={`${row.symbol}-${row.side}`} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

// ── Single desk row ────────────────────────────────────────────────────────

function DeskRow({ row }: { row: PositionDeskRow }) {
  const recChip = REC_CHIP[row.recommendation] ?? REC_CHIP.HOLD;
  const sideChip = SIDE_CHIP[row.side] ?? REC_CHIP.HOLD;

  const levels: Array<[string, string]> = [
    ["Entry", fmtPrice(row.entry_price)],
    ["Mark", fmtPrice(row.mark_price)],
  ];
  if (row.add_zone && row.add_zone.low != null && row.add_zone.high != null) {
    levels.push([
      "Add zone",
      `${fmtPrice(row.add_zone.low)}–${fmtPrice(row.add_zone.high)}`,
    ]);
  }
  if (row.tp_levels && row.tp_levels.length > 0) {
    levels.push(["TP1", fmtPrice(row.tp_levels[0])]);
  }
  if (row.regime_band_low != null && row.regime_band_high != null) {
    levels.push([
      "Weekly band",
      `${fmtPrice(row.regime_band_low)}–${fmtPrice(row.regime_band_high)}`,
    ]);
  }
  if (row.liq_distance_pct != null) {
    levels.push(["Liq dist", `${row.liq_distance_pct.toFixed(1)}%`]);
  }

  return (
    <article className="px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-bold text-slate-100">
            {row.symbol}
          </span>
          <span
            className={`inline-flex items-center border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${sideChip}`}
          >
            {row.side}
          </span>
          <span
            className={`inline-flex items-center border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${recChip}`}
          >
            {row.recommendation}
          </span>
          {row.alignment === "COUNTER_REGIME" && (
            <span className="inline-flex items-center border border-amber-700/50 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-400">
              Counter-regime
            </span>
          )}
          {row.alignment === "NO_DATA" && (
            <span className="inline-flex items-center border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-400">
              No data
            </span>
          )}
        </div>
        {typeof row.pnl_percent === "number" && (
          <span
            className={`font-mono text-sm tabular-nums ${
              row.pnl_percent >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {row.pnl_percent >= 0 ? "+" : ""}
            {row.pnl_percent.toFixed(2)}%
          </span>
        )}
      </div>

      {/* The ruling — verdict voice */}
      <p className="font-verdict pt-3 text-2xl text-slate-100 sm:text-3xl">
        {row.ruling}
      </p>
      {row.detail && (
        <p className="pt-1 text-sm leading-relaxed text-slate-400">
          {row.detail}
        </p>
      )}

      {/* Key levels */}
      <p className="flex flex-wrap gap-x-5 gap-y-1 pt-3 font-mono text-xs tabular-nums text-slate-500">
        {levels.map(([label, value]) => (
          <span key={label}>
            {label}{" "}
            <span className="text-slate-300">{value}</span>
          </span>
        ))}
      </p>
    </article>
  );
}

export default PositionDesk;
