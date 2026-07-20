export type DecisionDeskSignalState =
  | "WATCH"
  | "READY"
  | "ACTIONABLE"
  | "INVALIDATED"
  | "STALE";

/** A persisted, advisory-only realtime lifecycle record. */
export interface DecisionDeskSignal {
  pair: string;
  direction: string;
  state: DecisionDeskSignalState;
  missing_gates: string[];
  updated_at: string;
}

/** A watchlist row included in the Decision Desk snapshot. */
export interface DecisionDeskWatchlistPair {
  pair: string;
  market_scope: "mexc_realtime" | "research_only";
  mexc_symbol: string | null;
}

/** Response from `GET /api/v1/decision-desk/now`. */
export interface DecisionDeskResponse {
  generated_at: string;
  watchlist: DecisionDeskWatchlistPair[];
  signals: DecisionDeskSignal[];
}
