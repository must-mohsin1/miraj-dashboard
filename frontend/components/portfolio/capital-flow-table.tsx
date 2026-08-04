"use client";

import type { CapitalFlowEntry, SyncCoverageItem } from "@/lib/types";
import { formatUtcDateTime } from "@/lib/date-format";

const TYPE_LABELS: Record<string, string> = {
  funding: "Funding",
  futures_transfer: "Futures transfer",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
};

const CAPITAL_FLOW_STREAMS = new Set([
  "funding",
  "futures_transfers",
  "deposits",
  "withdrawals",
]);

const GAP_STATUSES = new Set(["partial", "unavailable", "error"]);

function typeLabel(entryType: string): string {
  return TYPE_LABELS[entryType] ?? humanize(entryType);
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSignedAmount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const body =
    abs >= 1000
      ? abs.toLocaleString(undefined, { maximumFractionDigits: 8 })
      : abs.toString();
  if (value > 0) return `+${body}`;
  if (value < 0) return `-${body}`;
  return "0";
}

function signedAmountClass(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) {
    return "text-[#EDE7DB]";
  }
  return value > 0 ? "text-[#6CA98F]" : "text-[#C96A55]";
}

function bannerDetail(sync: SyncCoverageItem[]): string | null {
  const gaps = sync.filter(
    (item) => CAPITAL_FLOW_STREAMS.has(item.stream) && GAP_STATUSES.has(item.status),
  );
  if (gaps.length === 0) return null;
  const withReason = gaps.find((item) => item.reason);
  if (!withReason?.reason) return null;
  return humanize(withReason.reason);
}

export function CapitalFlowTable({
  entries,
  sync,
  partial = false,
}: {
  entries: CapitalFlowEntry[];
  sync: SyncCoverageItem[];
  partial?: boolean;
}) {
  const showBanner =
    partial ||
    sync.some(
      (s) => CAPITAL_FLOW_STREAMS.has(s.stream) && GAP_STATUSES.has(s.status),
    );

  const detail = bannerDetail(sync);

  return (
    <section
      className="border border-[#2A2620] bg-[#161411]"
      aria-labelledby="capital-flow-title"
    >
      <div className="border-b border-[#2A2620] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#C2A36B]">
          Capital flow
        </p>
        <h2
          id="capital-flow-title"
          className="mt-1 text-lg font-semibold text-[#EDE7DB]"
        >
          Ledger entries
        </h2>
        <p className="mt-2 text-sm text-[#8E8778]">
          Read-only funding, transfers, deposits, and withdrawals ingested from
          the exchange.
        </p>
      </div>

      {showBanner && (
        <div
          className="border-b border-[#2A2620] px-4 py-3 text-sm text-[#D19A4A]"
          role="status"
        >
          <p>History truncated at exchange boundary. Miraj only shows proven ledger coverage.</p>
          {detail && (
            <p className="mt-1 text-xs text-[#8E8778]">{detail}.</p>
          )}
        </div>
      )}

      {entries.length === 0 ? (
        <div className="p-4">
          <h3 className="text-sm font-semibold text-[#EDE7DB]">No ledger entries</h3>
          <p className="mt-1 text-sm text-[#8E8778]">
            Miraj has no proven capital-flow rows for this exchange yet. Rows are
            never invented.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              Capital-flow ledger entries for funding, transfers, deposits, and
              withdrawals
            </caption>
            <thead className="border-b border-[#2A2620] text-[11px] uppercase tracking-[0.18em] text-[#8E8778]">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">
                  Date
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  Type
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  Asset
                </th>
                <th scope="col" className="px-4 py-3 font-medium text-right">
                  Signed amount
                </th>
                <th scope="col" className="px-4 py-3 font-medium">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#2A2620]">
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="px-4 py-3 align-top font-mono text-xs text-[#EDE7DB]">
                    {entry.occurred_at
                      ? formatUtcDateTime(entry.occurred_at)
                      : "—"}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <span className="inline-flex border border-[#2A2620] px-2 py-0.5 text-xs font-semibold text-[#EDE7DB]">
                      {typeLabel(entry.entry_type)}
                    </span>
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs text-[#EDE7DB]">
                    {entry.asset}
                  </td>
                  <td
                    className={`px-4 py-3 align-top text-right font-mono tabular-nums text-xs ${signedAmountClass(entry.signed_amount)}`}
                  >
                    {formatSignedAmount(entry.signed_amount)}
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-[#8E8778]">
                    {entry.status ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default CapitalFlowTable;
