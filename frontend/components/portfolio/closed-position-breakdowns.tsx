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

export type ClosedPositionBreakdownGroup = "symbol" | "side" | "duration" | "leverage" | "pair_direction";

export type ClosedPositionBreakdownRow = {
  key: string;
  trade_count: number;
  total_pnl: number | null;
  gross_profit: number | null;
  gross_loss_abs: number | null;
  win_rate_pct: number | null;
  average_pnl: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  basis?: string | null;
  currency_unit?: string | null;
};

export type ClosedPositionConcentration = {
  gross_profit_top_1_contribution_pct?: number | null;
  gross_profit_top_1_contribution_pct_reason?: string | null;
  gross_profit_hhi?: number | null;
  gross_profit_hhi_reason?: string | null;
  gross_loss_top_1_contribution_pct?: number | null;
  gross_loss_top_1_contribution_pct_reason?: string | null;
  gross_loss_hhi?: number | null;
  gross_loss_hhi_reason?: string | null;
};

export type ClosedPositionBreakdownsData = Partial<Record<ClosedPositionBreakdownGroup, ClosedPositionBreakdownRow[]>>;

export interface ClosedPositionBreakdownsProps {
  breakdowns: ClosedPositionBreakdownsData;
  concentration?: ClosedPositionConcentration | null;
  excludedReasons?: Record<string, number> | null;
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  loading?: boolean;
  error?: string | null;
}

const GROUP_LABELS: Record<ClosedPositionBreakdownGroup, string> = {
  symbol: "Symbol",
  side: "Side",
  duration: "Duration bucket",
  leverage: "Leverage bucket",
  pair_direction: "Pair / direction",
};

const GROUP_ORDER: ClosedPositionBreakdownGroup[] = ["symbol", "side", "duration", "leverage", "pair_direction"];

export function ClosedPositionBreakdowns({
  breakdowns,
  concentration,
  excludedReasons,
  basis,
  loading = false,
  error = null,
}: ClosedPositionBreakdownsProps) {
  const pnlBasis = basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS;

  if (loading) {
    return <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-busy="true">Loading closed-position breakdowns…</section>;
  }

  if (error) {
    return <section className="border border-destructive bg-destructive/10 p-4 text-sm text-destructive" role="alert">{CLOSED_POSITION_ANALYTICS_ERROR}</section>;
  }

  const hasRows = GROUP_ORDER.some((group) => (breakdowns[group] || []).length > 0);

  return (
    <section className="grid gap-4" aria-labelledby="closed-position-breakdowns-heading">
      <div>
        <h2 id="closed-position-breakdowns-heading" className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">Closed-position breakdowns</h2>
        <p className="mt-1 text-sm text-muted-foreground">Rows use server-provided {pnlBasis}; total PnL, gross profit, gross loss, win rate, averages, best/worst, and gross contribution concentration are shown without client-side aggregate recomputation.</p>
      </div>

      <ConcentrationPanel concentration={concentration} />
      <ExcludedReasons excludedReasons={excludedReasons} />

      {!hasRows ? (
        <div className="border border-border bg-card p-6 text-sm text-muted-foreground">No breakdown rows match these filters. Unknown duration/leverage buckets will appear here when supplied by the server.</div>
      ) : null}

      <div className="grid gap-4">
        {GROUP_ORDER.map((group) => (
          <BreakdownTable key={group} group={group} rows={breakdowns[group] || []} pnlBasis={pnlBasis} />
        ))}
      </div>
    </section>
  );
}

function ConcentrationPanel({ concentration }: { concentration?: ClosedPositionConcentration | null }) {
  if (!concentration) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <ConcentrationMetric label="Gross profit top group contribution" value={concentration.gross_profit_top_1_contribution_pct} suffix="%" reason={concentration.gross_profit_top_1_contribution_pct_reason} />
      <ConcentrationMetric label="Gross profit HHI" value={concentration.gross_profit_hhi} reason={concentration.gross_profit_hhi_reason} />
      <ConcentrationMetric label="Gross loss top group contribution" value={concentration.gross_loss_top_1_contribution_pct} suffix="%" reason={concentration.gross_loss_top_1_contribution_pct_reason} />
      <ConcentrationMetric label="Gross loss HHI" value={concentration.gross_loss_hhi} reason={concentration.gross_loss_hhi_reason} />
    </div>
  );
}

