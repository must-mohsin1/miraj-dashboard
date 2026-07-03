/**
 * Shared TypeScript types for the frontend.
 *
 * These mirror the JSON shapes returned by the FastAPI backend so that
 * Server Components can fetch and render data in a type-safe way.
 */

import type { UTCTimestamp } from "lightweight-charts";

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

/** A single closed/historical position row. */
export interface PositionHistoryItem {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_percent: number;
  leverage: number;
  open_time: string | null;
  close_time: string | null;
  close_reason: string | null;
  contract_size?: number | null;
}

/** A single historical (closed/cancelled) order row. */
export interface OrderHistoryItem {
  symbol: string;
  type: string;
  side: string;
  side_action?: string | null;
  price: number;
  amount: number;
  filled: number;
  filled_price?: number | null;
  cost: number;
  status: string;
  timestamp: string;
  fee?: number | null;
  fee_currency?: string | null;
  leverage?: number | null;
  reduce_only?: number | null;
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
  position_history: PositionHistoryItem[];
  order_history: OrderHistoryItem[];
  snapshot: SnapshotItem | null;
  last_refreshed: string | null;
  stale: boolean;
}

/** Response envelope for `GET /api/v1/history`. */
export interface HistoryResponse {
  exchange: string;
  position_history: PositionHistoryItem[];
  order_history: OrderHistoryItem[];
}

// ── Analytics (Phase 2) ────────────────────────────────────────────────────

/** Response for `GET /api/v1/analytics/{exchange}/performance`. */
export interface PerformanceMetrics {
  /** Percentage of winning trades (0–100). */
  win_rate: number;
  /** Gross profit / gross loss. `null` when there are zero losing trades (∞). */
  profit_factor: number | null;
  /** Simplified per-trade Sharpe (mean/std*sqrt(n)). `null` when < 2 trades. */
  sharpe_ratio: number | null;
  /** Largest peak-to-trough decline in cumulative PnL (USD). */
  max_drawdown: number;
  /** Max drawdown as a percentage of the peak. `null` when peak is 0/negative. */
  max_drawdown_percent: number | null;
  /** Mean PnL of winning trades. */
  average_win: number;
  /** Mean PnL of losing trades. */
  average_loss: number;
  /** Total closed positions. */
  total_trades: number;
  /** Count of profitable trades. */
  winning_trades: number;
  /** Count of losing trades. */
  losing_trades: number;
  /** Best single trade PnL. */
  best_trade: number;
  /** Worst single trade PnL. */
  worst_trade: number;
  /** Total realised PnL. */
  total_pnl: number;
  /** Total realised PnL %. */
  total_pnl_percent: number;
}

/** A single point on the equity curve. */
export interface EquityCurvePoint {
  timestamp: string;
  total_value: number;
}

/** Response for `GET /api/v1/analytics/{exchange}/equity-curve`. */
export interface EquityCurveResponse {
  exchange: string;
  points: EquityCurvePoint[];
}

/** A single day's PnL. */
export interface DailyPnlPoint {
  date: string;
  pnl: number;
}

/** Response for `GET /api/v1/analytics/{exchange}/daily-pnl`. */
export interface DailyPnlResponse {
  exchange: string;
  days: DailyPnlPoint[];
}

/** A single asset allocation entry. */
export interface AllocationItem {
  asset: string;
  usd_value: number;
  percentage: number;
}

/** Response for `GET /api/v1/analytics/{exchange}/allocation`. */
export interface AllocationResponse {
  exchange: string;
  items: AllocationItem[];
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
/** Full response shape for `POST /api/v1/scan/{symbol}`.
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
  /** MACD series (macd, signal, histogram arrays aligned to candles). */
  macd: MacdData | null;
  /** Volume Profile histogram buckets. */
  volume_profile: VolumeProfileData | null;
  /** Bollinger Bands series (upper, middle, lower arrays aligned to candles). */
  bb: BollingerBandsData | null;
  /** RSI series (last 100 values aligned to candles). */
  rsi: number[] | null;
  /** `true` when the result is served from a stale cache. */
  stale: boolean;
  /** ISO-8601 timestamp the result was cached at, or `null`. */
  cached_at: string | null;
}

// ── Trading (Phase 4) ─────────────────────────────────────────────────────

/** Body for POST /api/v1/trading/{exchange}/order. */
export interface PlaceOrderRequest {
  symbol: string;
  type: "limit" | "market";
  side: "buy" | "sell";
  amount: number;
  price?: number | null;
  reduce_only?: boolean;
  leverage?: number | null;
}

/** Response from order placement / cancellation. */
export interface OrderResponse {
  id: string;
  symbol: string;
  type: string;
  side: string;
  amount: number;
  price?: number | null;
  filled: number;
  remaining: number;
  status: string;
  reduce_only?: boolean | null;
  timestamp?: number | null;
  cost?: number | null;
  fee?: Record<string, unknown> | null;
}

