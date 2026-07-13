import { Activity, AlertTriangle, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";

export const DCA_VALIDATION_DISCLAIMER =
  "These are reconstructed and shadow-mode results, not realized trading performance or financial advice.";

export type DcaValidationState =
  | "metrics_available"
  | "insufficient_history"
  | "reconstructing"
  | "validation_error";

export type DcaRecommendationCategory = "ADD" | "HOLD" | "REDUCE" | "CLOSE" | string;
export type DcaShadowOutcome = "would_allow" | "would_block" | "would_reduce" | "would_close" | "no_action";

export interface DcaMetricValue<T = number> {
  value: T | null;
  reason?: string | null;
}

export interface DcaValidationMetricSet {
  win_rate?: DcaMetricValue;
  total_return?: DcaMetricValue;
  gross_profit?: DcaMetricValue;
  gross_loss?: DcaMetricValue;
  profit_factor?: DcaMetricValue;
  max_drawdown_absolute?: DcaMetricValue;
  max_drawdown_percent?: DcaMetricValue;
  sharpe?: DcaMetricValue;
  sortino?: DcaMetricValue;
  average_hold_time_hours?: DcaMetricValue;
  exposure_percentage?: DcaMetricValue;
  reconstructed_trade_count?: DcaMetricValue;
  [metric: string]: DcaMetricValue<unknown> | undefined;
}

export interface DcaValidationDcaMetricSet {
  entry_level_completion_rate?: DcaMetricValue;
  average_entry_price_vs_planned_zone?: DcaMetricValue<Record<string, number | null>>;
  add_follow_through_rate?: DcaMetricValue;
  dca_safe_flag_accuracy?: DcaMetricValue;
  three_entry_completion_rate?: DcaMetricValue;
  [metric: string]: DcaMetricValue<unknown> | undefined;
}

export interface DcaDateRange {
  start: string | null;
  end: string | null;
}

export interface DcaWalkForwardPeriod {
  date_range: DcaDateRange;
  metrics?: DcaValidationMetricSet;
}

export interface DcaWalkForwardMetrics {
  split_ratio: number;
  in_sample: DcaWalkForwardPeriod;
  out_of_sample: DcaWalkForwardPeriod;
}

export interface DcaBuyAndHoldBenchmark {
  value: number | null;
  reason?: string | null;
}

export interface DcaValidationMetricsBySymbol {
  symbol: string;
  status: "metrics_available" | "insufficient_history" | string;
  scan_count?: number;
  first_scan_at?: string | null;
  last_scan_at?: string | null;
  insufficient_reasons?: string[];
  metrics?: DcaValidationMetricSet;
  dca_metrics?: DcaValidationDcaMetricSet;
  walk_forward?: DcaWalkForwardMetrics;
  buy_and_hold_benchmark?: DcaBuyAndHoldBenchmark;
  warnings?: string[];
}

export interface DcaFillAssumptions {
  long_thresholds?: number[];
  short_thresholds?: number[];
  long_rsi_entries?: number[];
  short_rsi_entries?: number[];
  allocations?: number[];
  allocation_percentages?: number[];
  slippage_percent?: number;
  fee_percent?: number;
  [assumption: string]: string | number | boolean | number[] | null | undefined;
}

export interface DcaReconstructionEvent {
  timestamp: string | null;
  symbol: string;
  recommendation: DcaRecommendationCategory;
  confidence: number | string | null;
  reason: string | null;
  participates_in_metrics: boolean;
  skipped_reason?: string | null;
  source_scan_timestamp?: string | null;
  position_context_used?: boolean;
  rsi?: number | null;
  mark_price?: number | null;
  trade_plan_available?: boolean;
  fill_assumption?: string | null;
}

export interface DcaSkippedScan {
  timestamp: string | null;
  symbol?: string;
  reason: string;
}

export interface DcaSymbolReconstruction {
  symbol: string;
  status: "metrics_available" | "insufficient_history" | "eligible" | "reconstructing" | "validation_error" | string;
  required_minimum_scans: number;
  scan_count: number;
  first_scan_at: string | null;
  last_scan_at: string | null;
  max_scan_gap_seconds: number | null;
  method?: "scan-to-scan" | string;
  method_description?: string;
  direction?: "LONG" | "SHORT" | string;
  unavailable_source?: string | null;
  events: DcaReconstructionEvent[];
  skipped_scans: DcaSkippedScan[];
  data_quality_warnings?: string[];
}

export interface DcaValidationReconstructionResponse {
  exchange: string;
  method: "scan-to-scan" | string;
  method_description?: string;
  fill_assumptions?: DcaFillAssumptions;
  symbols: DcaSymbolReconstruction[];
}

export interface DcaShadowGateBreakdownItem {
  name: string;
  passed: boolean;
  reason: string;
}

export interface DcaShadowAssumptionSet {
  mode?: string;
  live_execution?: boolean;
  min_confluence_score?: number;
  hourly_add_limit?: number;
  daily_add_limit?: number;
  close_cooldown_hours?: number;
  max_add_size_pct_portfolio?: number;
  exposure_cap_pct?: number;
  fee_percent?: number;
  slippage_percent?: number;
  split_ratio?: number;
  [assumption: string]: unknown;
}

export interface DcaShadowHistoryItem {
  timestamp: string | null;
  exchange?: string;
  symbol: string;
  original_recommendation: DcaRecommendationCategory;
  final_outcome: DcaShadowOutcome;
  gate_breakdown: DcaShadowGateBreakdownItem[];
  blocked_gates: string[];
  assumption_set: DcaShadowAssumptionSet;
  final_reason: string;
}

export interface DcaValidationLastCompleted {
  completed_at: string;
  state: DcaValidationState;
}

export interface DcaValidationResponse {
  state: DcaValidationState;
  exchange: string;
  reconstruction: DcaValidationReconstructionResponse | null;
  metrics: {
    exchange: string;
    split_ratio: number;
    symbols: DcaValidationMetricsBySymbol[];
    portfolio?: { metrics?: Partial<DcaValidationMetricSet> };
  } | null;
  shadow_history: DcaShadowHistoryItem[];
  validation_errors?: { field: string; message: string }[];
  last_completed: DcaValidationLastCompleted | null;
  disclaimer?: string;
}

interface DcaValidationSummaryProps {
  validation: DcaValidationResponse | null;
  unavailableSource?: string | null;
}

export function DcaValidationSummary({ validation, unavailableSource }: DcaValidationSummaryProps) {
  const symbols = validation?.reconstruction?.symbols ?? [];
  const eligibleSymbols = symbols.filter((symbol) => isMetricsAvailable(symbol)).length;
  const usableScans = symbols.reduce((total, symbol) => total + symbol.scan_count, 0);
  const reconstructedRecommendations = symbols.reduce(
    (total, symbol) => total + symbol.events.filter((event) => !event.skipped_reason).length,
    0
  );
  const blockedBySafetyGates = (validation?.shadow_history ?? []).filter(
    (item) => item.final_outcome === "would_block"
  ).length;
  const latestValidation = validation?.last_completed?.completed_at ?? latestTimestamp(symbols);
  const warnings = collectWarnings(validation);

  if (!validation) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5" aria-labelledby="dca-validation-summary-title">
        <SummaryHeading title={unavailableSource ? "Validation unavailable" : "No validation data yet"} />
        <p className="mt-3 text-sm text-slate-400">
          {unavailableSource
            ? `DCA validation could not load because ${unavailableSource} is missing.`
            : "Run validation after stored scans are available. The system needs at least 2 usable scans for a symbol before it can reconstruct recommendations."}
        </p>
        <SummaryDisclaimer />
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5" aria-labelledby="dca-validation-summary-title">
      <SummaryHeading title="DCA validation summary" />
      <dl className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <SummaryStat label="Eligible symbols" value={eligibleSymbols.toLocaleString()} />
        <SummaryStat label="Usable scans" value={usableScans.toLocaleString()} />
        <SummaryStat label="Reconstructed recommendations" value={reconstructedRecommendations.toLocaleString()} />
        <SummaryStat label="Latest validation" value={latestValidation ? formatDateTime(latestValidation) : "Not run yet"} />
        <SummaryStat label="Blocked by safety gates" value={blockedBySafetyGates.toLocaleString()} tone={blockedBySafetyGates > 0 ? "warning" : "default"} />
      </dl>

      <div className="mt-5 grid gap-3 lg:grid-cols-3">
        <InfoBlock label="Method" value="Scan-to-scan, not candle-level replay." />
        <InfoBlock label="Default assumptions" value={formatAssumptions(validation.reconstruction?.fill_assumptions, validation.metrics?.split_ratio)} />
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Data quality</div>
          {warnings.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-amber-200">
              {warnings.map((warning) => (
                <li key={warning} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-300">No active validation warnings.</p>
          )}
        </div>
      </div>

      <SummaryDisclaimer />
    </section>
  );
}

function SummaryHeading({ title }: { title: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-cyan-700/60 bg-cyan-500/10 text-cyan-300">
        <Activity className="h-5 w-5" aria-hidden="true" />
      </div>
      <div>
        <h2 id="dca-validation-summary-title" className="text-lg font-semibold text-slate-100">
          {title}
        </h2>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-cyan-700 bg-cyan-500/10 text-cyan-300">
            Scan-to-scan reconstruction
          </Badge>
          <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300">
            Read-only shadow mode
          </Badge>
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "warning" }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className={tone === "warning" ? "mt-1 text-xl font-semibold tabular-nums text-amber-300" : "mt-1 text-xl font-semibold tabular-nums text-slate-100"}>
        {value}
      </dd>
    </div>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <p className="mt-2 text-sm text-slate-300">{value}</p>
    </div>
  );
}

export function SummaryDisclaimer() {
  return (
    <p className="mt-5 flex gap-2 rounded-lg border border-amber-700/50 bg-amber-500/10 p-3 text-sm text-amber-100">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{DCA_VALIDATION_DISCLAIMER}</span>
    </p>
  );
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

export function formatMetric(value: DcaMetricValue | undefined, suffix = "") {
  if (!value || value.value === null || value.value === undefined) {
    return { value: "—", reason: value?.reason ?? "Not enough usable scans." };
  }
  if (typeof value.value === "number") {
    return { value: `${trimNumber(value.value)}${suffix}`, reason: value.reason ?? null };
  }
  return { value: String(value.value), reason: value.reason ?? null };
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${trimNumber(seconds / 3600)}h`;
  return `${trimNumber(seconds / 86400)}d`;
}

export function humanize(value: string | null | undefined) {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function isMetricsAvailable(symbol: DcaSymbolReconstruction) {
  return symbol.status === "metrics_available" || symbol.status === "eligible" || symbol.scan_count >= symbol.required_minimum_scans;
}

function collectWarnings(validation: DcaValidationResponse | null) {
  const warnings = new Set<string>();
  validation?.reconstruction?.symbols.forEach((symbol) => {
    symbol.data_quality_warnings?.forEach((warning) => warnings.add(warning));
    if ((symbol.max_scan_gap_seconds ?? 0) > 48 * 60 * 60) {
      warnings.add(`${symbol.symbol} has scan gaps over 48 hours.`);
    }
    if (symbol.events.length < 30 && isMetricsAvailable(symbol)) {
      warnings.add(`${symbol.symbol} has fewer than 30 reconstructed events.`);
    }
  });
  validation?.metrics?.symbols.forEach((symbol) => {
    if (symbol.buy_and_hold_benchmark?.value === null && symbol.buy_and_hold_benchmark.reason) {
      warnings.add(`Missing benchmark data for ${symbol.symbol}: ${symbol.buy_and_hold_benchmark.reason}`);
    }
    symbol.warnings?.forEach((warning) => warnings.add(warning));
  });
  return Array.from(warnings);
}

function latestTimestamp(symbols: DcaSymbolReconstruction[]) {
  const latest = symbols
    .map((symbol) => symbol.last_scan_at)
    .filter((timestamp): timestamp is string => Boolean(timestamp))
    .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
  return latest ?? null;
}

function formatAssumptions(assumptions: DcaFillAssumptions | undefined, splitRatio: number | undefined) {
  const fee = assumptions?.fee_percent ?? 0.04;
  const slippage = assumptions?.slippage_percent ?? 0.05;
  const split = splitRatio ?? 0.7;
  return `Fee ${trimNumber(fee)}% · slippage ${trimNumber(slippage)}% per simulated entry/exit · split ${Math.round(split * 100)}% in-sample / ${Math.round((1 - split) * 100)}% out-of-sample.`;
}

function trimNumber(value: number) {
  return Number.isInteger(value) ? value.toLocaleString() : Number(value.toFixed(2)).toLocaleString();
}

export default DcaValidationSummary;
