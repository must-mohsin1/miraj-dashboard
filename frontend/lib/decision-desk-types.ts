export type DecisionDeskSignalState = "WATCH" | "READY" | "ACTIONABLE" | "INVALIDATED" | "STALE";

export interface DecisionDeskSignal {
  pair: string;
  direction: string;
  state: DecisionDeskSignalState;
  missing_gates: string[];
  updated_at: string;
}

export interface DecisionDeskWatchlistPair {
  pair: string;
  market_scope: "mexc_realtime" | "research_only";
  mexc_symbol: string | null;
}

export interface DecisionDeskNotificationChannel {
  channel_type: string;
  enabled: boolean;
  configured: boolean;
  updated_at: string;
}

/** A durable outbox row; delivered requires sent + sent_at + no error. */
export interface DecisionDeskNotificationOutboxItem {
  pair: string;
  direction: string;
  signal_state: DecisionDeskSignalState;
  channel_type: string;
  status: "pending" | "sent" | "failed" | "cancelled" | string;
  attempts: number;
  created_at: string;
  next_attempt_at: string | null;
  sent_at: string | null;
  error: string | null;
}

export interface DecisionDeskAccountPosition {
  symbol: string;
  side: string;
  size: number;
}

/** Read-only authenticated portfolio-cache evidence, never public market inference. */
export interface DecisionDeskAccountReconciliation {
  exchange: string;
  freshness: "fresh" | "stale" | "unavailable";
  last_reconciled_at: string | null;
  positions: DecisionDeskAccountPosition[];
}

export interface DecisionDeskResponse {
  generated_at: string;
  watchlist: DecisionDeskWatchlistPair[];
  signals: DecisionDeskSignal[];
  notification_channels: DecisionDeskNotificationChannel[];
  notification_outbox: DecisionDeskNotificationOutboxItem[];
  account_reconciliation: DecisionDeskAccountReconciliation[];
}
