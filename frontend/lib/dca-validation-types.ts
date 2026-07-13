/**
 * TypeScript types for the read-only DCA shadow-mode validation API.
 *
 * These mirror the backend response from GET /api/v1/dca-validation/{exchange}
 * and intentionally keep JSON-valued audit payloads as records so future
 * backend fields remain renderable without weakening the stable envelope.
 */

export const DCA_VALIDATION_RECONSTRUCTION_METHOD = "scan-to-scan" as const;
export const DCA_VALIDATION_RECONSTRUCTION_LABEL = "scan-history reconstruction" as const;
export const DCA_VALIDATION_SIMULATED_METRICS_LABEL = "simulated metrics" as const;
export const DCA_VALIDATION_DISCLAIMER =
  "These are reconstructed and shadow-mode results, not realized trading performance or financial advice." as const;

export type DcaValidationState =
  | "metrics_available"
  | "insufficient_history"
  | "reconstructing"
  | "validation_error";

export type DcaRecommendationCategory = "ADD" | "HOLD" | "REDUCE" | "CLOSE";

export type DcaShadowOutcome =
  | "would_allow"
  | "would_block"
  | "would_reduce"
  | "would_close"
  | "no_action";

export type DcaSkippedScanReason =
  | "missing_trade_plan"
  | "missing_rsi"
  | "missing_mark_price"
  | "malformed_scan_result"
  | "unsupported_direction"
  | "missing_position_context"
  | string;

export interface DcaValidationRequestEcho {
  exchange: string;
  symbol: string | null;
  start_date: string | null;
  end_date: string | null;
  split_ratio: number;
  timeout_ms: number;
}

export interface DcaValidationErrorItem {
  field: string;
  message: string;
}

export interface DcaMetricValue<T = number> {
  value: T | null;
  reason?: string | null;
}

export interface DcaValidationMetricSet {
  win_rate: DcaMetricValue;
  total_return: DcaMetricValue;
  gross_profit: DcaMetricValue;
  gross_loss: DcaMetricValue;
  profit_factor: DcaMetricValue;
  max_drawdown_absolute: DcaMetricValue;
  max_drawdown_percent: DcaMetricValue;
  sharpe: DcaMetricValue;
  sortino: DcaMetricValue;
  average_hold_time_hours: DcaMetricValue;
  exposure_percentage: DcaMetricValue;
  reconstructed_trade_count: DcaMetricValue;
  [metric: string]: DcaMetricValue | undefined;
}

export interface DcaValidationDcaMetricSet {
  entry_level_completion_rate: DcaMetricValue;
  average_entry_price_vs_planned_zone: DcaMetricValue<Record<string, number | null>>;
  add_follow_through_rate: DcaMetricValue;
  dca_safe_flag_accuracy: DcaMetricValue;
  three_entry_completion_rate: DcaMetricValue;
  [metric: string]: DcaMetricValue<unknown> | undefined;
}

export interface DcaDateRange {
  start: string | null;
  end: string | null;
}

export interface DcaWalkForwardPeriod {
  date_range: DcaDateRange;
  metrics: DcaValidationMetricSet;
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
  metrics: DcaValidationMetricSet;
  dca_metrics?: DcaValidationDcaMetricSet;
  walk_forward?: DcaWalkForwardMetrics;
  buy_and_hold_benchmark?: DcaBuyAndHoldBenchmark;
  warnings?: string[];
}

export interface DcaValidationMetricsResponse {
  exchange: string;
  split_ratio: number;
  symbols: DcaValidationMetricsBySymbol[];
  portfolio: {
    metrics: Partial<DcaValidationMetricSet>;
    dca_metrics?: Partial<DcaValidationDcaMetricSet>;
    buy_and_hold_benchmark?: DcaBuyAndHoldBenchmark;
  };
}

export interface DcaFillAssumptions {
  long_thresholds?: number[];
  short_thresholds?: number[];
  long_rsi_entries?: number[];
  short_rsi_entries?: number[];
  allocations?: number[];
  allocation_percentages?: number[];
  slippage_percent: number;
  fee_percent: number;
  [assumption: string]: string | number | boolean | number[] | null | undefined;
}

