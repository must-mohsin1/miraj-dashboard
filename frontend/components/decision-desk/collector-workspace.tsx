import { AuditDrawer } from "@/components/decision-desk/audit-drawer";
import { ConfluenceTable } from "@/components/decision-desk/confluence-table";
import { DeskAutoRefresh } from "@/components/decision-desk/desk-auto-refresh";
import { SetupStateRail } from "@/components/decision-desk/setup-state-rail";
import { SourceHealth } from "@/components/decision-desk/source-health";
import { TimeframeEvidence } from "@/components/decision-desk/timeframe-evidence";
import type { LatestCollectorReportResponse } from "@/lib/collector-report-types";

const verdictClass = {
  NO_TRADE: "text-slate-200",
  WATCH: "text-amber-400",
  READY_LONG: "text-emerald-400",
  READY_SHORT: "text-red-400",
  INVALIDATED: "text-ash-400",
  STALE: "text-ash-400",
};

function quote(value: number | null) {
  return value === null ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function CollectorWorkspace({ response }: { response: LatestCollectorReportResponse | null }) {
  const report = response?.report ?? null;
  const unavailable = !report;
  const stale = Boolean(response?.stale || response?.status === "stale");
  const verdict = unavailable ? "Desk unavailable." : report.verdict.summary.endsWith(".") ? report.verdict.summary : `${report.verdict.summary}.`;

  return (
    <section aria-label="Collector Decision Desk" className="mx-auto w-full max-w-[1080px]">
      <header className="border-t border-brass-400 pt-3">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] uppercase tracking-[0.12em] text-slate-500">
          <span className="font-mono">{report?.symbol ?? "SOLUSDT"}</span>
          <span aria-hidden>·</span>
          <span>{stale ? "Stale report" : report ? response?.status : "Unavailable"}</span>
          {report?.generated_at ? <><span aria-hidden>·</span><span className="font-mono">as of {report.generated_at}</span></> : null}
        </div>
        <h1 className={`font-verdict mt-8 text-5xl sm:text-7xl lg:text-8xl ${report ? verdictClass[report.verdict.state] : "text-ash-400"}`}>{verdict}</h1>
        <p className="mt-4 max-w-[64ch] text-sm leading-6 text-slate-500">{unavailable ? "No validated collector report is available. The desk makes no market inference while the evidence boundary is unavailable." : stale ? "Evidence is retained for review, not confirmation. A stale report cannot clear a setup gate." : "Validated public-data evidence for manual review. This desk never submits orders or changes collector state."}</p>
        <DeskAutoRefresh lastRefreshedAt={response?.received_at ?? report?.generated_at ?? null} />
      </header>

      {report ? <>
        <div className="mt-10 grid gap-x-10 gap-y-8 lg:grid-cols-12">
          <div className="lg:col-span-8">
            <SetupStateRail states={report.setup_states} />
            <div className="mt-8"><ConfluenceTable scores={report.scores} /></div>
            <div className="mt-8"><TimeframeEvidence timeframes={report.timeframes} /></div>
          </div>
          <aside className="lg:col-span-4 lg:border-l lg:border-slate-800 lg:pl-6">
            <section aria-labelledby="quote-title"><h2 id="quote-title" className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Quote context</h2><p className="mt-3 font-mono text-2xl tabular-nums text-slate-100">{quote(report.quote.price)}</p><p className="mt-2 text-xs text-slate-500">{report.quote.context_only ? "Context only — excluded from gate confirmation." : "Quote classification was supplied by the collector."}</p><p className="mt-1 font-mono text-xs text-slate-500">{report.quote.as_of ?? "No quote timestamp"}</p></section>
            <div className="mt-8"><SourceHealth sources={report.source_health} /></div>
            <div className="mt-8"><AuditDrawer response={response!} report={report} /></div>
          </aside>
        </div>
        {report.limitations.length > 0 ? <footer className="mt-10 border-t border-slate-800 pt-4"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Limitations</h2><ul className="mt-2 space-y-1 text-sm text-slate-500">{report.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></footer> : null}
      </> : null}
    </section>
  );
}
