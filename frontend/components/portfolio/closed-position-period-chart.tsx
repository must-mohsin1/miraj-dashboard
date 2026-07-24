import { ClosedPositionBasisNote, type ClosedPositionBasis, type ClosedPositionHistory } from "@/components/portfolio/closed-position-basis-note";
import {
  CLOSED_POSITION_ANALYTICS_ERROR,
  CLOSED_POSITION_PNL_BASIS,
  formatCount,
  formatUsdtMoney,
  pnlToneClass,
} from "@/components/portfolio/closed-position-formatters";

export type ClosedPositionPeriodItem = {
  label: string;
  period_start?: string | null;
  period_end?: string | null;
  trade_count: number;
  total_pnl: number | null;
  basis?: string | null;
  currency_unit?: string | null;
};

export type ClosedPositionPeriodTotals = {
  trade_count: number;
  total_pnl: number | null;
};

export interface ClosedPositionPeriodChartProps {
  items: ClosedPositionPeriodItem[];
  totals: ClosedPositionPeriodTotals;
  period: "day" | "week" | "month" | string;
  filtersApplied?: Record<string, unknown> | null;
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  loading?: boolean;
  error?: string | null;
}

export function ClosedPositionPeriodChart({
  items,
  totals,
  period,
  filtersApplied,
  basis,
  history,
  loading = false,
  error = null,
}: ClosedPositionPeriodChartProps) {
  const pnlBasis = basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS;
  const filterContext = describeFilterContext(filtersApplied);
  const summary = `Closed-position ${period} chart totals ${formatUsdtMoney(totals.total_pnl, {
    signed: true,
    dollarStyle: true,
  })} across ${formatCount(totals.trade_count)} positions for ${filterContext}. Basis: ${pnlBasis}.`;

  if (loading) {
    return <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-busy="true">Loading closed-position period chart…</section>;
  }

  if (error) {
    return <section className="border border-destructive bg-destructive/10 p-4 text-sm text-destructive" role="alert">{CLOSED_POSITION_ANALYTICS_ERROR}</section>;
  }

  if (items.length === 0) {
    return (
      <section className="grid gap-4" aria-labelledby="closed-position-period-chart-heading">
        <ChartHeader id="closed-position-period-chart-heading" period={period} summary={summary} />
        <div className="border border-border bg-card p-6 text-sm text-muted-foreground">No period buckets match these filters. {summary}</div>
        <ClosedPositionBasisNote basis={basis} history={history} />
      </section>
    );
  }

  const maxAbs = Math.max(...items.map((item) => Math.abs(item.total_pnl ?? 0)), 1);

  return (
    <section className="grid gap-4" aria-labelledby="closed-position-period-chart-heading">
      <ChartHeader id="closed-position-period-chart-heading" period={period} summary={summary} />
      <p className="sr-only">{summary}</p>
      <div className="border border-border bg-card p-4" role="img" aria-label={summary}>
        <div className="grid gap-3">
          {items.map((item) => {
            const value = item.total_pnl ?? 0;
            const width = `${Math.max(4, (Math.abs(value) / maxAbs) * 100)}%`;
            const profitable = value > 0;
            const losing = value < 0;
            const direction = profitable ? "Profit" : losing ? "Loss" : "Flat";
            return (
              <div key={`${item.label}-${item.period_start || ""}`} className="grid gap-1 sm:grid-cols-[8rem_1fr_9rem] sm:items-center">
                <div>
                  <div className="font-mono text-sm tabular-nums text-foreground">{item.label}</div>
                  <div className="text-xs text-muted-foreground">{formatCount(item.trade_count)} positions</div>
                </div>
                <div className="h-7 border border-border bg-background" aria-hidden="true">
                  <div
                    className={`h-full border-r border-border ${profitable ? "bg-profit/20" : losing ? "bg-loss/20" : "bg-muted/40"}`}
                    style={{ width }}
                  />
                </div>
                <div className="text-left sm:text-right">
                  <span className={`font-mono text-sm tabular-nums ${pnlToneClass(value)}`}>{formatUsdtMoney(value, { signed: true, dollarStyle: true })}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{direction}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <ClosedPositionBasisNote basis={basis} history={history} />
    </section>
  );
}

function ChartHeader({ id, period, summary }: { id: string; period: string; summary: string }) {
  return (
    <div>
      <h2 id={id} className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">Closed-position {period} chart</h2>
      <p className="mt-1 text-sm text-muted-foreground">{summary}</p>
    </div>
  );
}

export function describeFilterContext(filtersApplied?: Record<string, unknown> | null): string {
  if (!filtersApplied) return "all stored closed positions";
  const parts: string[] = [];
  const symbols = Array.isArray(filtersApplied.symbols) ? filtersApplied.symbols.join(", ") : filtersApplied.symbols;
  if (symbols) parts.push(`symbols ${symbols}`);
  if (filtersApplied.side) parts.push(`side ${filtersApplied.side}`);
  if (filtersApplied.from) parts.push(`from ${filtersApplied.from}`);
  if (filtersApplied.to) parts.push(`to ${filtersApplied.to} exclusive`);
  if (filtersApplied.timezone) parts.push(`timezone ${filtersApplied.timezone}`);
  return parts.length ? parts.join(", ") : "all stored closed positions";
}

export default ClosedPositionPeriodChart;
