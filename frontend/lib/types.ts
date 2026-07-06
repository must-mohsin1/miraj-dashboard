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
  /** Per-asset funding rates from Binance Futures. `null` when the source failed. */
  funding_rates?: Array<{
    symbol: string;
    funding_rate: number;
    funding_rate_percent: number;
  }>;
  /** Unfilled CME gaps on BTC weekly candles. `null` when the source failed. */
  cme_gaps?: Array<{
    date: string;
    gap_percent: number;
    direction: string;
    filled: boolean;
  }>;
  /** Heuristic market regime: "risk-on" | "risk-off" | "mixed". */
  regime: string | null;
  /** S&P 500 latest close (from yfinance ^GSPC). `null` when the source failed. */
  sp500?: number | null;
  /** S&P 500 daily change percentage vs. previous session close. `null` when unavailable. */
  sp500_change?: number | null;
  /** Nasdaq Composite latest close (from yfinance ^IXIC). `null` when the source failed. */
  nasdaq?: number | null;
  /** Nasdaq daily change percentage vs. previous session close. `null` when unavailable. */
  nasdaq_change?: number | null;
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

// ── Trade attribution (scan linking) ────────────────────────────────────────

/** A single closed position linked to the scan that preceded its entry.
 *  Response item from `GET /api/v1/portfolio/{exchange}/trade-attribution`. */
export interface TradeAttributionItem {
  position_symbol: string;
  position_side: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_percent: number;
  leverage: number;
  open_time: string | null;
  close_time: string | null;
  close_reason: string | null;
  /** Confluence score (0–30) of the pre-entry scan, or null if no scan found. */
  scan_score: number | null;
  /** LONG / SHORT inferred from the scan's trade plan, or null. */
  scan_direction: string | null;
  /** Per-TF QQE summary {daily,4h,1h → {trend,strength}} at entry. */
  scan_qqe_signals: Record<string, { trend: string; strength: string }> | null;
}

/** Response for `GET /api/v1/portfolio/{exchange}/trade-attribution`. */
export interface TradeAttributionResponse {
  exchange: string;
  total_trades: number;
  /** Trades entered on a scan with confluence score >= 20. */
  high_confidence_trades: number;
  items: TradeAttributionItem[];
}

/** Win-rate / avg-PnL stats for a single confluence-score band. */
export interface ScanAccuracyBand {
  score_band: string;
  total_trades: number;
  winning_trades: number;
  win_rate: number;
  avg_pnl: number;
}

