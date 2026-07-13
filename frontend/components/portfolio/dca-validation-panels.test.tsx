import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DcaValidationEvents } from "./dca-validation-events";
import { DcaShadowHistoryTable } from "./dca-shadow-history-table";
import { DcaValidationSummary, type DcaValidationResponse } from "./dca-validation-summary";
import { DcaValidationSymbolTable } from "./dca-validation-symbol-table";

const disclaimer = "These are reconstructed and shadow-mode results, not realized trading performance or financial advice.";

const validation: DcaValidationResponse = {
  state: "metrics_available",
  exchange: "binance",
  last_completed: { completed_at: "2026-07-13T10:00:00Z", state: "metrics_available" },
  disclaimer,
  validation_errors: [],
  reconstruction: {
    exchange: "binance",
    method: "scan-to-scan",
    method_description: "scan-history reconstruction; not candle-level historical replay",
    fill_assumptions: { fee_percent: 0.04, slippage_percent: 0.05 },
    symbols: [
      {
        symbol: "BTCUSDT:USDT",
        status: "insufficient_history",
        required_minimum_scans: 2,
        scan_count: 1,
        first_scan_at: "2026-07-10T00:00:00Z",
        last_scan_at: "2026-07-10T00:00:00Z",
        max_scan_gap_seconds: null,
        events: [],
        skipped_scans: [],
      },
      {
        symbol: "SOLUSDT:USDT",
        status: "metrics_available",
        direction: "LONG",
        required_minimum_scans: 2,
        scan_count: 42,
        first_scan_at: "2026-07-01T00:00:00Z",
        last_scan_at: "2026-07-12T00:00:00Z",
        max_scan_gap_seconds: 54 * 60 * 60,
        events: [
          {
            timestamp: "2026-07-12T00:00:00Z",
            symbol: "SOLUSDT:USDT",
            recommendation: "ADD",
            confidence: "HIGH",
            reason: "RSI entered the first DCA band.",
            participates_in_metrics: true,
          },
        ],
        skipped_scans: [{ timestamp: "2026-07-11T00:00:00Z", symbol: "SOLUSDT:USDT", reason: "missing_rsi" }],
      },
      {
        symbol: "XRPUSDT:USDT",
        status: "validation_error",
        required_minimum_scans: 2,
        scan_count: 8,
        first_scan_at: "2026-07-01T00:00:00Z",
        last_scan_at: "2026-07-12T00:00:00Z",
        max_scan_gap_seconds: 3600,
        unavailable_source: "missing_trade_plan",
        events: [],
        skipped_scans: [{ timestamp: "2026-07-12T00:00:00Z", symbol: "XRPUSDT:USDT", reason: "missing_trade_plan" }],
      },
    ],
  },
  metrics: {
    exchange: "binance",
    split_ratio: 0.7,
    portfolio: { metrics: {} },
    symbols: [
      {
        symbol: "SOLUSDT:USDT",
        status: "metrics_available",
        scan_count: 42,
        metrics: {
          win_rate: { value: 66.7 },
          total_return: { value: 12.3 },
          gross_profit: { value: 240 },
          gross_loss: { value: -80 },
          profit_factor: { value: null, reason: "no gross losses" },
          max_drawdown_absolute: { value: 40 },
          max_drawdown_percent: { value: 6.2 },
          sharpe: { value: 1.4 },
          sortino: { value: null, reason: "Not enough samples — needs at least 2 return observations." },
          average_hold_time_hours: { value: 18 },
          exposure_percentage: { value: 22 },
          reconstructed_trade_count: { value: 5 },
        },
        dca_metrics: {
          entry_level_completion_rate: { value: 50 },
          add_follow_through_rate: { value: 60 },
          dca_safe_flag_accuracy: { value: 75 },
          three_entry_completion_rate: { value: 25 },
        },
        walk_forward: {
          split_ratio: 0.7,
          in_sample: { date_range: { start: "2026-07-01T00:00:00Z", end: "2026-07-08T00:00:00Z" } },
          out_of_sample: { date_range: { start: "2026-07-09T00:00:00Z", end: "2026-07-12T00:00:00Z" } },
        },
        buy_and_hold_benchmark: { value: null, reason: "missing first or last usable mark price" },
      },
    ],
  },
  shadow_history: [
    {
      timestamp: "2026-07-12T03:00:00Z",
      exchange: "binance",
      symbol: "ETHUSDT:USDT",
      original_recommendation: "ADD",
      final_outcome: "would_block",
      blocked_gates: ["confluence_score", "exposure_cap"],
      final_reason: "Blocked: confluence score is 8.5, below the required 10.",
      assumption_set: { mode: "shadow_non_live", fee_percent: 0.04, slippage_percent: 0.05, split_ratio: 0.7, min_confluence_score: 10, exposure_cap_pct: 35 },
      gate_breakdown: [
        { name: "Confluence score is at least 10", passed: false, reason: "Confluence score is 8.5, below the required 10." },
        { name: "Total DCA exposure stays under the configured cap", passed: false, reason: "Simulated ADD would exceed the configured exposure cap." },
        { name: "User kill switch is off", passed: true, reason: "User kill switch is off." },
        { name: "No more than 3 ADD decisions in the last hour", passed: true, reason: "Hourly ADD limit has not been reached." },
      ],
    },
  ],
};

