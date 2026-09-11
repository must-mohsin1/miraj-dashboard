# Realtime Interactive Chart Implementation Plan

> **For Hermes:** Execute directly in the existing Miraj Dashboard; the user explicitly authorized implementation.

**Goal:** Upgrade the existing lightweight-charts analysis chart into a durable, realtime, interactive signal chart without requiring TradingView or a paid subscription.

**Architecture:** Reuse the existing authenticated Next.js `LiveCandlestickChart`, `lightweight-charts` v5 renderer, `/api/v1/charts/{symbol}/candles` REST hydration, and SSE fallback. The first shipped phase adds a direct public Binance kline WebSocket for USDT crypto symbols, in-place candle updates, reconnect handling, visible stream state, a text-label tool, and browser-local per-symbol/timeframe drawing persistence. It remains read-only: no order execution.

**Follow-up boundary:** Server-backed per-user drawing persistence and a backend-normalized multi-exchange candle SSE are intentionally not included in this phase; the existing MEXC parser/subscription remains available for that next phase.

**Research basis:** Binance official kline streams update the current candle in real time and expose the `k.x` closed-candle flag; the project already has a MEXC contract kline parser/subscription helper; Lightweight Charts supports candlestick, line, histogram and price-line series with in-place `series.update`; the repo already contains the chart, indicator, SSE, and drawing primitives.

---

## Assessment

Existing code already provides most of the UI foundation:

- `frontend/components/live-candlestick-chart.tsx` loads timeframe candles, indicators and a live-price SSE stream.
- `frontend/components/candlestick-chart.tsx` renders candlesticks, EMA, Bollinger, volume, RSI, MACD, FVG/OB and trade levels with `lightweight-charts`.
- `frontend/components/chart-drawing-toolbar.tsx` supports cursor, horizontal, trend and Fibonacci tools.
- `backend/routes/stream.py` currently polls Binance public tickers every 5 seconds; it is not a candle WebSocket.
- `backend/routes/charts.py` fetches OHLCV on demand and returns an authenticated empty drawing contract because persistence is not implemented.
- Drawing state is currently session/component-local and has no text-label tool.

Verified gaps:

1. The live chart receives price ticks, not exchange-native candle updates with closed-candle state.
2. The latest candle's high/low/close are updated in the browser, but volume and candle-boundary rollover are not stream-driven.
3. Drawings are lost on reload and are not scoped to user/symbol/timeframe.
4. There is no text/label drawing type.
5. Existing signal/trade-level data is available, but there is no durable, explicit label layer for trigger, invalidation and targets.

## Acceptance criteria

- A SOLUSDT chart updates from a public exchange WebSocket without page refresh.
- Current candle updates in place; a closed candle creates exactly one new candle.
- Reconnect hydrates REST candles before applying new live frames.
- Stale/disconnected state is visible and does not silently look live.
- EMA/BB/RSI/MACD and signal levels refresh after candle updates or closed-candle rollover.
- Horizontal, trend, Fibonacci and text-label drawings persist by authenticated user + symbol + timeframe.
- Existing drawings load on chart mount and survive reload.
- No order placement or exchange private-key access is added.
- Focused backend/frontend tests pass, then production build and end-to-end chart verification pass.

## Implementation tasks

### 1. Add durable drawing persistence

Files:
- Modify `backend/models.py` to add `ChartDrawing` with user_id, symbol, timeframe, drawing_id, drawing_type, points JSON, style JSON, metadata JSON, timestamps and a unique user/symbol/timeframe/drawing_id constraint.
- Modify `backend/routes/charts.py` to implement authenticated GET/PUT/DELETE drawing endpoints.
- Add `backend/migrations/versions/<timestamp>_chart_drawings.py`.
- Add backend tests for scope isolation, upsert, delete and empty state.

Contract:
- `GET /api/v1/drawings?symbol=SOLUSDT&timeframe=4h`
- `PUT /api/v1/drawings` upserts one drawing.
- `DELETE /api/v1/drawings/{drawing_id}` deletes only the current user's drawing.

### 2. Add text labels to the chart drawing model

Files:
- Modify `frontend/components/chart-drawing-toolbar.tsx` to add `text`.
- Modify `frontend/components/candlestick-chart.tsx` to render text labels as `lightweight-charts` custom HTML overlays or positioned DOM labels anchored to time/price coordinates.
- Add label editor UX with text, color, size and optional role (`signal`, `stop`, `target`, `support`, `note`).
- Persist creation/edit/delete through the drawing API.
- Add frontend tests for drawing serialization and label rendering state.

### 3. Replace ticker polling for chart candles with a realtime candle stream

Files:
- Add a backend public stream module under `backend/realtime/chart_stream.py`.
- Add an authenticated SSE endpoint, e.g. `/api/v1/stream/candles?symbol=SOLUSDT&timeframe=4h`.
- Use exchange-native public WebSocket klines where supported; normalize Binance/MEXC payloads to `{symbol,timeframe,startTime,open,high,low,close,volume,closed}`.
- REST hydrate on startup/reconnect, dedupe by candle start time, and fail closed with stale status after heartbeat timeout.
- Add focused parser/reconnect/closed-candle tests with fixtures.

### 4. Connect the frontend to candle events

Files:
- Modify `frontend/components/live-candlestick-chart.tsx` to subscribe to candle SSE, keep price SSE only for sub-candle badge updates, and expose `connected`, `lastUpdate`, `stale` and `closed` state.
- Modify `frontend/components/candlestick-chart.tsx` to update the current candle including volume and rollover to a new candle.
- Recompute client-side display indicators after a candle update or use a backend indicator payload when the timeframe changes.
- Add visible connection badge and stale-data warning.

### 5. Auto-render signal overlays

Files:
- Modify `frontend/components/candlestick-chart.tsx` or a new `signal-overlays.ts` helper.
- Normalize the existing analysis trade-plan fields into labeled lines: entry/trigger, stop/invalidation, targets, demand/supply, support/resistance.
- Render lines and labels distinctly from user drawings; do not persist generated signal overlays as user drawings.
- Add tests for missing/partial trade plans and level ordering.

### 6. Verify locally and in production

Commands:
- Backend focused tests for drawings and stream parsers.
- Frontend Jest/TypeScript tests for chart state and drawing serialization.
- `npm run build` in `frontend`.
- Run the local stack and verify a SOLUSDT chart updates without refresh, reconnects, preserves drawings, and shows labels.
- Deploy only after local acceptance passes; verify public browser behavior and health endpoints separately.

## Official/source references reviewed

- Binance WebSocket kline/candlestick streams: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams#kline-candlestick-streams
- Lightweight Charts series documentation: https://tradingview.github.io/lightweight-charts/docs/series-types
- Existing MEXC public contract parser/subscription: `backend/realtime/mexc_stream.py`
- Existing chart route: `backend/routes/charts.py`
- Existing live chart: `frontend/components/live-candlestick-chart.tsx`, `frontend/components/candlestick-chart.tsx`
