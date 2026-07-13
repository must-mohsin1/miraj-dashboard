import { serverFetch } from "@/lib/api";
import type {
  DcaShadowHistoryFilters,
  DcaValidationFilters,
  DcaValidationResponse,
  DcaValidationState,
} from "@/lib/dca-validation-types";

const VALIDATION_STATES = new Set<DcaValidationState>([
  "metrics_available",
  "insufficient_history",
  "reconstructing",
  "validation_error",
]);

function encodeSegment(value: string): string {
  return encodeURIComponent(value.trim().toLowerCase());
}

function appendDateParam(params: URLSearchParams, key: string, value: string | Date | null | undefined): void {
  if (!value) return;
  params.set(key, value instanceof Date ? value.toISOString() : value);
}

export function buildDcaValidationPath(exchange: string, filters: DcaValidationFilters = {}): string {
  const params = new URLSearchParams();
  const symbol = filters.symbol?.trim();
  if (symbol) params.set("symbol", symbol.toUpperCase());
  appendDateParam(params, "start_date", filters.startDate);
  appendDateParam(params, "end_date", filters.endDate);
  if (filters.splitRatio != null) params.set("split_ratio", String(filters.splitRatio));
  if (filters.timeoutMs != null) params.set("timeout_ms", String(filters.timeoutMs));
  if (filters.shadowOutcome) params.set("outcome", filters.shadowOutcome);
  if (filters.shadowLimit != null) params.set("limit", String(filters.shadowLimit));

  const query = params.toString();
  const base = `/api/v1/dca-validation/${encodeSegment(exchange)}`;
  return query ? `${base}?${query}` : base;
}

export function buildDcaShadowHistoryQuery(filters: DcaShadowHistoryFilters = {}): string {
  const params = new URLSearchParams();
  const symbol = filters.symbol?.trim();
  if (symbol) params.set("symbol", symbol.toUpperCase());
  if (filters.outcome) params.set("outcome", filters.outcome);
  appendDateParam(params, "start_date", filters.startDate);
  appendDateParam(params, "end_date", filters.endDate);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  return params.toString();
}

export async function fetchDcaValidation(
  exchange: string,
  token?: string | null,
  filters: DcaValidationFilters = {}
): Promise<DcaValidationResponse> {
  const payload = await serverFetch<unknown>(buildDcaValidationPath(exchange, filters), token);
  return parseDcaValidationResponse(payload);
}

export function parseDcaValidationResponse(payload: unknown): DcaValidationResponse {
  if (!isRecord(payload)) {
    throw new Error("Invalid DCA validation response: expected an object");
  }

  if (typeof payload.state !== "string" || !VALIDATION_STATES.has(payload.state as DcaValidationState)) {
    throw new Error("Invalid DCA validation response: unknown state");
  }

  if (typeof payload.exchange !== "string" || !isRecord(payload.request)) {
    throw new Error("Invalid DCA validation response: missing exchange or request echo");
  }

  const reconstruction = payload.reconstruction;
  if (reconstruction !== null && reconstruction !== undefined) {
    assertReconstruction(reconstruction);
  }

  if (payload.metrics !== null && payload.metrics !== undefined && !isRecord(payload.metrics)) {
    throw new Error("Invalid DCA validation response: metrics must be an object or null");
  }

  if (!Array.isArray(payload.shadow_history)) {
    throw new Error("Invalid DCA validation response: shadow_history must be an array");
  }

  if (!Array.isArray(payload.validation_errors)) {
    throw new Error("Invalid DCA validation response: validation_errors must be an array");
  }

  if (payload.state === "insufficient_history") {
    assertInsufficientHistoryShape(reconstruction);
  }

  return payload as unknown as DcaValidationResponse;
}

function assertReconstruction(value: unknown): void {
  if (!isRecord(value)) {
    throw new Error("Invalid DCA validation response: reconstruction must be an object or null");
  }
  if (value.method !== "scan-to-scan") {
    throw new Error("Invalid DCA validation response: reconstruction method must be scan-to-scan");
  }
  if (!Array.isArray(value.symbols)) {
    throw new Error("Invalid DCA validation response: reconstruction symbols must be an array");
  }
}

function assertInsufficientHistoryShape(reconstruction: unknown): void {
  if (!isRecord(reconstruction) || !Array.isArray(reconstruction.symbols)) {
    throw new Error("Invalid DCA validation response: insufficient history requires reconstruction symbols");
  }
  for (const symbol of reconstruction.symbols) {
    if (!isRecord(symbol)) {
      throw new Error("Invalid DCA validation response: invalid symbol reconstruction");
    }
    if (symbol.status !== "insufficient_history") continue;
    if (typeof symbol.required_minimum_scans !== "number" || typeof symbol.scan_count !== "number") {
      throw new Error("Invalid DCA validation response: insufficient history requires scan counts");
    }
    if (!Array.isArray(symbol.events) || symbol.events.length !== 0) {
      throw new Error("Invalid DCA validation response: insufficient history must not include metric events");
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
