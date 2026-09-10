import { serverFetch } from "@/lib/api";
import type {
  CollectorReport,
  CollectorReportStatus,
  CollectorSetupStateName,
  CollectorVerdictState,
  LatestCollectorReportResponse,
} from "@/lib/collector-report-types";

const REPORT_STATUSES = new Set<CollectorReportStatus>(["received", "validated", "stale", "failed", "unavailable"]);
const VERDICT_STATES = new Set<CollectorVerdictState>(["NO_TRADE", "WATCH", "READY_LONG", "READY_SHORT", "INVALIDATED", "STALE"]);
const SETUP_STATE_NAMES = ["S0", "S1", "S2", "S3", "S4", "S5"] as const satisfies readonly CollectorSetupStateName[];

export function buildLatestCollectorReportPath(symbol = "SOLUSDT"): string {
  const normalized = symbol.trim().toUpperCase();
  return `/api/v1/collector-reports/latest?symbol=${encodeURIComponent(normalized || "SOLUSDT")}`;
}

export async function fetchLatestCollectorReport(
  symbol = "SOLUSDT",
  token?: string | null,
): Promise<LatestCollectorReportResponse> {
  const payload = await serverFetch<unknown>(buildLatestCollectorReportPath(symbol), token);
  return parseLatestCollectorReport(payload);
}

export function parseLatestCollectorReport(payload: unknown): LatestCollectorReportResponse {
  if (!isRecord(payload) || typeof payload.status !== "string" || !REPORT_STATUSES.has(payload.status as CollectorReportStatus)) {
    throw new Error("Invalid collector report response: unknown status");
  }
  if (typeof payload.stale !== "boolean") throw new Error("Invalid collector report response: stale must be boolean");
  if (payload.received_at !== null && typeof payload.received_at !== "string") throw new Error("Invalid collector report response: received_at must be string or null");
  if (payload.report !== null && payload.report !== undefined) assertReport(payload.report);
  if ((payload.status === "validated" || payload.status === "stale") && !payload.report) {
    throw new Error("Invalid collector report response: report required for validated or stale status");
  }

  return {
    status: payload.status as CollectorReportStatus,
    stale: payload.stale,
    received_at: (payload.received_at as string | null) ?? null,
    report: (payload.report as CollectorReport | null) ?? null,
  };
}

function assertReport(value: unknown): asserts value is CollectorReport {
  if (!isRecord(value) || !hasOnlyKeys(value, ["report_id", "payload_sha256", "generated_at", "symbol", "venue", "source", "schema_version", "verdict", "quote", "scores", "timeframes", "source_health", "limitations", "setup_states"])) {
    throw new Error("Invalid collector report: expected allowlisted object");
  }
  for (const key of ["report_id", "payload_sha256", "generated_at", "symbol", "venue", "source", "schema_version"] as const) {
    if (typeof value[key] !== "string") throw new Error(`Invalid collector report: missing ${key}`);
  }
  if (!isRecord(value.verdict) || !hasOnlyKeys(value.verdict, ["state", "summary", "gates"]) || typeof value.verdict.state !== "string" || !VERDICT_STATES.has(value.verdict.state as CollectorVerdictState)) {
    throw new Error("Invalid collector report: unknown verdict state");
  }
  if (typeof value.verdict.summary !== "string" || !Array.isArray(value.verdict.gates) || !value.verdict.gates.every(isGate)) throw new Error("Invalid collector report: invalid verdict");
  if (!isRecord(value.quote) || !hasOnlyKeys(value.quote, ["price", "as_of", "context_only"]) || !isNullableNumber(value.quote.price) || !isNullableString(value.quote.as_of) || typeof value.quote.context_only !== "boolean") {
    throw new Error("Invalid collector report: invalid quote");
  }
  if (!Array.isArray(value.scores) || !value.scores.every(isScore)) throw new Error("Invalid collector report: invalid scores");
  if (!Array.isArray(value.timeframes) || !value.timeframes.every(isTimeframe)) throw new Error("Invalid collector report: invalid timeframes");
  if (!Array.isArray(value.source_health) || !value.source_health.every(isSourceHealth)) throw new Error("Invalid collector report: invalid source_health");
  if (!Array.isArray(value.limitations) || !value.limitations.every((limitation) => typeof limitation === "string")) throw new Error("Invalid collector report: invalid limitations");
  const setupStates = value.setup_states;
  if (!Array.isArray(setupStates) || setupStates.length !== SETUP_STATE_NAMES.length || !SETUP_STATE_NAMES.every((name, index) => {
    const entry = setupStates[index];
    return isRecord(entry) && hasOnlyKeys(entry, ["state", "status", "label", "reason"]) && entry.state === name && isGateState(entry.status) && typeof entry.label === "string" && isOptionalString(entry.reason);
  })) {
    throw new Error("Invalid collector report: setup_states must include S0 through S5");
  }
}

