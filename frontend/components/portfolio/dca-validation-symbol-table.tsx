"use client";

import { BarChart3, Clock, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DCA_VALIDATION_DISCLAIMER,
  formatDateTime,
  formatDuration,
  formatMetric,
  humanize,
  isMetricsAvailable,
  SummaryDisclaimer,
  type DcaSymbolReconstruction,
  type DcaValidationMetricsBySymbol,
} from "./dca-validation-summary";

interface DcaValidationSymbolTableProps {
  symbols: DcaSymbolReconstruction[];
  metrics?: DcaValidationMetricsBySymbol[] | null;
  onViewEvents?: (symbol: string) => void;
}

export function DcaValidationSymbolTable({ symbols, metrics = [], onViewEvents }: DcaValidationSymbolTableProps) {
  const metricRows = metrics ?? [];

  if (symbols.length === 0) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-sm text-slate-400" aria-labelledby="dca-symbols-title">
        <h2 id="dca-symbols-title" className="text-base font-semibold text-slate-100">Per-symbol validation</h2>
        <p className="mt-2">No validation symbols yet. Stored scans will appear here once validation can inspect them.</p>
        <SummaryDisclaimer />
      </section>
    );
  }

  return (
    <section aria-labelledby="dca-symbols-title" className="space-y-3">
      <div>
        <h2 id="dca-symbols-title" className="text-base font-semibold text-slate-100">Per-symbol validation</h2>
        <p className="mt-1 text-sm text-slate-400">
          Each symbol uses scan-history reconstruction and exposes scan count, date range, maximum scan gap, and metric readiness.
        </p>
      </div>
      {symbols.map((symbol) => (
        <SymbolCard key={symbol.symbol} symbol={symbol} metrics={metricRows.find((item) => item.symbol === symbol.symbol)} onViewEvents={onViewEvents} />
      ))}
    </section>
  );
}

function SymbolCard({ symbol, metrics, onViewEvents }: { symbol: DcaSymbolReconstruction; metrics?: DcaValidationMetricsBySymbol; onViewEvents?: (symbol: string) => void }) {
  const status = getSymbolStatus(symbol);

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4" aria-labelledby={`dca-symbol-${symbol.symbol}`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`dca-symbol-${symbol.symbol}`} className="font-mono text-base font-semibold text-slate-100">
              {symbol.symbol}{symbol.direction ? ` · ${symbol.direction}` : ""}
            </h3>
            <Badge variant="outline" className={status.className}>{status.label}</Badge>
            <Badge variant="outline" className="border-cyan-700 bg-cyan-500/10 text-cyan-300">Scan-to-scan</Badge>
          </div>
          <p className="mt-2 text-sm text-slate-400">{status.description}</p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-slate-700 bg-slate-950/50 text-slate-200 hover:bg-slate-800"
          onClick={() => onViewEvents?.(symbol.symbol)}
          aria-label={`View reconstructed recommendation events for ${symbol.symbol}`}
        >
          View reconstructed events
        </Button>
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetaItem label="Usable scans" value={symbol.scan_count.toLocaleString()} />
        <MetaItem label="First scan" value={formatDateTime(symbol.first_scan_at)} />
        <MetaItem label="Last scan" value={formatDateTime(symbol.last_scan_at)} />
        <MetaItem label="Max scan gap" value={formatDuration(symbol.max_scan_gap_seconds)} />
        <MetaItem label="Method" value="scan-history reconstruction" />
      </dl>

      {status.kind === "insufficient" && <InsufficientHistory symbol={symbol} />}
      {status.kind === "unavailable" && <UnavailableState symbol={symbol} />}
      {status.kind === "metrics" && <MetricsAvailable symbol={symbol} metrics={metrics} />}
    </article>
  );
}

