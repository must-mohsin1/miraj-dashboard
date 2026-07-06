"use client";

import type { BMSB } from "@/lib/types";

interface BmsbStatusProps {
  bmsb: BMSB | null | undefined;
}

export function BmsbStatus({ bmsb }: BmsbStatusProps) {
  if (!bmsb) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-300">Bull Market Support Band</h3>
        <p className="text-xs text-slate-500">No BMSB data</p>
      </div>
    );
  }

  const isAbove = bmsb.status === "above";
  const isBull = bmsb.regime === "bull";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">Bull Market Support Band</h3>
      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-500">20-Week SMA</p>
          <p className="font-bold tabular-nums text-slate-100">${bmsb.sma_20w?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-500">21-Week EMA</p>
          <p className="font-bold tabular-nums text-slate-100">${bmsb.ema_21w?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-slate-500">Current Price</p>
          <p className="font-bold tabular-nums text-slate-100">${bmsb.current_price?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
        </div>
      </div>
      <div className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 ${
        isAbove
          ? "border-emerald-700/50 bg-emerald-500/10"
          : "border-red-700/50 bg-red-500/10"
      }`}>
        <span className={`text-sm font-bold ${isAbove ? "text-emerald-400" : "text-red-400"}`}>
          {isAbove ? "✅ ABOVE BAND" : "❌ BELOW BAND"}
        </span>
        <span className="text-xs text-slate-400">
          ({isBull ? "Bull Market regime" : "Bear Market regime"})
        </span>
      </div>
      <p className="mt-2 text-[10px] text-slate-600">
        If BTC is below this band, avoid longs. This is Miraj's legendary regime indicator.
      </p>
    </div>
  );
}

export default BmsbStatus;
