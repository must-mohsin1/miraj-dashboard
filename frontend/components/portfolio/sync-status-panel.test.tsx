import { render, screen, within } from "@testing-library/react";

import { SyncStatusPanel } from "@/components/portfolio/sync-status-panel";
import type { FuturesAccountItem, SyncCoverageItem } from "@/lib/types";

function coverage(overrides: Partial<SyncCoverageItem>): SyncCoverageItem {
  return {
    stream: "positions_history",
    status: "fresh",
    complete: true,
    reason: null,
    rows_fetched_total: 237,
    source_total: 237,
    oldest_source_ts: "2026-07-01T00:00:00Z",
    newest_source_ts: "2026-07-25T20:00:00Z",
    last_success_at: "2026-07-25T20:00:00Z",
    last_attempt_at: "2026-07-25T20:00:00Z",
    unrecoverable_gaps: [],
    ...overrides,
  };
}

/** Real capital-flow stream statuses (Phase 2B): funding fresh, transfers partial, deposits unavailable, withdrawals error. */
const ALL_STATES: SyncCoverageItem[] = [
  coverage({ stream: "positions_history", status: "fresh" }),
  coverage({ stream: "orders_history", status: "stale", complete: false, last_success_at: "2026-07-24T20:00:00Z" }),
  coverage({
    stream: "futures_account_assets",
    status: "partial",
    complete: false,
    reason: "retention_boundary",
    rows_fetched_total: 80,
    source_total: 100,
  }),
  coverage({ stream: "funding", status: "fresh" }),
  coverage({
    stream: "futures_transfers",
    status: "partial",
    complete: false,
    reason: "retention_boundary",
    rows_fetched_total: 10,
    source_total: 50,
  }),
  coverage({
    stream: "deposits",
    status: "unavailable",
    complete: false,
    reason: "endpoint_unavailable",
    rows_fetched_total: 0,
    source_total: null,
  }),
  coverage({
    stream: "withdrawals",
    status: "error",
    complete: false,
    error_code: "MEXC_510",
    last_success_at: "2026-07-23T20:00:00Z",
    rows_fetched_total: 0,
    source_total: null,
  }),
];

const ALL_CAPITAL_FRESH: SyncCoverageItem[] = [
  coverage({ stream: "positions_history", status: "fresh" }),
  coverage({ stream: "funding", status: "fresh" }),
  coverage({ stream: "futures_transfers", status: "fresh" }),
  coverage({ stream: "deposits", status: "fresh" }),
  coverage({ stream: "withdrawals", status: "fresh" }),
];

const FUTURES_ACCOUNT: FuturesAccountItem = {
  settlement_asset: "USDT",
  equity: 1200.5,
  available_balance: 800.25,
  frozen_balance: 10,
  cash_balance: 900,
  position_margin: 300,
  unrealized_pnl: -12.34,
  bonus: 0,
  available_cash: 700,
  debt_amount: 0,
  source_ts: "2026-07-25T20:00:00Z",
  synced_at: "2026-07-25T20:01:00Z",
};

