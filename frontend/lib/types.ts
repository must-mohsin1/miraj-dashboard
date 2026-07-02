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

// ── Watchlist ───────────────────────────────────────────────────────────────

/**
 * A single watchlist pair row, as returned by the FastAPI backend's
 * `GET /api/v1/watchlist` (inside the `pairs` array) and `POST /api/v1/watchlist`
 * endpoints.
 *
 * The backend stores the trading pair under the `pair` field (e.g. "BTCUSDT").
 * `score` and `status` are enrichment fields that the backend populates with
 * `null` / "Active" when no scan has run yet.
 */
export interface WatchlistPair {
  /** Database primary key. */
  id: number;
  user_id: number;
  /** Trading pair symbol, e.g. "BTCUSDT". */
  pair: string;
  sort_order: number;
  /** ISO-8601 creation timestamp. */
  created_at: string;
  /** Latest confluence score (0–100) or `null` when no scan has run. */
  score: number | null;
  /** Human-readable status, e.g. "Active". */
  status: string;
}

/** Response envelope for `GET /api/v1/watchlist`. */
export interface WatchlistResponse {
  total: number;
  pairs: WatchlistPair[];
}

/** Request body for `POST /api/v1/watchlist`. */
export interface WatchlistCreateRequest {
  pair: string;
}

/**
 * Shape of the scan result persisted to the analyses table. The full result
 * from `POST /api/v1/scan/{symbol}` is a richer object (see `ScanResult`);
 * this trimmed shape is what the history endpoint returns per row.
 */
export interface AnalysisHistoryItem {
  id: number;
  user_id: number;
  pair: string;
  analysis_type: string;
  parameters: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  created_at: string;
}

/** Response envelope for the paginated history endpoint. */
export interface HistoryResponse {
  items: AnalysisHistoryItem[];
  total: number;
  page: number;
  page_size: number;
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
