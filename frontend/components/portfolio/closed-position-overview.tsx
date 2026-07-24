import type { ReactNode } from "react";

import { type ClosedPositionBasis, type ClosedPositionHistory } from "@/components/portfolio/closed-position-basis-note";
import {
  CLOSED_POSITION_ANALYTICS_ERROR,
  CLOSED_POSITION_PNL_BASIS,
  formatCount,
  formatPercent,
  formatRatio,
  formatUsdtMoney,
  pnlToneClass,
  readableReason,
} from "@/components/portfolio/closed-position-formatters";

export type ClosedPositionUnavailable = {
  fee_net_pnl?: { value: null; reason: string } | null;
  account_return_pct?: { value: null; reason: string } | null;
  account_equity?: { value: null; reason: string } | null;
};

export type ClosedPositionOverviewData = {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  total_pnl: number | null;
  win_rate_pct?: number | null;
  win_rate_pct_reason?: string | null;
  average_win?: number | null;
  average_win_reason?: string | null;
  average_loss?: number | null;
  average_loss_reason?: string | null;
  average_trade_pnl?: number | null;
  average_trade_pnl_reason?: string | null;
  expectancy_per_trade?: number | null;
  expectancy_per_trade_reason?: string | null;
  profit_factor?: number | null;
  profit_factor_reason?: string | null;
  payoff_ratio?: number | null;
  payoff_ratio_reason?: string | null;
  active_days?: number | null;
  calendar_days?: number | null;
  average_pnl_per_active_day?: number | null;
  average_pnl_per_active_day_label?: string | null;
  average_pnl_per_active_day_reason?: string | null;
  average_pnl_per_calendar_day?: number | null;
  average_pnl_per_calendar_day_label?: string | null;
  average_pnl_per_calendar_day_reason?: string | null;
};

export interface ClosedPositionOverviewProps {
  overview: ClosedPositionOverviewData | null;
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  unavailable?: ClosedPositionUnavailable | null;
  loading?: boolean;
  error?: string | null;
}

export function ClosedPositionOverview({
  overview,
  basis,
  history,
  unavailable,
  loading = false,
  error = null,
}: ClosedPositionOverviewProps) {
  if (loading) {
    return (
      <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-busy="true">
        Loading closed-position analytics…
      </section>
    );
  }

  if (error) {
    return (
      <section className="border border-destructive bg-destructive/10 p-4 text-sm text-destructive" role="alert">
        {CLOSED_POSITION_ANALYTICS_ERROR}
      </section>
    );
  }

  if (!overview || overview.total_trades === 0) {
    return (
      <section className="grid gap-4">
        <div className="border border-border bg-card p-6 text-sm text-muted-foreground">
          No stored closed positions match these filters. MEXC-reported closed-position PnL will appear once matching closed positions are stored.
        </div>
      </section>
    );
  }

  const activeDayLabel = overview.average_pnl_per_active_day_label || "per active trading day";
  const calendarDayLabel = overview.average_pnl_per_calendar_day_label || "per calendar day";

  return (
    <section className="grid gap-4" aria-labelledby="closed-position-overview-heading">
      <div>
        <h2 id="closed-position-overview-heading" className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          Closed-position overview
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS}</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Total closed positions"
          value={formatCount(overview.total_trades)}
          hint={`${formatCount(overview.winning_trades)} wins / ${formatCount(overview.losing_trades)} losses / ${formatCount(overview.breakeven_trades)} breakeven`}
        />
        <KpiCard
          label="Total MEXC-reported PnL"
          value={formatUsdtMoney(overview.total_pnl, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.total_pnl)}
          hint="MEXC-reported closed-position PnL"
        />
        <KpiCard
          label="Win rate"
          value={formatPercent(overview.win_rate_pct)}
          hint={overview.win_rate_pct == null ? readableReason(overview.win_rate_pct_reason) : "Winning positions / all filtered positions"}
        />
        <KpiCard
          label="Average trade PnL"
          value={formatUsdtMoney(overview.average_trade_pnl, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.average_trade_pnl)}
          hint={overview.average_trade_pnl == null ? readableReason(overview.average_trade_pnl_reason) : "All filtered closed positions"}
        />
        <KpiCard
          label="Average win"
          value={formatUsdtMoney(overview.average_win, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.average_win)}
          hint={overview.average_win == null ? readableReason(overview.average_win_reason) : "Winning positions only"}
        />
        <KpiCard
          label="Average loss"
          value={formatUsdtMoney(overview.average_loss, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.average_loss)}
          hint={overview.average_loss == null ? readableReason(overview.average_loss_reason) : "Losing positions only"}
        />
        <KpiCard
          label={`Average PnL ${activeDayLabel}`}
          value={formatUsdtMoney(overview.average_pnl_per_active_day, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.average_pnl_per_active_day)}
          hint={overview.average_pnl_per_active_day == null ? readableReason(overview.average_pnl_per_active_day_reason) : `${formatCount(overview.active_days)} active days`}
        />
        <KpiCard
          label={`Average PnL ${calendarDayLabel}`}
          value={formatUsdtMoney(overview.average_pnl_per_calendar_day, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.average_pnl_per_calendar_day)}
          hint={overview.average_pnl_per_calendar_day == null ? readableReason(overview.average_pnl_per_calendar_day_reason) : `${formatCount(overview.calendar_days)} calendar days`}
        />
        <KpiCard
          label="Expectancy per trade"
          value={formatUsdtMoney(overview.expectancy_per_trade, { signed: true, dollarStyle: true })}
          valueClassName={pnlToneClass(overview.expectancy_per_trade)}
          hint={overview.expectancy_per_trade == null ? readableReason(overview.expectancy_per_trade_reason) : "Total PnL / all filtered positions"}
        />
        <KpiCard
          label="Profit factor"
          value={formatRatio(overview.profit_factor)}
          hint={overview.profit_factor == null ? readableReason(overview.profit_factor_reason) : "Gross profit / gross loss"}
        />
        <KpiCard
          label="Payoff ratio"
          value={formatRatio(overview.payoff_ratio)}
          hint={overview.payoff_ratio == null ? readableReason(overview.payoff_ratio_reason) : "Average win / absolute average loss"}
        />
        <KpiCard
          label="Fee-net PnL"
          value="Unavailable"
          hint={readableReason(unavailable?.fee_net_pnl?.reason || basis?.fee_status)}
        />
      </div>

    </section>
  );
}

function KpiCard({
  label,
  value,
  hint,
  valueClassName = "text-foreground",
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  valueClassName?: string;
}) {
  return (
    <article className="border border-border bg-card p-4">
      <h3 className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</h3>
      <p className={`mt-2 font-mono text-xl font-semibold tabular-nums ${valueClassName}`}>{value}</p>
      {hint ? <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{hint}</p> : null}
    </article>
  );
}

export default ClosedPositionOverview;
