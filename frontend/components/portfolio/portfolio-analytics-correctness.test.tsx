import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { execFileSync } from "child_process";

import { AllocationPie } from "@/components/portfolio/allocation-pie";
import { AnalyticsDashboard } from "@/components/portfolio/analytics-dashboard";
import { BenchmarkComparison } from "@/components/portfolio/benchmark-comparison";
import { EquityCurve } from "@/components/portfolio/equity-curve";
import { HealthScorePanel } from "@/components/portfolio/health-score-panel";
import { PerformanceMetrics } from "@/components/portfolio/performance-metrics";
import { RiskMetricsPanel } from "@/components/portfolio/risk-metrics-panel";
import type {
  ClosedPositionAnalyticsResponse,
  PerformanceMetrics as PerformanceMetricsType,
} from "@/lib/types";

const METRICS: PerformanceMetricsType = {
  win_rate: 66.67,
  profit_factor: 6,
  sharpe_ratio: null,
  max_drawdown: 5,
  max_drawdown_percent: 20,
  realised_pnl_drawdown_usd: 5,
  realised_pnl_drawdown_pct: 20,
  drawdown_basis: "cumulative_closed_pnl",
  trade_quality_score: 1.25,
  trade_quality_basis: "per_trade_pnl_dispersion",
  average_win: 15,
  average_loss: -5,
  total_trades: 3,
  winning_trades: 2,
  losing_trades: 1,
  best_trade: 20,
  worst_trade: -5,
  total_pnl: 25,
  total_pnl_basis: "MEXC-reported closed-position PnL",
  total_pnl_percent: null,
  total_pnl_percent_reason: "capital_history_missing",
  account_return_pct: null,
  account_return_pct_reason: "capital_history_missing",
};

const CLOSED_ANALYTICS: ClosedPositionAnalyticsResponse = {
  exchange: "mexc",
  filters_applied: { timezone: "UTC", period: "week" },
  basis: {
    pnl_source: "PositionHistory.pnl",
    pnl_basis: "MEXC-reported closed-position PnL",
    currency_unit: "USDT",
    fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
    size_unit: "contracts",
  },
  history: {
    history_scope: "stored_closed_positions",
    history_completeness: "unknown",
    reason: "full_history_sync_not_implemented_phase2",
    row_count: 49,
    first_close_time: "2026-07-24T10:00:00+00:00",
    last_close_time: "2026-07-24T12:00:00+00:00",
  },
  excluded_reasons: {},
  overview: {
    total_trades: 49,
    winning_trades: 48,
    losing_trades: 1,
    breakeven_trades: 0,
    total_pnl: 49.23,
    win_rate_pct: 97.96,
    average_trade_pnl: 1,
    average_pnl_per_active_day: 49.23,
    average_pnl_per_active_day_label: "per active trading day",
    average_pnl_per_calendar_day: 24.62,
    average_pnl_per_calendar_day_label: "per calendar day",
  },
  periods: {
    exchange: "mexc",
    filters_applied: { timezone: "UTC", period: "week" },
    basis: {
      pnl_source: "PositionHistory.pnl",
      pnl_basis: "MEXC-reported closed-position PnL",
      currency_unit: "USDT",
      fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
      size_unit: "contracts",
    },
    history: {
      history_scope: "stored_closed_positions",
      history_completeness: "unknown",
      reason: "full_history_sync_not_implemented_phase2",
      row_count: 49,
    },
    excluded_reasons: {},
    period: "week",
    items: [],
    totals: { trade_count: 49, total_pnl: 49.23 },
  },
  calendar_days: [],
  concentration: {},
  breakdowns: {},
  explorer: {
    exchange: "mexc",
    filters_applied: { timezone: "UTC", period: "week" },
    sort: "-close_time",
    limit: 50,
    offset: 0,
    total: 49,
    has_more: false,
    basis: {
      pnl_source: "PositionHistory.pnl",
      pnl_basis: "MEXC-reported closed-position PnL",
      currency_unit: "USDT",
      fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
      size_unit: "contracts",
    },
    history: {
      history_scope: "stored_closed_positions",
      history_completeness: "unknown",
      reason: "full_history_sync_not_implemented_phase2",
      row_count: 49,
    },
    excluded_reasons: {},
    items: [],
  },
  unavailable: {
    fee_net_pnl: {
      value: null,
      reason: "fee_net_pnl_unavailable_phase2_ledger_required",
    },
    account_return_pct: { value: null, reason: "capital_history_missing" },
    account_equity: { value: null, reason: "account_equity_unavailable_phase3" },
  },
};

