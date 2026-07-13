import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  formatDateTime,
  humanize,
  type DcaReconstructionEvent,
  type DcaSkippedScan,
} from "./dca-validation-summary";

interface DcaValidationEventsProps {
  symbol: string;
  events: DcaReconstructionEvent[];
  skippedScans?: DcaSkippedScan[];
  errorSource?: string | null;
}

export function DcaValidationEvents({ symbol, events, skippedScans = [], errorSource }: DcaValidationEventsProps) {
  if (errorSource) {
    return (
      <section className="rounded-xl border border-red-800/60 bg-red-500/10 p-5" aria-labelledby="dca-events-title">
        <h2 id="dca-events-title" className="text-base font-semibold text-red-100">Events could not load</h2>
        <p className="mt-2 text-sm text-red-100/80">Reconstructed events could not load because {humanize(errorSource)} is missing.</p>
      </section>
    );
  }

  const rows = latestEvents(events, skippedScans, symbol);

  if (rows.length === 0) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5" aria-labelledby="dca-events-title">
        <h2 id="dca-events-title" className="text-base font-semibold text-slate-100">No reconstructed events for {symbol}</h2>
        <p className="mt-2 text-sm text-slate-400">Stored scans were found, but none had enough usable DCA inputs to reconstruct a recommendation.</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4" aria-labelledby="dca-events-title">
      <div className="mb-3">
        <h2 id="dca-events-title" className="text-base font-semibold text-slate-100">Latest reconstructed recommendation events</h2>
        <p className="mt-1 text-sm text-slate-400">Showing the latest {rows.length} scan-history reconstruction event(s) for {symbol}, capped at 50.</p>
      </div>
      <Table aria-label={`Reconstructed events for ${symbol}`}>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Time</TableHead>
            <TableHead className="text-slate-500">Recommendation</TableHead>
            <TableHead className="text-slate-500">Confidence</TableHead>
            <TableHead className="text-slate-500">Reason</TableHead>
            <TableHead className="text-slate-500">Metric eligible</TableHead>
            <TableHead className="text-slate-500">Skipped reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((event, index) => (
            <TableRow key={`${event.timestamp ?? "no-time"}-${event.recommendation}-${index}`} className="border-slate-800/60 hover:bg-slate-800/30">
              <TableCell className="whitespace-nowrap text-slate-400 tabular-nums">{formatDateTime(event.timestamp)}</TableCell>
              <TableCell className="font-medium text-slate-100">{event.recommendation}</TableCell>
              <TableCell className="text-slate-300 tabular-nums">{event.confidence ?? "—"}</TableCell>
              <TableCell className="max-w-md text-slate-300">{event.reason ?? "—"}</TableCell>
              <TableCell className={event.participates_in_metrics ? "text-emerald-300" : "text-amber-300"}>
                {event.participates_in_metrics ? "Yes" : "No"}
              </TableCell>
              <TableCell className="text-slate-400">{event.skipped_reason ? humanize(event.skipped_reason) : "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

function latestEvents(events: DcaReconstructionEvent[], skippedScans: DcaSkippedScan[], symbol: string) {
  const skippedRows: DcaReconstructionEvent[] = skippedScans
    .filter((scan) => !scan.symbol || scan.symbol === symbol)
    .map((scan) => ({
      timestamp: scan.timestamp,
      symbol: scan.symbol ?? symbol,
      recommendation: "—",
      confidence: null,
      reason: "Skipped scan during reconstruction.",
      participates_in_metrics: false,
      skipped_reason: scan.reason,
    }));

  return [...events, ...skippedRows]
    .filter((event) => event.symbol === symbol)
    .sort((a, b) => timestampValue(b.timestamp) - timestampValue(a.timestamp))
    .slice(0, 50);
}

function timestampValue(timestamp: string | null) {
  if (!timestamp) return 0;
  const value = new Date(timestamp).getTime();
  return Number.isNaN(value) ? 0 : value;
}

export default DcaValidationEvents;
