export interface GoalProgress {
  available: boolean;
  reason: string | null;
  opening_equity: number | null;
  ending_equity: number | null;
  net_external_flows: number | null;
  net_profit: number | null;
  return_pct: number | null;
  as_of?: string | null;
}

export interface GoalProfitBucket {
  period: string;
  from: string;
  to: string;
  opening_equity: number;
  ending_equity: number;
  net_external_flows: number;
  net_profit: number;
  return_pct: number | null;
}

export interface GoalPeriodAnalytics {
  available: boolean;
  reason: string | null;
  basis: "cash_flow_adjusted_futures_equity";
  source: "FuturesAccountSnapshot.equity+CapitalFlowLedger.signed_amount";
  daily: GoalProfitBucket[];
  weekly: GoalProfitBucket[];
  monthly: GoalProfitBucket[];
}

export interface GoalArchiveMonth {
  period_year: number;
  period_month: number;
  status: "closed";
  target_return_pct: number;
  realized_return_pct: number | null;
  net_profit: number | null;
  declared_redeem_usd: number | null;
  declared_reinvest_usd: number | null;
  closed_at: string | null;
}

export interface GoalNowResponse {
  exchange: string;
  timezone: string;
  period_year: number;
  period_month: number;
  goal: {
    target_return_pct: number;
    base_equity: number | null;
    base_source: string | null;
    redeem_pct: number;
    reinvest_pct: number;
    status: string;
  } | null;
  progress: GoalProgress;
  target_usd: number | null;
  remaining_usd: number | null;
  period_analytics: GoalPeriodAnalytics;
  year_archive: GoalArchiveMonth[];
  days_left: number;
  state: string;
  display: string;
}