function ConcentrationMetric({ label, value, suffix = "", reason }: { label: string; value?: number | null; suffix?: string; reason?: string | null }) {
  const rendered = value == null ? "—" : suffix === "%" ? formatPercent(value) : formatRatio(value);
  return (
    <article className="border border-border bg-card p-4">
      <h3 className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</h3>
      <p className="mt-2 font-mono text-xl font-semibold tabular-nums text-foreground">{rendered}</p>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Gross contribution concentration uses nonnegative gross profit/loss, not signed net PnL{value == null ? ` — ${readableReason(reason)}` : "."}</p>
    </article>
  );
}

function ExcludedReasons({ excludedReasons }: { excludedReasons?: Record<string, number> | null }) {
  const entries = Object.entries(excludedReasons || {}).filter(([, count]) => count > 0);
  if (entries.length === 0) return null;

  return (
    <aside className="border border-border bg-card p-4 text-sm text-muted-foreground" aria-label="Closed-position excluded rows">
      <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">Excluded rows</h3>
      <ul className="mt-2 grid gap-1">
        {entries.map(([reason, count]) => (
          <li key={reason}><span className="font-mono tabular-nums text-foreground">{formatCount(count)}</span> rows excluded for {readableReason(reason)}</li>
        ))}
      </ul>
    </aside>
  );
}

function BreakdownTable({ group, rows, pnlBasis }: { group: ClosedPositionBreakdownGroup; rows: ClosedPositionBreakdownRow[]; pnlBasis: string }) {
  return (
    <article className="border border-border bg-card p-4" aria-labelledby={`closed-position-${group}-heading`}>
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h3 id={`closed-position-${group}-heading`} className="text-sm font-semibold text-foreground">{GROUP_LABELS[group]}</h3>
        <p className="text-xs text-muted-foreground">{pnlBasis}</p>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No {GROUP_LABELS[group].toLowerCase()} rows returned by the server.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <caption className="sr-only">Closed-position breakdown by {GROUP_LABELS[group]} with PnL, gross contribution, win rate, averages, and best/worst positions.</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-[0.12em] text-muted-foreground">
                <th scope="col" className="py-2 pr-3 text-left font-medium">Bucket</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Positions</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Total PnL</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Gross profit</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Gross loss</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Win rate</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Average</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Best</th>
                <th scope="col" className="py-2 pl-3 text-right font-medium">Worst</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b border-border last:border-b-0">
                  <th scope="row" className="py-3 pr-3 text-left font-mono text-xs tabular-nums text-foreground">{readableBucket(row.key)}</th>
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-foreground">{formatCount(row.trade_count)}</td>
                  <MoneyCell value={row.total_pnl} />
                  <MoneyCell value={row.gross_profit} />
                  <MoneyCell value={row.gross_loss_abs == null ? null : -Math.abs(row.gross_loss_abs)} />
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-foreground">{formatPercent(row.win_rate_pct)}</td>
                  <MoneyCell value={row.average_pnl} />
                  <MoneyCell value={row.best_trade} />
                  <MoneyCell value={row.worst_trade} edge="right" />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

function MoneyCell({ value, edge = "middle" }: { value: number | null; edge?: "middle" | "right" }) {
  const padding = edge === "right" ? "py-3 pl-3" : "px-3 py-3";
  return <td className={`${padding} text-right font-mono tabular-nums ${pnlToneClass(value)}`}>{formatUsdtMoney(value, { signed: true, dollarStyle: true })}</td>;
}

function readableBucket(key: string): string {
  if (key === "unknown_duration") return "Unknown duration";
  if (key === "unknown_leverage") return "Unknown leverage";
  return key.replaceAll("_", " / ");
}

export default ClosedPositionBreakdowns;
