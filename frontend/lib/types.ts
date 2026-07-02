/**
 * Shared TypeScript types for the frontend.
 *
 * These mirror the JSON shapes returned by the FastAPI backend so that
 * Server Components can fetch and render data in a type-safe way.
 */

/** Shape of ``data`` inside the ``GET /api/v1/macro`` response. */
export interface MacroData {
  /** BTC dominance as a percentage (e.g. 52.34). `null` when the source failed. */
  btc_dominance: number | null;
  /** USDT dominance as a percentage (e.g. 4.21). `null` when the source failed. */
  usdt_dominance: number | null;
  /** US Dollar Index (DXY) latest value. `null` when the source failed. */
  dxy: number | null;
  /** Error message for the DXY source, surfaced only when `dxy` is null. */
  dxy_error: string | null;
  /** Fear & Greed index value (0–100). `null` when the source failed. */
  fear_greed_index: number | null;
  /** Human label for the Fear & Greed value (e.g. "Fear", "Greed"). */
  fear_greed_label: string | null;
  /** Binance global long/short account ratio for BTCUSDT. */
  binance_ls_ratio: number | null;
  /** Heuristic market regime: "risk-on" | "risk-off" | "mixed". */
  regime: string | null;
}

/** A single per-source error reported by the macro endpoint. */
export interface MacroSourceError {
  field: string;
  message: string;
}

/** Full ``GET /api/v1/macro`` response envelope. */
export interface MacroResponse {
  data: MacroData;
  /** ISO-8601 timestamp of the last successful cache refresh, or `null`. */
  cached_at: string | null;
  /** `true` when the cached data is older than the refresh TTL. */
  stale: boolean;
  /** Per-source errors, or `null` when every source succeeded. */
  errors: MacroSourceError[] | null;
}
