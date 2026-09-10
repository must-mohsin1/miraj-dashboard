export type CollectorReportStatus = "received" | "validated" | "stale" | "failed" | "unavailable";
export type CollectorVerdictState = "NO_TRADE" | "WATCH" | "READY_LONG" | "READY_SHORT" | "INVALIDATED" | "STALE";
export type CollectorGateState = "passed" | "blocked" | "pending" | "unavailable";
export type CollectorSetupStateName = "S0" | "S1" | "S2" | "S3" | "S4" | "S5";
export type CollectorSourceStatus = "ok" | "degraded" | "failed" | "unavailable";

export interface CollectorCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
}

export interface CollectorLevelRange {
  low: number;
  high: number;
}

export interface CollectorEmaMetrics {
  "20"?: number | null;
  "50"?: number | null;
  "200"?: number | null;
}

export interface CollectorBollingerMetrics {
  width_pct?: number | null;
  mean_width_pct?: number | null;
  squeeze?: boolean | null;
}

export interface CollectorTimeframeMetrics {
  completed_count?: number | null;
  first_completed_open_utc?: string | null;
  completed_rows_sha256?: string | null;
  close?: number | null;
  close_time_utc?: string | null;
  open_time_utc?: string | null;
  rsi14?: number | null;
  ema?: CollectorEmaMetrics | null;
  last_volume_base?: number | null;
  volume20_base?: number | null;
  high20?: number | null;
  low20?: number | null;
  bollinger?: CollectorBollingerMetrics | null;
  volume_vs20?: number | null;
}

export interface CollectorTimeframeEvidence {
  timeframe: string;
  state: string;
  close: number | null;
  as_of: string | null;
  candles: CollectorCandle[];
  fvg?: CollectorLevelRange | null;
  ote?: CollectorLevelRange | null;
  metrics?: CollectorTimeframeMetrics | null;
}

export interface CollectorSetupState {
  state: CollectorSetupStateName;
  status: CollectorGateState;
  label: string;
  reason?: string | null;
}

export interface CollectorReport {
  report_id: string;
  payload_sha256: string;
  generated_at: string;
  symbol: string;
  venue: string;
  source: string;
  schema_version: string;
  verdict: {
    state: CollectorVerdictState;
    summary: string;
    gates: Array<{ label: string; state: CollectorGateState; reason?: string | null }>;
  };
  quote: { price: number | null; as_of: string | null; context_only: boolean };
  scores: Array<{ label: string; value: number | null; maximum: number | null; detail?: string | null }>;
  timeframes: CollectorTimeframeEvidence[];
  source_health: Array<{ source: string; status: CollectorSourceStatus; checked_at: string | null; fallback: boolean; detail?: string | null }>;
  limitations: string[];
  setup_states: CollectorSetupState[];
}

export interface LatestCollectorReportResponse {
  status: CollectorReportStatus;
  stale: boolean;
  received_at: string | null;
  report: CollectorReport | null;
}