/** Response for the trading status endpoint. */
export interface TradingStatusResponse {
  enabled: boolean;
}

/** ── Chart upgrades (Phase 1) ──────────────────────────────────────────── */

/** Accepted timeframe values. */
export type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d" | "1w";

/** Response from `GET /api/v1/charts/{symbol}/candles?timeframe=...&limit=...`. */
export interface CandlesResponse {
  symbol: string;
  timeframe: Timeframe;
  candles: Candle[];
  count?: number;
}

/**
 * MACD indicator series. Arrays of the last N values aligned to the
 * scan response candles array (same length, same order).
 */
export interface MacdData {
  macd: number[];
  signal: number[];
  histogram: number[];
}

/**
 * Bollinger Bands overlay series. Each array holds the last N values
 * aligned 1-to-1 with the scan response candles.
 */
export interface BollingerBandsData {
  upper: number[];
  middle: number[];
  lower: number[];
}

/**
 * Volume Profile (VPVR-style) horizontal histogram. The parallel arrays
 * describe price-level buckets and the volume traded in each.
 */
export interface VolumeProfileData {
  price_levels: number[];
  volumes: number[];
  buy_volumes: number[];
  sell_volumes: number[];
}

/** A single point in a time-value line series aligned to candles. */
export interface TimeValuePoint {
  time: UTCTimestamp;
  value: number;
}

/**
 * Normalised indicator series — each is an array of `{time, value}` points
 * ready for lightweight-charts, aligned to the candle timestamps.
 */
export interface IndicatorSeries {
  rsi?: TimeValuePoint[];
  macd?: {
    macd: TimeValuePoint[];
    signal: TimeValuePoint[];
    histogram: TimeValuePoint[];
  };
  bb?: {
    upper: TimeValuePoint[];
    middle: TimeValuePoint[];
    lower: TimeValuePoint[];
  };
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

// ── Trading Journal (Phase 3) ──────────────────────────────────────────────

/** A single trading-journal entry from `GET/POST /api/v1/journal`. */
export interface TradeJournalEntry {
  /** Database primary key. */
  id: number;
  user_id: number;
  /** Exchange slug (e.g. "mexc"), or `null` for manual entries. */
  exchange: string | null;
  /** Trading pair symbol, e.g. "BTCUSDT". */
  symbol: string;
  /** Optional FK to a PositionHistory row. */
  position_id: number | null;
  /** Free-text trade notes. */
  notes: string | null;
  /** Comma-separated tags, e.g. "scalp,swing,breakout". */
  tags: string | null;
  /** Lessons learned / post-mortem notes. */
  lessons: string | null;
  /** JSON array of screenshot file paths. */
  screenshots: string[];
  /** Trade entry price (copied for quick reference). */
  entry_price: number | null;
  /** Trade exit price (copied for quick reference). */
  exit_price: number | null;
  /** Realised PnL for the trade (copied for quick reference). */
  pnl: number | null;
  /** ISO-8601 creation timestamp. */
  created_at: string;
  /** ISO-8601 last-update timestamp. */
  updated_at: string;
}

/** Response envelope for `GET /api/v1/journal`. */
export interface JournalListResponse {
  total: number;
  entries: TradeJournalEntry[];
}

/** Request body for `POST /api/v1/journal` (create entry). */
export interface JournalEntryCreateRequest {
  symbol: string;
  exchange?: string | null;
  position_id?: number | null;
  notes?: string | null;
  tags?: string | null;
  lessons?: string | null;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl?: number | null;
}

/** Request body for `PUT /api/v1/journal/{id}` (update entry). */
export interface JournalEntryUpdateRequest {
  notes?: string | null;
  tags?: string | null;
  lessons?: string | null;
}

/** Per-tag aggregates inside the journal summary. */
export interface JournalTagStat {
  /** Number of entries with this tag. */
  trade_count: number;
  /** Sum of PnL across tagged entries. */
  total_pnl: number;
  /** Entries with PnL > 0. */
  winning_trades: number;
  /** Entries with PnL < 0. */
  losing_trades: number;
  /** Win rate (0–100) of decisive trades. */
  win_rate: number;
}

/** Response for `GET /api/v1/analytics/{exchange}/journal-summary`. */
export interface JournalSummaryResponse {
  exchange: string;
  total_entries: number;
  tags: Record<string, JournalTagStat>;
}

/** Response for `POST /api/v1/journal/{id}/screenshot`. */
export interface JournalScreenshotUploadResponse {
  entry_id: number;
  filename: string;
  path: string;
}

/** Response for `GET /api/v1/journal/{id}/screenshots`. */
export interface JournalScreenshotListResponse {
  entry_id: number;
  screenshots: string[];
}
