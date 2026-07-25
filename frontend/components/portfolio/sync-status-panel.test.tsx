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

const ALL_STATES: SyncCoverageItem[] = [
  coverage({ stream: "positions_history", status: "fresh" }),
  coverage({ stream: "orders_history", status: "stale", complete: false, last_success_at: "2026-07-24T20:00:00Z" }),
  coverage({ stream: "futures_account_assets", status: "partial", complete: false, reason: "retention_boundary", rows_fetched_total: 80, source_total: 100 }),
  coverage({ stream: "funding", status: "error", complete: false, error_code: "MEXC_510", last_success_at: "2026-07-23T20:00:00Z" }),
  coverage({ stream: "deposits", status: "unavailable", complete: false, reason: "requires_spot_wallet_endpoint_and_retention_probe_phase_2b", rows_fetched_total: 0, source_total: null }),
  coverage({ stream: "futures_transfers", status: "not_enabled_phase_2b", complete: false, rows_fetched_total: 0, source_total: null }),
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
  it("renders every Phase 2A coverage state as visible text paired with stream labels", () => {
    render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={FUTURES_ACCOUNT} partial />);

    const table = screen.getByRole("table", { name: "MEXC stream synchronization coverage states" });
    expect(within(table).getByText("Position history")).toBeInTheDocument();
    expect(within(table).getByText("Fresh")).toBeInTheDocument();
    expect(within(table).getByText("Order history")).toBeInTheDocument();
    expect(within(table).getByText("Stale")).toBeInTheDocument();
    expect(within(table).getByText("Futures account assets")).toBeInTheDocument();
    expect(within(table).getByText("Partial history")).toBeInTheDocument();
    expect(within(table).getByText("Funding history")).toBeInTheDocument();
    expect(within(table).getByText("Sync error")).toBeInTheDocument();
    expect(within(table).getByText("Deposits")).toBeInTheDocument();
    expect(within(table).getByText("Unavailable")).toBeInTheDocument();
    expect(within(table).getByText("Futures transfers")).toBeInTheDocument();
    expect(within(table).getByText("Phase 2B")).toBeInTheDocument();
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
    expect(screen.getByText("Authenticated futures account values from the latest read-only MEXC fixture.")).toBeInTheDocument();
    expect(screen.getByText("Settlement asset")).toBeInTheDocument();
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("$1,200.50")).toBeInTheDocument();
    expect(screen.getByText("Jul 25, 2026, 20:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("Jul 25, 2026, 20:01 UTC")).toBeInTheDocument();
    expect(screen.queryByText("Account return")).not.toBeInTheDocument();
  });

  it("renders partial history and capital-flow/account-return unavailable copy without lifetime-complete claims", () => {
    render(<SyncStatusPanel sync={ALL_STATES} futuresAccount={null} partial />);

    expect(screen.getByText("Futures snapshot unavailable")).toBeInTheDocument();
    expect(screen.getByText("Spot balances are not futures collateral. Miraj will not use spot balances as futures equity.")).toBeInTheDocument();
    expect(screen.getAllByText("Partial history").length).toBeGreaterThan(0);
    expect(screen.getByText("Capital-flow history unavailable")).toBeInTheDocument();
    expect(screen.getByText("Funding, transfers, deposits, and withdrawals are not ingested in Phase 2A.")).toBeInTheDocument();
    expect(screen.getByText("Account return unavailable")).toBeInTheDocument();
    expect(screen.getByText("Account return needs opening equity and complete capital-flow history. Phase 2A does not calculate it.")).toBeInTheDocument();
    expect(screen.queryByText(/Complete history/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Full history/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lifetime history/i)).not.toBeInTheDocument();
  });
});