afterEach(() => {
  jest.restoreAllMocks();
});

describe("portfolio analytics Phase 0 truth labels", () => {
  it("keeps Phase 0-added portfolio UI lines on design-system tokens", () => {
    const base = "ab1366e3408b249c8542627b59e79ca007c32473";
    const diff = execFileSync(
      "git",
      ["diff", "--unified=0", base, "--", "components/portfolio"],
      { cwd: process.cwd(), encoding: "utf8" },
    );
    const bannedUtilityPattern = new RegExp(
      String.raw`rounded-(?:x` +
        String.raw`l|lg|md|full)|` +
        String.raw`slate` +
        String.raw`-`,
    );
    const addedViolations = diff
      .split("\n")
      .filter((line) => line.startsWith("+") && !line.startsWith("+++"))
      .filter((line) => bannedUtilityPattern.test(line));

    expect(addedViolations).toEqual([]);
  });

  it("does not render account return from summed position ROI", () => {
    render(<PerformanceMetrics metrics={METRICS} />);

    expect(screen.getByText("MEXC-reported closed-position PnL")).toBeInTheDocument();
    expect(screen.getByText("Account return")).toBeInTheDocument();
    expect(screen.getByText(/Unavailable —/)).toBeInTheDocument();
    expect(screen.getByText(/capital-flow history not synced|capital history missing/i)).toBeInTheDocument();
    expect(screen.queryByText("+25.00%")).not.toBeInTheDocument();
  });

  it("wires the Phase 1 dashboard tab to one shared closed-position filter query", async () => {
    const user = userEvent.setup();
    const ok = (data: unknown) => Promise.resolve({ ok: true, json: async () => data });
    const fetchMock = jest.fn((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.includes("closed-position-analytics")) return ok(CLOSED_ANALYTICS);
      if (path.includes("performance")) return ok(METRICS);
      if (path.includes("equity-curve")) return ok({ exchange: "mexc", points: [], basis: null, source: null, complete: false, unavailable_reason: "no_account_equity_data" });
      if (path.includes("daily-pnl")) return ok({ exchange: "mexc", days: [], timezone: "UTC", period: { from: null, to: null } });
      if (path.includes("allocation")) return ok({ exchange: "mexc", account_type: "spot", items: [] });
      return ok({});
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<AnalyticsDashboard token="token" exchange="mexc" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/analytics/mexc/closed-position-analytics?timezone=UTC&period=week&limit=50&offset=0&sort=-close_time"),
      expect.any(Object),
    ));

    await user.click(screen.getByRole("tab", { name: "Closed Positions" }));
    expect(await screen.findByText("Closed-position overview")).toBeInTheDocument();
    expect(screen.getAllByText("+$49.23 USDT").length).toBeGreaterThan(0);

    const topProvenance = (await screen.findAllByLabelText("Closed-position analytics basis and history note"))[0];
    const filters = screen.getByRole("form", { name: "Closed-position analytics filters" });
    expect(topProvenance.compareDocumentPosition(filters) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(topProvenance).toHaveTextContent("MEXC-reported closed-position PnL");
    expect(topProvenance).toHaveTextContent("USDT");
    expect(topProvenance).toHaveTextContent("Fee-net PnL unavailable");
    expect(topProvenance).toHaveTextContent("History scope: stored closed positions");
    expect(topProvenance).toHaveTextContent("Completeness: unknown");
    expect(topProvenance).toHaveTextContent("Full history sync not implemented until Phase 2");

    await user.selectOptions(screen.getByRole("combobox", { name: "Side" }), "long");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("side=long"))).toBe(true);
    });
  });

  it("labels realised-PnL drawdown and trade-quality score instead of conventional Sharpe", () => {
    render(<PerformanceMetrics metrics={METRICS} />);

    expect(screen.getByText("Trade Quality Score")).toBeInTheDocument();
    expect(screen.getByText("Per-trade PnL dispersion")).toBeInTheDocument();
    expect(screen.getByText("Realised-PnL Drawdown")).toBeInTheDocument();
    expect(screen.getByText(/Cumulative closed PnL/)).toBeInTheDocument();
    expect(screen.queryByText("Sharpe Ratio")).not.toBeInTheDocument();
  });

  it("shows an unavailable account-equity state instead of plotting unrealised PnL fallback", () => {
    render(
      <EquityCurve
        points={[]}
        basis={null}
        unavailableReason="no_account_equity_data"
      />
    );

    expect(screen.getByText("Account equity unavailable — no account equity data")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Futures wallet equity history is missing\. Spot balances are not account equity for this curve\./,
      ),
    ).toBeInTheDocument();
  });

  it("labels spot allocation separately from futures collateral", () => {
    render(
      <AllocationPie
        accountType="spot"
        items={[{ asset: "USDT", usd_value: 100, percentage: 100, account_type: "spot" }]}
      />
    );

    expect(screen.getByText("Spot Allocation")).toBeInTheDocument();
    expect(screen.getByText("Spot holdings only — not futures collateral.")).toBeInTheDocument();
  });

  it("renders no-open-futures risk as not applicable", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        exchange: "mexc",
        total_exposure_usd: 0,
        net_exposure_usd: 0,
        long_exposure_usd: 0,
        short_exposure_usd: 0,
        avg_liquidation_distance_pct: null,
        margin_usage_pct: null,
        total_margin_used: 0,
        total_balance_usd: null,
        open_positions: 0,
        risk_score: null,
        risk_reason: "no_open_futures_risk",
        unavailable_reason: "futures_equity_not_available",
      }),
    }) as unknown as typeof fetch;

    render(<RiskMetricsPanel token="token" exchange="mexc" />);

    expect(await screen.findByText("No open futures risk"));
    expect(screen.getByText("Margin usage unavailable — futures equity not available")).toBeInTheDocument();
  });

  it("renders flat health as not applicable with reason", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        exchange: "mexc",
        diversification_score: 0,
        correlation_risk: 0,
        concentration_risk: 0,
        health_score: null,
        grade: null,
        health_reason: "no_open_positions",
        recommendations: ["No open futures risk."],
        open_positions: 0,
        unique_assets: 0,
      }),
    }) as unknown as typeof fetch;

    render(<HealthScorePanel token="token" exchange="mexc" />);

    await waitFor(() => expect(screen.getByText("Not applicable")).toBeInTheDocument());
    expect(screen.getByText("No open positions")).toBeInTheDocument();
    expect(screen.queryByText("B")).not.toBeInTheDocument();
  });

  it("renders benchmark account-return comparison as unavailable instead of closed-PnL return", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        symbol: "BTC-USD",
        days: 30,
        btc_return_pct: 10,
        portfolio_return_pct: null,
        alpha: null,
        beta: null,
        source: "PortfolioSnapshot.total_balance_usd",
        basis: null,
        complete: false,
        unavailable_reason: "capital_history_missing",
        points: [
          { date: "2026-07-01", btc_return_pct: 0, portfolio_return_pct: null },
          { date: "2026-07-02", btc_return_pct: 10, portfolio_return_pct: null },
        ],
      }),
    }) as unknown as typeof fetch;

    render(<BenchmarkComparison token="token" exchange="mexc" />);

    await waitFor(() => expect(screen.getByText("Account-return benchmark unavailable")).toBeInTheDocument());
    expect(screen.getByText("Capital history missing; closed-position PnL is not account return.")).toBeInTheDocument();
    expect(screen.getByText("10.00%")).toBeInTheDocument();
    expect(screen.queryByText("Portfolio Return")).not.toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("Beta")).not.toBeInTheDocument();
  });
});