function isGate(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ["label", "state", "reason"]) && typeof value.label === "string" && isGateState(value.state) && isOptionalString(value.reason);
}

function isScore(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ["label", "value", "maximum", "detail"]) && typeof value.label === "string" && isNullableNumber(value.value) && isNullableNumber(value.maximum) && isOptionalString(value.detail);
}

function isTimeframe(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ["timeframe", "state", "close", "as_of", "candles", "fvg", "ote", "metrics"]) && typeof value.timeframe === "string" && typeof value.state === "string" && isNullableNumber(value.close) && isNullableString(value.as_of) && Array.isArray(value.candles) && value.candles.every(isCandle) && isOptionalRange(value.fvg) && isOptionalRange(value.ote) && isOptionalTimeframeMetrics(value.metrics);
}

function isCandle(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ["time", "open", "high", "low", "close", "volume"]) && typeof value.time === "string" && isNumber(value.open) && isNumber(value.high) && isNumber(value.low) && isNumber(value.close) && isOptionalNumber(value.volume);
}

function isSourceHealth(value: unknown): boolean {
  return isRecord(value) && hasOnlyKeys(value, ["source", "status", "checked_at", "fallback", "detail"]) && typeof value.source === "string" && typeof value.status === "string" && ["ok", "degraded", "failed", "unavailable"].includes(value.status) && isNullableString(value.checked_at) && typeof value.fallback === "boolean" && isOptionalString(value.detail);
}

function isOptionalRange(value: unknown): boolean {
  return value === undefined || value === null || (isRecord(value) && hasOnlyKeys(value, ["low", "high"]) && isNumber(value.low) && isNumber(value.high));
}

function isOptionalTimeframeMetrics(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (!isRecord(value) || !hasOnlyKeys(value, ["completed_count", "first_completed_open_utc", "completed_rows_sha256", "close", "close_time_utc", "open_time_utc", "rsi14", "ema", "last_volume_base", "volume20_base", "high20", "low20", "bollinger", "volume_vs20"])) return false;
  return isOptionalNumber(value.completed_count) && isOptionalString(value.first_completed_open_utc) && isOptionalString(value.completed_rows_sha256) && isOptionalNumber(value.close) && isOptionalString(value.close_time_utc) && isOptionalString(value.open_time_utc) && isOptionalNumber(value.rsi14) && isOptionalEma(value.ema) && isOptionalNumber(value.last_volume_base) && isOptionalNumber(value.volume20_base) && isOptionalNumber(value.high20) && isOptionalNumber(value.low20) && isOptionalBollinger(value.bollinger) && isOptionalNumber(value.volume_vs20);
}

function isOptionalEma(value: unknown): boolean {
  return value === undefined || value === null || (isRecord(value) && hasOnlyKeys(value, ["20", "50", "200"]) && isOptionalNumber(value["20"]) && isOptionalNumber(value["50"]) && isOptionalNumber(value["200"]));
}

function isOptionalBollinger(value: unknown): boolean {
  return value === undefined || value === null || (isRecord(value) && hasOnlyKeys(value, ["width_pct", "mean_width_pct", "squeeze"]) && isOptionalNumber(value.width_pct) && isOptionalNumber(value.mean_width_pct) && (value.squeeze === undefined || value.squeeze === null || typeof value.squeeze === "boolean"));
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function isGateState(value: unknown): boolean {
  return typeof value === "string" && ["passed", "blocked", "pending", "unavailable"].includes(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableNumber(value: unknown): boolean {
  return value === null || isNumber(value);
}

function isOptionalNumber(value: unknown): boolean {
  return value === undefined || value === null || isNumber(value);
}

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === "string";
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
