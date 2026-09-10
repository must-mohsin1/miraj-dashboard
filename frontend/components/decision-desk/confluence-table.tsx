import type { CollectorReport } from "@/lib/collector-report-types";

function displayNumber(value: number | null) {
  return value === null ? "—" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function ConfluenceTable({ scores }: { scores: CollectorReport["scores"] }) {
  return (
    <section aria-labelledby="confluence-title" className="border-t border-slate-800 pt-4">
      <h2 id="confluence-title" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Confluence</h2>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[26rem] border-collapse text-sm">
          <thead className="border-y border-slate-800 text-left text-[11px] uppercase tracking-[0.12em] text-slate-500">
            <tr><th className="py-2 font-medium">Evidence</th><th className="py-2 text-right font-medium">Score</th><th className="py-2 text-right font-medium">Maximum</th><th className="py-2 pl-5 font-medium">Note</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {scores.length === 0 ? <tr><td colSpan={4} className="py-3 text-slate-500">No confluence scores were supplied.</td></tr> : scores.map((score) => (
              <tr key={score.label}><th scope="row" className="py-3 text-left font-medium text-slate-200">{score.label}</th><td className="py-3 text-right font-mono text-slate-100">{displayNumber(score.value)}</td><td className="py-3 text-right font-mono text-slate-500">{displayNumber(score.maximum)}</td><td className="py-3 pl-5 text-slate-500">{score.detail ?? "—"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
