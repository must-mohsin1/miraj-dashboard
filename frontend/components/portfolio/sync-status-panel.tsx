import type { FuturesAccountItem, SyncCoverageItem } from "@/lib/types";
import { formatUtcDateTime } from "@/lib/date-format";

const STREAM_LABELS: Record<string, string> = {
  positions_history: "Position history",
  orders_history: "Order history",
  futures_account_assets: "Futures account assets",
  funding: "Funding history",
  futures_transfers: "Futures transfers",
  deposits: "Deposits",
  withdrawals: "Withdrawals",
};

const STATUS_LABELS: Record<string, string> = {
  fresh: "Fresh",
  stale: "Stale",
  partial: "Partial history",
  error: "Sync error",
  unavailable: "Unavailable",
  not_enabled_phase_2b: "Phase 2B",
};

const STATUS_STYLES: Record<string, string> = {
  fresh: "border-[#6CA98F]/60 bg-[#6CA98F]/10 text-[#6CA98F]",
  stale: "border-[#7E7B8A]/60 bg-[#7E7B8A]/10 text-[#A69D8C]",
  partial: "border-[#D19A4A]/60 bg-[#D19A4A]/10 text-[#D19A4A]",
  error: "border-[#C96A55]/60 bg-[#C96A55]/10 text-[#C96A55]",
  unavailable: "border-[#A69D8C]/60 bg-[#A69D8C]/10 text-[#A69D8C]",
  not_enabled_phase_2b: "border-[#C2A36B]/60 bg-[#C2A36B]/10 text-[#C2A36B]",
};

const FUTURES_FIELDS: Array<[keyof FuturesAccountItem, string]> = [
  ["equity", "Equity"],
  ["available_balance", "Available balance"],
  ["position_margin", "Position margin"],
  ["frozen_balance", "Frozen balance"],
  ["cash_balance", "Cash balance"],
  ["unrealized_pnl", "Unrealized PnL"],
  ["bonus", "Bonus"],
  ["available_cash", "Available cash"],
  ["debt_amount", "Debt amount"],
];

export interface SyncStatusPanelProps {
  sync: SyncCoverageItem[];
  futuresAccount: FuturesAccountItem | null;
  partial?: boolean;
}

export function streamLabel(stream: string): string {
  return STREAM_LABELS[stream] ?? humanize(stream);
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? humanize(status);
}

