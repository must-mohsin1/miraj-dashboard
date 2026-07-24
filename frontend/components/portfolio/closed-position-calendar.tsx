import { type ClosedPositionBasis, type ClosedPositionHistory } from "@/components/portfolio/closed-position-basis-note";
import {
  CLOSED_POSITION_ANALYTICS_ERROR,
  CLOSED_POSITION_PNL_BASIS,
  formatCount,
  formatUsdtMoney,
  pnlToneClass,
} from "@/components/portfolio/closed-position-formatters";
import { describeFilterContext } from "@/components/portfolio/closed-position-period-chart";

export type ClosedPositionCalendarDay = {
  date: string;
  trade_count: number;
  total_pnl: number | null;
  basis?: string | null;
  currency_unit?: string | null;
};

export interface ClosedPositionCalendarProps {
  days: ClosedPositionCalendarDay[];
  totals: { trade_count: number; total_pnl: number | null };
  filtersApplied?: Record<string, unknown> | null;
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  loading?: boolean;
  error?: string | null;
}

export function ClosedPositionCalendar({
  days,
  totals,
  filtersApplied,
  basis,
  loading = false,
  error = null,
}: ClosedPositionCalendarProps) {
  const pnlBasis = basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS;
  const filterContext = describeFilterContext(filtersApplied);
  const summary = `Closed-position PnL calendar total ${formatUsdtMoney(totals.total_pnl, {
    signed: true,
    dollarStyle: true,
  })} across ${formatCount(totals.trade_count)} positions for ${filterContext}. Basis: ${pnlBasis}.`;

  if (loading) {
    return <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-busy="true">Loading closed-position PnL calendar…</section>;
  }

  if (error) {
    return <section className="border border-destructive bg-destructive/10 p-4 text-sm text-destructive" role="alert">{CLOSED_POSITION_ANALYTICS_ERROR}</section>;
  }

  if (days.length === 0) {
    return (
      <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-labelledby="closed-position-calendar-heading">
        <h2 id="closed-position-calendar-heading" className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">Closed-position PnL calendar</h2>
        <p className="mt-2">No calendar days match these filters. {summary}</p>
      </section>
    );
  }

  const maxAbs = Math.max(...days.map((day) => Math.abs(day.total_pnl ?? 0)), 1);

  return (
    <section className="grid gap-4" aria-labelledby="closed-position-calendar-heading">
      <div>
        <h2 id="closed-position-calendar-heading" className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">Closed-position PnL calendar</h2>
        <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
      </div>
      <p className="sr-only">{summary}</p>
      <div className="border border-border bg-card p-4" role="img" aria-label={summary}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {days.map((day) => {
            const value = day.total_pnl ?? 0;
            const intensity = Math.max(0.12, Math.min(0.42, Math.abs(value) / maxAbs * 0.42));
            const state = value > 0 ? "Profit" : value < 0 ? "Loss" : "Flat";
            return (
              <article
                key={day.date}
                className="border border-border bg-background p-3"
                aria-label={`${day.date}: ${state}; ${formatUsdtMoney(value, { signed: true, dollarStyle: true })}; ${formatCount(day.trade_count)} positions; ${pnlBasis}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-mono text-xs tabular-nums text-muted-foreground">{day.date}</h3>
                  <span className="text-xs text-muted-foreground">{state}</span>
                </div>
                <div
                  className={`mt-3 h-1 border border-border ${value > 0 ? "bg-profit/20" : value < 0 ? "bg-loss/20" : "bg-muted/40"}`}
                  style={{ opacity: value === 0 ? 1 : intensity + 0.45 }}
                  aria-hidden="true"
                />
                <p className={`mt-2 font-mono text-sm tabular-nums ${pnlToneClass(value)}`}>{formatUsdtMoney(value, { signed: true, dollarStyle: true })}</p>
                <p className="mt-1 text-xs text-muted-foreground">{formatCount(day.trade_count)} closed positions</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export default ClosedPositionCalendar;
