"use client";

import { useState } from "react";
import { TimeframeCandleChart } from "@/components/decision-desk/timeframe-candle-chart";
import type { CollectorTimeframeEvidence } from "@/lib/collector-report-types";

function price(value: number | null) { return value === null ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function range(label: string, value?: { low: number; high: number } | null) { return value ? `${label} ${price(value.low)}–${price(value.high)}` : `${label} unavailable`; }

export function TimeframeEvidence({ timeframes }: { timeframes: CollectorTimeframeEvidence[] }) {
  const [selected, setSelected] = useState(0);
  const evidence = timeframes[selected] ?? null;
  return (
    <section aria-labelledby="timeframe-title" className="border-t border-slate-800 pt-4">
      <h2 id="timeframe-title" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Timeframe evidence</h2>
      {timeframes.length === 0 || !evidence ? <p className="mt-3 text-sm text-slate-500">No completed candle evidence was supplied.</p> : <>
        <div className="mt-3 flex flex-wrap gap-2" role="tablist" aria-label="Report timeframes">
          {timeframes.map((frame, index) => <button type="button" key={frame.timeframe} role="tab" aria-selected={selected === index} onClick={() => setSelected(index)} className={`border px-2 py-1 font-mono text-xs ${selected === index ? "border-brass-400 text-brass-300" : "border-slate-800 text-slate-500 hover:text-slate-200"}`}>{frame.timeframe}</button>)}
        </div>
        <div className="mt-4 grid gap-3 border-y border-slate-800 py-3 text-sm sm:grid-cols-3">
          <p><span className="block text-[11px] uppercase tracking-[0.12em] text-slate-500">State</span><span className="font-mono text-slate-200">{evidence.state}</span></p>
          <p><span className="block text-[11px] uppercase tracking-[0.12em] text-slate-500">Completed close</span><span className="font-mono text-slate-200">{price(evidence.close)}</span></p>
          <p><span className="block text-[11px] uppercase tracking-[0.12em] text-slate-500">As of</span><span className="font-mono text-slate-200">{evidence.as_of ?? "—"}</span></p>
        </div>
        <TimeframeCandleChart timeframe={evidence.timeframe} candles={evidence.candles} fvg={evidence.fvg} ote={evidence.ote} />
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500"><span>{evidence.candles.length} completed candle{evidence.candles.length === 1 ? "" : "s"} supplied.</span><span>{range("FVG", evidence.fvg)}</span><span>{range("OTE", evidence.ote)}</span></div>
      </>}
    </section>
  );
}
