import {
  CLOSED_POSITION_FEE_UNAVAILABLE,
  CLOSED_POSITION_HISTORY_PHASE2,
  CLOSED_POSITION_HISTORY_SCOPE,
  CLOSED_POSITION_HISTORY_UNKNOWN,
  CLOSED_POSITION_PNL_BASIS,
  readableReason,
} from "@/components/portfolio/closed-position-formatters";

export type ClosedPositionBasis = {
  pnl_source?: string | null;
  pnl_basis?: string | null;
  currency_unit?: string | null;
  fee_status?: string | null;
  size_unit?: string | null;
};

export type ClosedPositionHistory = {
  history_scope?: string | null;
  history_completeness?: string | null;
  reason?: string | null;
  row_count?: number | null;
  first_close_time?: string | null;
  last_close_time?: string | null;
};

export interface ClosedPositionBasisNoteProps {
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  className?: string;
}

export function ClosedPositionBasisNote({
  basis,
  history,
  className = "",
}: ClosedPositionBasisNoteProps) {
  const pnlBasis = basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS;
  const source = basis?.pnl_source || "PositionHistory.pnl";
  const currency = basis?.currency_unit || "USDT";
  const historyReason = history?.reason || "full_history_sync_not_implemented_phase2";

  return (
    <aside
      className={`border border-border bg-card p-4 text-sm text-muted-foreground ${className}`}
      aria-label="Closed-position analytics basis and history note"
    >
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">
            Basis
          </h3>
          <p className="mt-1 leading-relaxed">
            <span className="text-foreground">{pnlBasis}</span> from{" "}
            <span className="font-mono tabular-nums text-foreground">{source}</span>. Values are
            displayed in <span className="font-mono tabular-nums text-foreground">{currency}</span>.
          </p>
          <p className="mt-2 text-amber-400">{CLOSED_POSITION_FEE_UNAVAILABLE}</p>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">
            Stored history
          </h3>
          <dl className="mt-1 grid gap-1">
            <div className="flex flex-wrap gap-x-2">
              <dt>{CLOSED_POSITION_HISTORY_SCOPE}</dt>
              <dd className="font-mono tabular-nums text-foreground">
                {history?.row_count ?? 0} rows
              </dd>
            </div>
            <div>
              <dt>{CLOSED_POSITION_HISTORY_UNKNOWN}</dt>
              <dd className="sr-only">History completeness is unknown.</dd>
            </div>
            <div>
              <dt>{CLOSED_POSITION_HISTORY_PHASE2}</dt>
              <dd className="text-xs">Reason: {readableReason(historyReason)}</dd>
            </div>
          </dl>
        </div>
      </div>
    </aside>
  );
}

export default ClosedPositionBasisNote;