/** Response for `GET /api/v1/analytics/{exchange}/scan-accuracy`. */
export interface ScanAccuracyResponse {
  exchange: string;
  total_trades: number;
  bands: ScanAccuracyBand[];
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
 * Per-timeframe QQE signal summary extracted by the backend from the raw
 * `qqe` results. `trend` is GREEN / RED / NEUTRAL; `strength` is STRONG
 * (volume-confirmed) / NORMAL / NONE (neutral or errored).
 */
export interface QqeSignal {
  trend: "GREEN" | "RED" | "NEUTRAL";
  strength: "STRONG" | "NORMAL" | "NONE";
}

/**
 * Per-timeframe QQE signals keyed by timeframe (daily / 4h / 1h).
 * `null` before a scan completes or if the backend omitted the field.
 */
export type QqeSignals = Record<"daily" | "4h" | "1h", QqeSignal>;

/**
 * A single swing point used in the market-structure analysis.
 * `type` is "high" (swing high / peak) or "low" (swing low / trough).
 */
export interface StructureSwing {
  type: "high" | "low";
  price: number;
  index: number;
}

/**
 * Single-timeframe market-structure classification result.
 * `label` ∈ {HH, HL, LH, LL, unknown, "Insufficient data"}.
 * `swings` holds the most recent swing points (up to 6).
 */
export interface StructureLabel {
  label: "HH" | "HL" | "LH" | "LL" | "unknown" | "Insufficient data";
  detail: string;
  error?: string;
  swings?: StructureSwing[];
}

/**
 * Per-timeframe market-structure labels keyed by timeframe
 * (weekly / daily / 4h / 1h / 15m).
 */
export type StructureByTF = Record<
  "weekly" | "daily" | "4h" | "1h" | "15m",
  StructureLabel
>;

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
  bmsb: BMSB | null;
  qqe: Record<string, unknown> | null;
  /** Per-TF QQE trend/strength summary (daily/4h/1h). `null` before scan completes. */
  qqe_signals: QqeSignals | null;
  /** Per-TF market-structure classification (HH/HL/LH/LL). `null` before scan completes. */
  structure: StructureByTF | null;
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

// ── Signal Changes / Diff ──────────────────────────────────────────────────

/** Severity level for a single signal change. */
export type Severity = "major" | "minor" | "info";

/** A single field-level change between two scans (from the diff endpoint). */
export interface ScanDiffEntry {
  /** Dotted path, e.g. "qqe_signals.4h", "score.total". */
  field: string;
  /** Human-readable change description, e.g. "GREEN-STRONG → RED". */
  change: string;
  /** "major" | "minor" | "info" — drives the colour coding. */
  severity: Severity;
  /** Previous value (any JSON type, or null). */
  old_value: string | number | boolean | null;
  /** New value (any JSON type, or null). */
  new_value: string | number | boolean | null;
  /** ISO-8601 timestamp of the newer scan (the one that changed). */
  timestamp: string;
}

/** Response for `GET /api/v1/scan/{symbol}/diff` — last 2 scans. */
export interface ScanDiff {
  changes: ScanDiffEntry[];
  old_scan: { timestamp: string; score: number };
  new_scan: { timestamp: string; score: number };
}

/** Full ScanDiffResponse shape (richer, from the backend). Used by the
 * compact panel which keys on the same shape via the /diff endpoint. */
export interface ScanDiffResponse {
  symbol: string;
  previous_scan_at: string;
  latest_scan_at: string;
  previous_score: number | null;
  latest_score: number | null;
  changes: ScanDiffEntry[];
  summary: Record<Severity, number>;
}

/** A single point on the score progression series. */
export interface ScorePoint {
  timestamp: string;
  confluence_score: number | null;
  overall_score: number | null;
  direction: string | null;
  trade_decision: boolean | null;
}

/** One group of changes (per adjacent scan pair) in the timeline. */
export interface TimelineGroup {
  scan_at: string;
  score_before: number | null;
  score_after: number | null;
  changes: ScanDiffEntry[];
}

/** Response for `GET /api/v1/scan/{symbol}/changes` — full timeline. */
export interface ScanChangesTimelineResponse {
  symbol: string;
  total_scans: number;
  score_progression: ScorePoint[];
  timeline: TimelineGroup[];
  summary: Record<Severity, number>;
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

// ── Position alerts (Miraj cross-reference) ───────────────────────────────

/** A single alert on an open position (QQE flip, structure conflict, etc.). */
export interface PositionAlert {
  /** QQE_FLIP | STRUCTURE | CONFLUENCE | LIQ_DISTANCE */
  type: string;
  /** WARNING | DANGER */
  severity: string;
  message: string;
  action?: string | null;
}

/** Aggregated alerts for a single open position. */
export interface PositionAlertItem {
  symbol: string;
  position_side: string;
  position_size: number;
  max_severity: string | null;
  alerts: PositionAlert[];
}

/** Response for `GET /api/v1/portfolio/{exchange}/position-alerts`. */
export interface PositionAlertsResponse {
  exchange: string;
  total_alerts: number;
  danger_count: number;
  warning_count: number;
  positions: PositionAlertItem[];
}

// ── Risk metrics ────────────────────────────────────────────────────────────

/** Response for `GET /api/v1/analytics/{exchange}/risk`. */
export interface RiskMetrics {
  exchange: string;
  total_exposure_usd: number;
  net_exposure_usd: number;
  long_exposure_usd: number;
  short_exposure_usd: number;
  avg_liquidation_distance_pct: number | null;
  margin_usage_pct: number;
  total_margin_used: number;
  total_balance_usd: number | null;
  open_positions: number;
  /** 0–100 (higher = more risk). */
  risk_score: number;
}



// ── Portfolio health score ──────────────────────────────────────────────────

/** Response for `GET /api/v1/analytics/{exchange}/health`. */
export interface HealthScore {
  exchange: string;
  /** 0–100. Higher = more diversified. */
  diversification_score: number;
  /** 0–100. Higher = more directional correlation risk. */
  correlation_risk: number;
  /** 0–100. Higher = more concentration risk. */
  concentration_risk: number;
  /** 0–100 weighted average (higher = healthier). */
  health_score: number;
  /** Letter grade: A / B / C / D / F. */
  grade: string;
  /** Actionable recommendations to improve portfolio health. */
  recommendations: string[];
  open_positions: number;
  unique_assets: number;
}

// ── Benchmark comparison ────────────────────────────────────────────────────

/** A single day's benchmark + portfolio return data point. */
export interface BenchmarkPoint {
  date: string;
  btc_return_pct: number;
  portfolio_return_pct: number;
}

/** Response for `GET /api/v1/analytics/benchmark`. */
export interface BenchmarkResponse {
  symbol: string;
  days: number;
  btc_return_pct: number;
  portfolio_return_pct: number;
  /** portfolio_return_pct − btc_return_pct. */
  alpha: number;
  /** Beta of portfolio vs BTC (cov / var). Null when insufficient data. */
  beta: number | null;
  /** Daily indexed series — both indexed to 0% at start. */
  points: BenchmarkPoint[];
}

// ── Pattern Detection ──────────────────────────────────────────────────────

export interface Pattern {
  name?: string;
  pattern?: string;
  /** Backend returns `signal` ("Bullish"/"Bearish"); `direction` kept for compat. */
  direction?: string;
  signal?: string;
  confirmed?: boolean;
  timeframe?: string;
  levels?: Record<string, number>;
  details?: unknown;
}

// ── Bull Market Support Band ───────────────────────────────────────────────

export interface BMSB {
  sma_20w: number;
  ema_21w: number;
  current_price: number;
  status: "above" | "below";
  regime: "bull" | "bear";
}

// ── Deep Scan (Vision Analysis) ────────────────────────────────────────────

/** A single section in the deep analysis narrative. */
export interface DeepAnalysisSection {
  heading: string;
  body: string;
}

/** Key price levels extracted by deep analysis. */
export interface DeepKeyLevels {
  entry?: number | null;
  stop_loss?: number | null;
  target_1?: number | null;
  target_2?: number | null;
  target_3?: number | null;
  [key: string]: number | null | undefined;
}

/** The deep analysis narrative object. */
export interface DeepAnalysis {
  /** One-line bias verdict, e.g. "Bullish bias (72%) — BTC-USD shows..." */
  summary: string;
  /** Ordered list of analysis sections (heading + body). */
  detailed_analysis: DeepAnalysisSection[];
  /** Identified risk factors / warnings. */
  risk_factors: string[];
  /** Notable price levels (entry, stop, targets, OBs, FVGs). */
  key_levels: DeepKeyLevels;
  /** Per-timeframe breakdown strings. */
  timeframe_breakdown: Record<string, string>;
  /** Count of bullish signals found. */
  bullish_signals: number;
  /** Count of bearish signals found. */
  bearish_signals: number;
  /** Count of neutral signals found. */
  neutral_signals: number;
  /** Aggregate bullish bias percentage (0–100). */
  bias_percent: number;
}

/** Response from `POST /api/v1/scan/{symbol}/deep`. */
export interface DeepScanResult extends ScanResult {
  /** Narrative deep analysis — only present on deep scan responses. */
  deep_analysis: DeepAnalysis;
}