describe("DCA validation panels", () => {
  it("renders summary headline fields and disclaimer text", () => {
    render(<DcaValidationSummary validation={validation} />);

    expect(screen.getByText("Eligible symbols")).toBeInTheDocument();
    expect(screen.getByText("Usable scans")).toBeInTheDocument();
    expect(screen.getByText("Reconstructed recommendations")).toBeInTheDocument();
    expect(screen.getByText("Latest validation")).toBeInTheDocument();
    expect(screen.getByText("Blocked by safety gates")).toBeInTheDocument();
    expect(screen.getByText(disclaimer)).toBeInTheDocument();
    expect(screen.getByText(/Fee 0.04% · slippage 0.05%/)).toBeInTheDocument();
  });

  it("renders insufficient history without fake numeric metrics", () => {
    render(<DcaValidationSymbolTable symbols={validation.reconstruction!.symbols} metrics={validation.metrics!.symbols} />);

    expect(screen.getByText("Insufficient history")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT:USDT needs more scan history")).toBeInTheDocument();
    expect(screen.getByText("We found 1 usable scan(s). Metrics will appear after at least 2 usable scans with price, RSI, trade plan, and position context.")).toBeInTheDocument();
    expect(screen.getAllByText("Not enough usable scans.").length).toBeGreaterThanOrEqual(4);
  });

  it("renders metrics available state with scan metadata, walk-forward ranges, benchmark, and disclaimer", () => {
    render(<DcaValidationSymbolTable symbols={validation.reconstruction!.symbols} metrics={validation.metrics!.symbols} />);

    const solCard = screen.getByRole("article", { name: /SOLUSDT:USDT/i });
    expect(within(solCard).getByText("Metrics available")).toBeInTheDocument();
    expect(within(solCard).getByText("42")).toBeInTheDocument();
    expect(within(solCard).getByText("2.25d")).toBeInTheDocument();
    expect(within(solCard).getByText("scan-history reconstruction")).toBeInTheDocument();
    expect(within(solCard).getByText("Walk-forward split")).toBeInTheDocument();
    expect(within(solCard).getByText(/Benchmark unavailable — missing first or last usable mark price/)).toBeInTheDocument();
    expect(within(solCard).getByText(disclaimer)).toBeInTheDocument();
  });

  it("renders latest reconstructed events and skipped-scan reasons", () => {
    const sol = validation.reconstruction!.symbols[1];
    render(<DcaValidationEvents symbol="SOLUSDT:USDT" events={sol.events} skippedScans={sol.skipped_scans} />);

    expect(screen.getByRole("table", { name: "Reconstructed events for SOLUSDT:USDT" })).toBeInTheDocument();
    expect(screen.getByText("ADD")).toBeInTheDocument();
    expect(screen.getByText("RSI entered the first DCA band.")).toBeInTheDocument();
    expect(screen.getByText("Missing Rsi")).toBeInTheDocument();
  });

  it("displays blocked reason details with gate-by-gate pass/fail breakdown", async () => {
    render(<DcaShadowHistoryTable history={validation.shadow_history} />);

    expect(screen.getByRole("table", { name: "Shadow history" })).toBeInTheDocument();
    expect(screen.getAllByText("ETHUSDT:USDT").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("would_block")).toBeInTheDocument();
    expect(screen.getByText(/2 blocked/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Show blocked safety gates for ETHUSDT:USDT/i }));

    expect(screen.getByText("Why shadow ADD was blocked")).toBeInTheDocument();
    expect(screen.getAllByText("Blocked gates").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Passed gates")).toBeInTheDocument();
    expect(screen.getByText("Blocked: confluence score is 8.5, below the required 10.")).toBeInTheDocument();
    expect(screen.getByText(/Simulated ADD would exceed the configured exposure cap/)).toBeInTheDocument();
    expect(screen.getAllByText(/fee 0.04% · slippage 0.05% · split 70\/30/).length).toBeGreaterThanOrEqual(1);
  });

  it("filters shadow history by outcome", async () => {
    render(<DcaShadowHistoryTable history={validation.shadow_history} />);

    await userEvent.selectOptions(screen.getByLabelText("Outcome"), "would_allow");
    expect(screen.getByText("No shadow decisions match these filters. Try a different symbol, outcome, or date range.")).toBeInTheDocument();
  });
});
