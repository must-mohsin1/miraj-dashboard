import { render, screen, waitFor } from "@testing-library/react";
import { execFileSync } from "child_process";

import { AllocationPie } from "@/components/portfolio/allocation-pie";
import { BenchmarkComparison } from "@/components/portfolio/benchmark-comparison";
import { EquityCurve } from "@/components/portfolio/equity-curve";
import { HealthScorePanel } from "@/components/portfolio/health-score-panel";
import { PerformanceMetrics } from "@/components/portfolio/performance-metrics";
import { RiskMetricsPanel } from "@/components/portfolio/risk-metrics-panel";
import type { PerformanceMetrics as PerformanceMetricsType } from "@/lib/types";

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
    expect(screen.getByText("Account return unavailable — capital history missing")).toBeInTheDocument();
    expect(screen.queryByText("+25.00%")).not.toBeInTheDocument();
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
    expect(screen.getByText("PortfolioSnapshot.total_balance_usd is missing; realised-PnL reconstruction is shown separately.")).toBeInTheDocument();
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