export interface DcaReconstructionEvent {
  timestamp: string | null;
  symbol: string;
  recommendation: DcaRecommendationCategory | string;
  confidence: number | string | null;
  reason: string | null;
  participates_in_metrics: boolean;
  method?: typeof DCA_VALIDATION_RECONSTRUCTION_METHOD | string;
  entry_level?: number;
  rsi_threshold?: number;
  allocation_percent?: number;
  raw_price?: number;
  fill_price?: number;
  fee?: number;
  slippage_impact?: number;
  fill_assumption?: string;
  dca_safe?: boolean;
  planned_entry_zone?: [number, number];
}

export interface DcaSkippedScan {
  timestamp: string | null;
  symbol?: string;
  reason: DcaSkippedScanReason;
}

export interface DcaReconstructedFill {
  level: number;
  threshold: number;
  allocation_percent: number;
  timestamp: string | null;
  raw_price: number;
  fill_price: number;
  notional: number;
  quantity: number;
  fee: number;
  slippage_impact: number;
  fill_assumption: string;
}

export interface DcaReconstructedPosition {
  status: "open" | "closed" | string;
  direction?: "LONG" | "SHORT" | string;
  fills: DcaReconstructedFill[];
  valuation_price?: number;
  valuation_timestamp?: string | null;
  exit_price?: number;
  exit_timestamp?: string | null;
  exit_signal?: DcaRecommendationCategory | string;
}

export interface DcaReconstructedPnl {
  gross_pnl: number;
  fees: number;
  slippage_impact: number;
  net_pnl: number;
}

export interface DcaSymbolReconstruction {
  symbol: string;
  status: "metrics_available" | "insufficient_history" | "eligible" | string;
  required_minimum_scans: number;
  scan_count: number;
  first_scan_at: string | null;
  last_scan_at: string | null;
  max_scan_gap_seconds: number | null;
  method?: typeof DCA_VALIDATION_RECONSTRUCTION_METHOD | string;
  method_description?: string;
  events: DcaReconstructionEvent[];
  reconstructed_position?: DcaReconstructedPosition | null;
  pnl?: DcaReconstructedPnl | null;
  skipped_scans: DcaSkippedScan[];
  data_quality_warnings?: string[];
}

export interface DcaValidationReconstructionResponse {
  exchange: string;
  method: typeof DCA_VALIDATION_RECONSTRUCTION_METHOD | string;
  method_description: string;
  fill_assumptions: DcaFillAssumptions;
  symbols: DcaSymbolReconstruction[];
}

export interface DcaShadowGateBreakdownItem {
  name: string;
  passed: boolean;
  reason: string;
  details?: Record<string, unknown>;
}

export interface DcaShadowAssumptionSet {
  mode?: "shadow_non_live" | string;
  live_execution?: false | boolean;
  outcomes?: DcaShadowOutcome[];
  min_confluence_score?: number;
  hourly_add_limit?: number;
  daily_add_limit?: number;
  close_cooldown_hours?: number;
  max_add_size_pct_portfolio?: number;
  default_exposure_cap_pct?: number;
  exposure_cap_pct?: number;
  portfolio_value?: number;
  current_dca_exposure?: number;
  simulated_add_size?: number;
  [assumption: string]: unknown;
}

export interface DcaShadowHistoryItem {
  timestamp: string | null;
  exchange?: string;
  symbol: string;
  original_recommendation: DcaRecommendationCategory | string;
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
  request: DcaValidationRequestEcho;
  reconstruction: DcaValidationReconstructionResponse | null;
  metrics: DcaValidationMetricsResponse | null;
  shadow_history: DcaShadowHistoryItem[];
  validation_errors: DcaValidationErrorItem[];
  last_completed: DcaValidationLastCompleted | null;
  disclaimer: typeof DCA_VALIDATION_DISCLAIMER | string;
}

export interface DcaValidationFilters {
  symbol?: string | null;
  startDate?: string | Date | null;
  endDate?: string | Date | null;
  splitRatio?: number | null;
  timeoutMs?: number | null;
  shadowOutcome?: DcaShadowOutcome | null;
  shadowLimit?: number | null;
}

export interface DcaShadowHistoryFilters {
  symbol?: string | null;
  outcome?: DcaShadowOutcome | null;
  startDate?: string | Date | null;
  endDate?: string | Date | null;
  limit?: number | null;
}
