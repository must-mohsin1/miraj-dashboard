import type { CollectorReport } from "@/lib/collector-report-types";

const stateClass = {
  passed: "border-emerald-500/50 text-emerald-400",
  blocked: "border-amber-500/50 text-amber-400",
  pending: "border-slate-600 text-slate-300",
  unavailable: "border-ash-500 text-ash-400",
};

export function SetupStateRail({ states }: { states: CollectorReport["setup_states"] }) {
  return (
    <section aria-labelledby="setup-state-title" className="border-y border-slate-800 py-4">
      <h2 id="setup-state-title" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Setup state</h2>
      <ol className="mt-3 divide-y divide-slate-800">
        {states.map((entry) => (
          <li key={entry.state} className="grid gap-1 py-3 sm:grid-cols-[4rem_7rem_1fr] sm:items-baseline sm:gap-3">
            <span className="font-mono text-sm text-slate-200">{entry.state}</span>
            <span className={`w-fit border px-1.5 py-0.5 font-mono text-[11px] uppercase ${stateClass[entry.status]}`}>{entry.status}</span>
            <span className="text-sm text-slate-500">{entry.reason ?? "No reason supplied."}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