function InsufficientHistory({ symbol }: { symbol: DcaSymbolReconstruction }) {
  const hiddenMetrics = ["Win rate", "Sharpe", "Drawdown", "Profit factor"];
  return (
    <div className="mt-4 rounded-lg border border-sky-800/60 bg-sky-500/10 p-4">
      <h4 className="font-medium text-sky-100">{symbol.symbol} needs more scan history</h4>
      <p className="mt-2 text-sm text-sky-100/80">
        We found {symbol.scan_count} usable scan(s). Metrics will appear after at least {symbol.required_minimum_scans} usable scans with price, RSI, trade plan, and position context.
      </p>
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <MetaItem label="Required minimum" value={`${symbol.required_minimum_scans} usable scans`} />
        <MetaItem label="Why metrics are hidden" value="Win rate, Sharpe, drawdown, and profit factor need at least 2 usable scans." />
      </dl>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        {hiddenMetrics.map((metric) => (
          <div key={metric} className="rounded-md border border-sky-800/50 bg-slate-950/40 p-2">
            <div className="text-xs text-sky-200/70">{metric}</div>
            <div className="mt-1 text-lg font-semibold text-slate-100">—</div>
            <div className="text-xs text-sky-100/80">Not enough usable scans.</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UnavailableState({ symbol }: { symbol: DcaSymbolReconstruction }) {
  const source = symbol.unavailable_source ?? symbol.skipped_scans[0]?.reason ?? "stored scan history";
  const reconstructing = symbol.status === "reconstructing";
  return (
    <div className="mt-4 rounded-lg border border-amber-800/60 bg-amber-500/10 p-4" aria-live={reconstructing ? "polite" : undefined}>
      <div className="flex items-center gap-2 font-medium text-amber-100">
        {reconstructing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Clock className="h-4 w-4" aria-hidden="true" />}
        {reconstructing ? `Reconstructing ${symbol.symbol}` : `${symbol.symbol} validation unavailable`}
      </div>
      <p className="mt-2 text-sm text-amber-100/80">
        {reconstructing
          ? "Validation is rebuilding recommendations from stored scan history. You can leave this page and refresh later."
          : `Validation cannot run because ${humanize(source)} is missing.`}
      </p>
      {!reconstructing && <p className="mt-1 text-sm text-amber-100/80">Run new scans or reconnect portfolio data, then retry validation.</p>}
    </div>
  );
}

function MetricsAvailable({ symbol, metrics }: { symbol: DcaSymbolReconstruction; metrics?: DcaValidationMetricsBySymbol }) {
  const performance = metrics?.metrics ?? {};
  const dcaMetrics = metrics?.dca_metrics ?? {};
  return (
    <div className="mt-4 space-y-4">
      <p className="rounded-lg border border-amber-700/50 bg-amber-500/10 p-3 text-sm text-amber-100">{DCA_VALIDATION_DISCLAIMER}</p>
      <div className="grid gap-3 lg:grid-cols-4">
        <MetricGroup title="Performance" metrics={[
          ["Win rate", formatMetric(performance.win_rate, "%")],
          ["Total return", formatMetric(performance.total_return, "%")],
          ["Gross profit", formatMetric(performance.gross_profit)],
          ["Gross loss", formatMetric(performance.gross_loss)],
          ["Profit factor", formatMetric(performance.profit_factor)],
        ]} />
        <MetricGroup title="Risk" metrics={[
          ["Max drawdown", formatMetric(performance.max_drawdown_absolute)],
          ["Max drawdown %", formatMetric(performance.max_drawdown_percent, "%")],
          ["Sharpe", formatMetric(performance.sharpe)],
          ["Sortino", formatMetric(performance.sortino)],
        ]} />
        <MetricGroup title="Behavior" metrics={[
          ["Average hold time", formatMetric(performance.average_hold_time_hours, "h")],
          ["Exposure", formatMetric(performance.exposure_percentage, "%")],
          ["Reconstructed trades", formatMetric(performance.reconstructed_trade_count)],
        ]} />
        <MetricGroup title="DCA-specific" metrics={[
          ["Entry completion", formatMetric(dcaMetrics.entry_level_completion_rate, "%")],
          ["ADD follow-through", formatMetric(dcaMetrics.add_follow_through_rate, "%")],
          ["DCA SAFE accuracy", formatMetric(dcaMetrics.dca_safe_flag_accuracy, "%")],
          ["3-entry completion", formatMetric(dcaMetrics.three_entry_completion_rate, "%")],
        ]} />
      </div>

      {metrics?.walk_forward && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <h4 className="flex items-center gap-2 text-sm font-medium text-slate-100"><BarChart3 className="h-4 w-4" aria-hidden="true" /> Walk-forward split</h4>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <MetaItem label="In-sample range" value={`${formatDateTime(metrics.walk_forward.in_sample.date_range.start)} – ${formatDateTime(metrics.walk_forward.in_sample.date_range.end)}`} />
            <MetaItem label="Out-of-sample range" value={`${formatDateTime(metrics.walk_forward.out_of_sample.date_range.start)} – ${formatDateTime(metrics.walk_forward.out_of_sample.date_range.end)}`} />
          </div>
        </div>
      )}

      <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">
        <span className="font-medium text-slate-100">Benchmark: </span>
        {metrics?.buy_and_hold_benchmark?.value == null
          ? `Benchmark unavailable — ${metrics?.buy_and_hold_benchmark?.reason ?? "missing first or last usable mark price."}`
          : `Buy-and-hold ${metrics.buy_and_hold_benchmark.value}% over the same scan window.`}
      </div>
    </div>
  );
}

function MetricGroup({ title, metrics }: { title: string; metrics: [string, { value: string; reason: string | null }][] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <h4 className="text-sm font-medium text-slate-100">{title}</h4>
      <dl className="mt-2 space-y-2">
        {metrics.map(([label, metric]) => (
          <div key={label} className="flex items-start justify-between gap-3 text-sm">
            <dt className="text-slate-400">{label}</dt>
            <dd className="text-right text-slate-100 tabular-nums">
              <div>{metric.value}</div>
              {metric.reason && <div className="max-w-44 text-xs text-slate-500">{humanize(metric.reason)}</div>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-2">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-200">{value}</dd>
    </div>
  );
}

function getSymbolStatus(symbol: DcaSymbolReconstruction) {
  if (symbol.status === "insufficient_history" || symbol.scan_count < symbol.required_minimum_scans) {
    return {
      kind: "insufficient" as const,
      label: "Insufficient history",
      className: "border-sky-700 bg-sky-500/10 text-sky-300",
      description: "Metrics are hidden until at least 2 usable scans are available.",
    };
  }
  if (symbol.status === "reconstructing") {
    return {
      kind: "unavailable" as const,
      label: "Reconstructing",
      className: "border-amber-700 bg-amber-500/10 text-amber-300",
      description: "Validation is rebuilding recommendations from stored scan history.",
    };
  }
  if (symbol.status === "validation_error" || !isMetricsAvailable(symbol)) {
    return {
      kind: "unavailable" as const,
      label: "Unavailable",
      className: "border-amber-700 bg-amber-500/10 text-amber-300",
      description: "Validation cannot run until the missing source data is available.",
    };
  }
  return {
    kind: "metrics" as const,
    label: "Metrics available",
    className: "border-emerald-700 bg-emerald-500/10 text-emerald-300",
    description: "Scan-history reconstruction has enough usable inputs to display simulated metrics.",
  };
}

export default DcaValidationSymbolTable;
