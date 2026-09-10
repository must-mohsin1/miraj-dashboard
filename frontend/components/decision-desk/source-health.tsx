import type { CollectorReport } from "@/lib/collector-report-types";

const healthClass = { ok: "text-emerald-400", degraded: "text-amber-400", failed: "text-red-400", unavailable: "text-ash-400" };

export function SourceHealth({ sources }: { sources: CollectorReport["source_health"] }) {
  return <section aria-labelledby="source-health-title" className="border-t border-slate-800 pt-4"><h2 id="source-health-title" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Source health</h2><ul className="mt-3 divide-y divide-slate-800">{sources.length === 0 ? <li className="py-3 text-sm text-slate-500">No source-health evidence was supplied.</li> : sources.map((source) => <li key={source.source} className="grid gap-1 py-3 text-sm sm:grid-cols-[1fr_auto_1fr]"><span className="font-mono text-slate-200">{source.source}</span><span className={`font-mono uppercase ${healthClass[source.status]}`}>{source.status}</span><span className="text-slate-500 sm:text-right">{source.checked_at ?? "No timestamp"}{source.fallback ? " · fallback" : ""}{source.detail ? ` · ${source.detail}` : ""}</span></li>)}</ul></section>;
}
