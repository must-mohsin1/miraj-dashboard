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

// ── Portfolio (multi-exchange) ─────────────────────────────────────────────

/**
 * Response for `GET /api/v1/portfolio/exchanges`.
 * Lists the exchange slugs supported by the backend (e.g. ["mexc","binance","bybit"]).
 */
export interface ExchangesResponse {
  exchanges: string[];
}

/** Response for `GET /api/v1/portfolio/{exchange}/keys`. */
export interface KeysResponse {
  connected: boolean;
  masked_key: string | null;
}

/** Response for `POST /api/v1/portfolio/mexc/connect`. */
export interface ConnectResponse {
  connected: boolean;
  exchange: string;
  masked_key: string;
}

/** A single balance row from the portfolio endpoint. */
export interface BalanceItem {
  asset: string;
  free: number;
  locked: number;
  total: number;
  usd_value: number | null;
}

/** A single open position row. */
export interface PositionItem {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  mark_price: number;
  pnl: number;
  pnl_percent: number;
  leverage: number;
  liquidation_price: number | null;
  margin: number;
  contract_size?: number | null;
}

/** A single trade row. */
export interface TradeItem {
  symbol: string;
  side: string;
  type: string;
  price: number;
  amount: number;
  cost: number;
  fee: number | null;
  fee_currency: string | null;
  timestamp: string;
  exchange_trade_id: string;
}

/** Aggregated portfolio snapshot metrics. */
export interface SnapshotItem {
  total_balance_usd: number | null;
  total_pnl_usd: number;
  open_positions: number;
  timestamp: string;
}

/** Response for `GET/POST /api/v1/portfolio/mexc`. */
export interface PortfolioResponse {
  exchange: string;
  balances: BalanceItem[];
  positions: PositionItem[];
  trades: TradeItem[];
  snapshot: SnapshotItem | null;
  last_refreshed: string | null;
  stale: boolean;
}

// ── Settings ───────────────────────────────────────────────────────────────

/** Per-pair alert settings row from `GET /api/v1/settings/pairs`. */
export interface PairSettingsResponse {
  id: number;
  user_id: number;
  pair: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** A single alert channel row from `GET /api/v1/settings/channels`. */
export interface AlertChannel {
  id: number;
  user_id: number;
  channel_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** Response envelope for `GET /api/v1/settings/channels`. */
export interface AlertChannelListResponse {
  total: number;
  channels: AlertChannel[];
}

// ── Price Alerts ───────────────────────────────────────────────────────────

/** A single price alert row from `GET /api/v1/alerts/price`. */
export interface PriceAlertResponse {
  id: number;
  user_id: number;
  symbol: string;
  alert_type: string;
  direction: string;
  price_level: number;
  current_price: number | null;
  message: string | null;
  status: string;
  triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Response envelope for `GET /api/v1/alerts/price`. */
export interface PriceAlertListResponse {
  total: number;
  alerts: PriceAlertResponse[];
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

// ── Analysis / Scan ────────────────────────────────────────────────────────

/**
 * A single OHLCV candle bar as returned by the scan endpoint's `candles`
 * array. `time` is an ISO-8601 string (or epoch seconds) suitable for
 * lightweight-charts.
 */
export interface Candle {
  time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

/**
 * EMA overlay data. The backend returns a dict keyed by EMA period string
 * (e.g. "ema_9", "ema_50") whose value is an array of the last N floats,
 * aligned 1-to-1 with the `candles` array. There are no per-point timestamps
 * baked in — the frontend re-aligns them to the candle times.
 */
export type EmaData = Record<string, number[]>;

/**
 * An order block zone rendered as a rectangle on the chart. `type` is
 * "bullish" or "bearish" and controls the fill colour.
 */
export interface OrderBlock {
  start_time: string | number;
  end_time: string | number;
  price_high: number | null;
  price_low: number | null;
  type: string;
}

/** A fair-value-gap zone rendered as a dashed rectangle on the chart. */
export interface FairValueGap {
  start_time: string | number;
  end_time: string | number;
  price_high: number | null;
  price_low: number | null;
}

/**
 * The flat, UI-friendly trade plan derived by the backend from the full
 * `trade_plan` object. Entry / stop / targets are plain floats (or null
 * when unavailable). `rationale` is a free-text human explanation.
 */
export interface TradePlanFlat {
  direction: string;
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  target_3?: number | null;
  rationale?: string | null;
}

/**
 * Category-level sub-scores (0–5 raw points each). Keys: regime, location,
 * confirmation, volume_retest, risk.
 */
export type CategoryScores = Record<string, number>;

/**
 * Full response shape for `POST /api/v1/scan/{symbol}`.
 *
 * Mirrors the backend `ScanResponse` Pydantic model. Optional fields are
 * nullable because any given pipeline step may fail and the backend
 * substitutes `null` / empty instead of raising.
 */
export interface ScanResult {
  symbol: string;
  /** Overall confluence score scaled to 0–100 (may be null on failure). */
  overall_score: number | null;
  /** Raw confluence score out of 30. */
  confluence_score: number;
  /** Per-category sub-scores (regime, location, confirmation, volume_retest, risk). */
  scores: CategoryScores | null;
  /** Full trade plan object from the backend (nested shape). */
  trade_plan: Record<string, unknown>;
  /** Flat, UI-friendly trade plan (entry/stop/targets/direction). */
  trade_plan_flat: TradePlanFlat | null;
  /** Breakdown of the confluence score (category objects with `score`/`max`). */
  score_breakdown: Record<string, unknown>;
  macro_data: Record<string, unknown> | null;
  smc: Record<string, unknown> | null;
  patterns: Record<string, unknown> | null;
  qqe: Record<string, unknown> | null;
  indicators: Record<string, unknown> | null;
  /** Last 100 daily candles for the chart. */
  candles: Candle[] | null;
  /** EMA overlay series keyed by period string. */
  emas: EmaData | null;
  /** Order block zones for the chart. */
  order_blocks: OrderBlock[] | null;
  /** Fair-value-gap zones for the chart. */
  fvgs: FairValueGap[] | null;
  /** `true` when the result is served from a stale cache. */
  stale: boolean;
  /** ISO-8601 timestamp the result was cached at, or `null`. */
  cached_at: string | null;
}

// ── History (analyses list) ────────────────────────────────────────────────

/** A single row in the paginated history response from `GET /api/v1/history`. */
export interface HistoryRow {
  id: number;
  symbol: string;
  analysis_type: string;
  score: number | null;
  direction: string | null;
  alert_sent: boolean;
  created_at: string;
}

/** Response envelope for `GET /api/v1/history`. */
export interface ScanHistoryResponse {
  rows: HistoryRow[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}