describe("SyncStatusPanel", () => {
  it("renders every coverage state as visible text paired with stream labels", () => {
    render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={FUTURES_ACCOUNT} partial />);

    const table = screen.getByRole("table", { name: "MEXC stream synchronization coverage states" });
    expect(within(table).getByText("Position history")).toBeInTheDocument();
    expect(within(table).getByText("Order history")).toBeInTheDocument();
    expect(within(table).getByText("Stale")).toBeInTheDocument();
    expect(within(table).getByText("Futures account assets")).toBeInTheDocument();
    expect(within(table).getByText("Funding history")).toBeInTheDocument();
    expect(within(table).getByText("Futures transfers")).toBeInTheDocument();
    expect(within(table).getByText("Deposits")).toBeInTheDocument();
    expect(within(table).getByText("Unavailable")).toBeInTheDocument();
    expect(within(table).getByText("Withdrawals")).toBeInTheDocument();
    expect(within(table).getByText("Sync error")).toBeInTheDocument();
    // Capital streams use real statuses — partial (not Phase 2B placeholder)
    expect(within(table).getAllByText("Partial history").length).toBeGreaterThanOrEqual(1);
    expect(within(table).getAllByText("Fresh").length).toBeGreaterThanOrEqual(1);
    expect(within(table).queryByText("Phase 2B")).not.toBeInTheDocument();
    expect(within(table).getAllByText("Jul 1, 2026, 00:00 UTC to Jul 25, 2026, 20:00 UTC").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("237 of 237").length).toBeGreaterThan(0);
  });

  it("uses the INK & OXIDE palette instead of Tailwind slate or indigo classes", () => {
    const { container } = render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={FUTURES_ACCOUNT} partial />);

    expect(container.innerHTML).toContain("#161411");
    expect(container.innerHTML).toContain("#2A2620");
    expect(container.innerHTML).toContain("#EDE7DB");
    expect(container.innerHTML).toContain("#C2A36B");
    expect(container.innerHTML).not.toMatch(/(?:slate|indigo)-/);
  });

  it("shows futures account snapshot fields without reusing spot balances", () => {
    render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={FUTURES_ACCOUNT} />);

    expect(screen.getByText("Futures account snapshot")).toBeInTheDocument();
    expect(screen.getByText("Authenticated futures account values from the latest synchronized read-only MEXC account response.")).toBeInTheDocument();
    expect(screen.queryByText(/read-only MEXC fixture/i)).not.toBeInTheDocument();
    expect(screen.getByText("Settlement asset")).toBeInTheDocument();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("$1,200.50")).toBeInTheDocument();
    expect(screen.getByText("Jul 25, 2026, 20:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("Jul 25, 2026, 20:01 UTC")).toBeInTheDocument();
    expect(screen.queryByText("Account return unavailable")).toBeInTheDocument();
  });

  it("renders account return when Phase 3 value is provided", () => {
    render(
      <SyncStatusPanel
        sync={ALL_CAPITAL_FRESH}
        futuresAccount={FUTURES_ACCOUNT}
        accountReturnPct={12.5}
        netAccountProfitUsd={150}
      />,
    );

    expect(screen.getByText("Account return")).toBeInTheDocument();
    expect(screen.getByText("+12.50%")).toBeInTheDocument();
    expect(screen.getByText(/net profit \+\$150\.00/)).toBeInTheDocument();
    expect(screen.queryByText("Account return unavailable")).not.toBeInTheDocument();
  });

  it("renders partial history and capital-flow/account-return copy without lifetime-complete claims", () => {
    render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={null} partial />);

    expect(screen.getByText("Futures snapshot unavailable")).toBeInTheDocument();
    expect(screen.getByText("Spot balances are not futures collateral. Miraj will not use spot balances as futures equity.")).toBeInTheDocument();
    expect(screen.getAllByText("Partial history").length).toBeGreaterThan(0);
    expect(screen.getByText("Capital-flow history unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Capital-flow history is partial or unavailable for one or more streams."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Funding, transfers, deposits, and withdrawals are not ingested in Phase 2A.")).not.toBeInTheDocument();
    expect(screen.queryByText("Ledger ingestion and retention validation belong to Phase 2B.")).not.toBeInTheDocument();
    expect(screen.getByText("Account return unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Account return uses futures wallet equity only \(spot is never the base\)/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Complete history/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Full history/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lifetime history/i)).not.toBeInTheDocument();
  });

  it("shows synchronized capital-flow copy when all four streams are fresh", () => {
    render(<SyncStatusPanel sync={ALL_CAPITAL_FRESH} futuresAccount={FUTURES_ACCOUNT} />);

    expect(screen.getByText("Capital-flow streams are synchronized.")).toBeInTheDocument();
    expect(
      screen.queryByText("Capital-flow history is partial or unavailable for one or more streams."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Account return unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Account return uses futures wallet equity only \(spot is never the base\)/,
      ),
    ).toBeInTheDocument();
  });

  it("explains futures_equity_flat without implying spot is the return base", () => {
    render(
      <SyncStatusPanel
        sync={ALL_CAPITAL_FRESH}
        futuresAccount={{ ...FUTURES_ACCOUNT, equity: 0 }}
        accountReturnReason="futures_equity_flat"
      />,
    );

    expect(screen.getByText("Account return unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(/futures wallet equity is flat \(zero\)/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Spot balances are not account equity for return/i),
    ).toBeInTheDocument();
  });

  it("labels available return as futures equity only", () => {
    render(
      <SyncStatusPanel
        sync={ALL_CAPITAL_FRESH}
        futuresAccount={FUTURES_ACCOUNT}
        accountReturnPct={5}
        netAccountProfitUsd={50}
      />,
    );

    expect(
      screen.getByText(/Futures equity only — cash-flow-adjusted/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Spot balances are not account equity for return/i),
    ).toBeInTheDocument();
  });
});
