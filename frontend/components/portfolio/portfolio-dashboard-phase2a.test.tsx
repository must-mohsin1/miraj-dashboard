import { render, screen } from "@testing-library/react";

import { PortfolioDashboard } from "@/components/portfolio/portfolio-dashboard";
import type { PortfolioResponse, SyncCoverageItem } from "@/lib/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: jest.fn() }),
}));

jest.mock("@/components/portfolio/balances-table", () => ({
  BalancesTable: () => <div>Balances table</div>,
}));
jest.mock("@/components/portfolio/positions-table", () => ({
  PositionsTable: () => <div>Positions table</div>,
}));
jest.mock("@/components/portfolio/trades-table", () => ({
  TradesTable: () => <div>Trades table</div>,
}));
jest.mock("@/components/portfolio/position-history-table", () => ({
  PositionHistoryTable: () => <div>Position history table</div>,
}));
jest.mock("@/components/portfolio/order-history-table", () => ({
  OrderHistoryTable: () => <div>Order history table</div>,
}));
jest.mock("@/components/portfolio/live-portfolio-header", () => ({
  LivePortfolioHeader: () => <div>Live portfolio header</div>,
}));
jest.mock("@/components/portfolio/analytics-dashboard", () => ({
  AnalyticsDashboard: () => <div>Analytics dashboard</div>,
}));
jest.mock("@/components/portfolio/position-alerts-panel", () => ({
  PositionAlertsPanel: () => <div>Position alerts panel</div>,
}));
jest.mock("@/components/portfolio/position-desk", () => ({
  PositionDesk: () => <div>Position desk</div>,
}));
jest.mock("@/components/portfolio/risk-metrics-panel", () => ({
  RiskMetricsPanel: () => <div>Risk metrics panel</div>,
}));
jest.mock("@/components/portfolio/dca-panel", () => ({
  DcaPanel: () => <div>DCA panel</div>,
}));
jest.mock("@/components/portfolio/capital-flow-table", () => ({
  CapitalFlowTable: () => <div>Capital flow table</div>,
}));

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

const PORTFOLIO: PortfolioResponse = {
  exchange: "mexc",
  balances: [{ asset: "USDT", free: 100, locked: 0, total: 100, usd_value: 100 }],
  positions: [],
  trades: [],
  position_history: [
    {
      exchange_position_id: "pos-1",
      symbol: "BTC_USDT",
      side: "long",
      size: 1,
      entry_price: 100,
      exit_price: 120,
      pnl: 20,
      pnl_percent: 20,
      leverage: 5,
      open_time: "2026-07-01T00:00:00Z",
      close_time: "2026-07-02T00:00:00Z",
      close_reason: "closed",
    },
  ],
  order_history: [],
  snapshot: { total_balance_usd: 100, total_pnl_usd: 20, open_positions: 0, timestamp: "2026-07-25T20:00:00Z" },
  sync: [
    coverage({ stream: "positions_history", status: "partial", complete: false, reason: "retention_boundary", rows_fetched_total: 237, source_total: 300 }),
    coverage({ stream: "orders_history", status: "fresh" }),
    coverage({ stream: "futures_account_assets", status: "unavailable", complete: false, reason: "futures_account_snapshot_missing", rows_fetched_total: 0, source_total: null }),
    coverage({ stream: "funding", status: "fresh" }),
    coverage({ stream: "futures_transfers", status: "partial", complete: false, reason: "retention_boundary", rows_fetched_total: 10, source_total: 50 }),
    coverage({ stream: "deposits", status: "unavailable", complete: false, reason: "endpoint_unavailable", rows_fetched_total: 0, source_total: null }),
    coverage({ stream: "withdrawals", status: "error", complete: false, error_code: "MEXC_510", rows_fetched_total: 0, source_total: null }),
  ],
  futures_account: null,
  partial: true,
  last_refreshed: "2026-07-25T20:00:00Z",
  stale: false,
};

afterEach(() => {
  jest.restoreAllMocks();
});

describe("PortfolioDashboard Phase 2A coverage states", () => {
  it("renders additive sync coverage and unavailable account/capital-flow states from mocked PortfolioResponse", () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;

    render(<PortfolioDashboard token="token" portfolio={PORTFOLIO} maskedKey="mx***" exchange="mexc" />);

    expect(screen.getByText("MEXC sync coverage")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Position History \(1\) · Partial history/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Order History \(0\) · Fresh/ })).toBeInTheDocument();
    expect(screen.getByText("Updated: Jul 25, 2026, 20:00 UTC")).toBeInTheDocument();
    expect(screen.getAllByText("Jul 1, 2026, 00:00 UTC to Jul 25, 2026, 20:00 UTC").length).toBeGreaterThan(0);
    expect(screen.getByText("Futures snapshot unavailable")).toBeInTheDocument();
    expect(screen.getByText("Spot balances are not futures collateral. Miraj will not use spot balances as futures equity.")).toBeInTheDocument();
    expect(screen.getByText("Capital-flow history unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Capital-flow history is partial or unavailable for one or more streams."),
    ).toBeInTheDocument();
    expect(screen.getByText("Account return unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Account return needs opening futures equity and complete external capital-flow history/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Complete history/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lifetime history/i)).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});