export function SyncStatusPanel({ sync, futuresAccount, partial = false }: SyncStatusPanelProps) {
  const futuresCoverage = sync.find((item) => item.stream === "futures_account_assets");
  const hasCapitalFlowGap = sync.some((item) =>
    ["funding", "futures_transfers", "deposits", "withdrawals"].includes(item.stream) &&
    ["not_enabled_phase_2b", "unavailable", "partial", "error"].includes(item.status),
  );

  return (
    <section className="border border-[#2A2620] bg-[#161411]" aria-labelledby="mexc-sync-coverage-title">
      <div className="border-b border-[#2A2620] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#C2A36B]">
          Portfolio coverage
        </p>
        <h2 id="mexc-sync-coverage-title" className="mt-1 text-lg font-semibold text-[#EDE7DB]">
          MEXC sync coverage
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-[#8E8778]">
          Shows what Miraj has synchronized from read-only MEXC account data and what is still outside Phase 2A.
        </p>
      </div>

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="border-b border-[#2A2620] lg:border-b-0 lg:border-r">
          {sync.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">MEXC stream synchronization coverage states</caption>
                <thead className="border-b border-[#2A2620] text-[11px] uppercase tracking-[0.18em] text-[#8E8778]">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">Stream</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                    <th scope="col" className="px-4 py-3 font-medium">Coverage window</th>
                    <th scope="col" className="px-4 py-3 font-medium">Rows</th>
                    <th scope="col" className="px-4 py-3 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#2A2620]">
                  {sync.map((item) => (
                    <tr key={item.stream}>
                      <th scope="row" className="px-4 py-3 align-top font-medium text-[#EDE7DB]">
                        {streamLabel(item.stream)}
                      </th>
                      <td className="px-4 py-3 align-top">
                        <span className={`inline-flex border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLES[item.status] ?? STATUS_STYLES.unavailable}`}>
                          {statusLabel(item.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3 align-top font-mono text-xs text-[#EDE7DB]">
                        {coverageWindow(item)}
                      </td>
                      <td className="px-4 py-3 align-top font-mono text-xs text-[#EDE7DB]">
                        {rowCount(item)}
                      </td>
                      <td className="max-w-xs px-4 py-3 align-top text-xs text-[#8E8778]">
                        {coverageDetail(item)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-4">
              <h3 className="text-sm font-semibold text-[#EDE7DB]">No sync coverage yet</h3>
              <p className="mt-1 text-sm text-[#8E8778]">Run a mocked refresh to record coverage for MEXC streams.</p>
            </div>
          )}
        </div>

        <div className="flex flex-col divide-y divide-[#2A2620]">
          <FuturesAccountSnapshot futuresAccount={futuresAccount} coverage={futuresCoverage} />
          <Phase2AUnavailableStates partial={partial} hasCapitalFlowGap={hasCapitalFlowGap} />
        </div>
      </div>
    </section>
  );
}

function FuturesAccountSnapshot({
  futuresAccount,
  coverage,
}: {
  futuresAccount: FuturesAccountItem | null;
  coverage?: SyncCoverageItem;
}) {
  if (!futuresAccount) {
    return (
      <div className="p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8E8778]">Futures account snapshot</p>
        <h3 className="mt-2 text-base font-semibold text-[#EDE7DB]">Futures snapshot unavailable</h3>
        <p className="mt-2 text-sm text-[#8E8778]">No authenticated futures account snapshot is available.</p>
        <p className="mt-1 text-sm text-[#8E8778]">Spot balances are not futures collateral. Miraj will not use spot balances as futures equity.</p>
        {coverage?.reason && <p className="mt-2 text-xs text-[#8E8778]">{humanize(coverage.reason)}.</p>}
      </div>
    );
  }

  return (
    <div className="p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8E8778]">Futures account snapshot</p>
      <h3 className="mt-2 text-base font-semibold text-[#EDE7DB]">Authenticated futures account values from the latest synchronized read-only MEXC account response.</h3>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-[#8E8778]">Settlement asset</dt>
          <dd className="font-mono text-[#EDE7DB]">{futuresAccount.settlement_asset}</dd>
        </div>
        {FUTURES_FIELDS.map(([key, label]) => (
          <div key={key}>
            <dt className="text-xs text-[#8E8778]">{label}</dt>
            <dd className="font-mono tabular-nums text-[#EDE7DB]">{formatCurrency(futuresAccount[key])}</dd>
          </div>
        ))}
        <div>
          <dt className="text-xs text-[#8E8778]">Source time</dt>
          <dd className="font-mono text-xs text-[#EDE7DB]">{formatDate(futuresAccount.source_ts)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[#8E8778]">Synced at</dt>
          <dd className="font-mono text-xs text-[#EDE7DB]">{formatDate(futuresAccount.synced_at)}</dd>
        </div>
      </dl>
    </div>
  );
}

function Phase2AUnavailableStates({ partial, hasCapitalFlowGap }: { partial: boolean; hasCapitalFlowGap: boolean }) {
  return (
    <div className="space-y-4 p-4">
      {partial && (
        <div>
          <h3 className="text-sm font-semibold text-[#EDE7DB]">Partial history</h3>
          <p className="mt-1 text-sm text-[#8E8778]">Only part of portfolio history is available. Miraj only shows the proven coverage window.</p>
        </div>
      )}
      <div>
        <h3 className="text-sm font-semibold text-[#EDE7DB]">Account return unavailable</h3>
        <p className="mt-1 text-sm text-[#8E8778]">Account return needs opening equity and complete capital-flow history. Phase 2A does not calculate it.</p>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-[#EDE7DB]">Capital-flow history unavailable</h3>
        <p className="mt-1 text-sm text-[#8E8778]">
          {hasCapitalFlowGap
            ? "Funding, transfers, deposits, and withdrawals are not ingested in Phase 2A."
            : "Capital-flow history is not proven by the current sync coverage."}
        </p>
        <p className="mt-1 text-xs text-[#8E8778]">Ledger ingestion and retention validation belong to Phase 2B.</p>
      </div>
    </div>
  );
}

function coverageWindow(item: SyncCoverageItem): string {
  if (item.oldest_source_ts && item.newest_source_ts) {
    return `${formatDate(item.oldest_source_ts)} to ${formatDate(item.newest_source_ts)}`;
  }
  if (item.last_success_at) return `as of ${formatDate(item.last_success_at)}`;
  if (item.last_attempt_at) return `attempted ${formatDate(item.last_attempt_at)}`;
  return "No source window";
}

function rowCount(item: SyncCoverageItem): string {
  if (typeof item.source_total === "number") {
    return `${item.rows_fetched_total.toLocaleString()} of ${item.source_total.toLocaleString()}`;
  }
  return item.rows_fetched_total > 0 ? item.rows_fetched_total.toLocaleString() : "—";
}

function coverageDetail(item: SyncCoverageItem): string {
  if (item.status === "fresh") return "Synced successfully.";
  if (item.status === "stale") return item.last_success_at ? `Showing cached data from ${formatDate(item.last_success_at)}.` : "No recent successful sync is recorded.";
  if (item.status === "partial") return item.reason ? `${humanize(item.reason)}. Rows synced: ${rowCount(item)}.` : "The exchange boundary or response stopped before complete coverage was proven.";
  if (item.status === "error") return item.last_success_at ? `Showing the last cached data from ${formatDate(item.last_success_at)}. Error details are redacted.${item.error_code ? ` Code: ${item.error_code}.` : ""}` : `No cached data is available for this stream. Error details are redacted.${item.error_code ? ` Code: ${item.error_code}.` : ""}`;
  if (item.status === "unavailable") return unavailableDetail(item);
  if (item.status === "not_enabled_phase_2b") return phase2BDetail(item);
  return item.reason ? humanize(item.reason) : "Coverage state recorded by the backend.";
}

function unavailableDetail(item: SyncCoverageItem): string {
  if (item.reason === "requires_spot_wallet_endpoint_and_retention_probe_phase_2b") {
    return "Requires spot-wallet endpoint and retention probe in Phase 2B.";
  }
  if (item.reason === "futures_account_snapshot_missing") return "Futures account snapshot missing.";
  return "This stream is unavailable in Phase 2A.";
}

function phase2BDetail(item: SyncCoverageItem): string {
  if (item.stream === "funding") {
    return "Not enabled in Phase 2A. Funding history is supported by exchange capability research but ledger ingestion belongs to Phase 2B.";
  }
  if (item.stream === "futures_transfers") {
    return "Not enabled in Phase 2A. Futures transfer history is supported by exchange capability research but ledger ingestion belongs to Phase 2B.";
  }
  return "Not enabled in Phase 2A.";
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatCurrency(value: FuturesAccountItem[keyof FuturesAccountItem]): string {
  return typeof value === "number"
    ? `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "Unavailable";
}

function formatDate(value: string): string {
  return formatUtcDateTime(value);
}

export default SyncStatusPanel;
