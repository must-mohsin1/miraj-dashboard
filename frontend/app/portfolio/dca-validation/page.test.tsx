import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("@/lib/auth", () => ({
  getAccessToken: jest.fn().mockResolvedValue("test-token"),
}));

jest.mock("@/lib/dca-validation-api", () => ({
  buildDcaValidationPath: jest.fn(),
  fetchDcaValidation: jest.fn(),
}));

jest.mock("lucide-react", () => ({
  Activity: () => <svg data-testid="activity-icon" />,
  AlertTriangle: () => <svg data-testid="alert-icon" />,
  BarChart3: () => <svg data-testid="bar-chart-icon" />,
  ClipboardCheck: () => <svg data-testid="clipboard-check" />,
  Clock: () => <svg data-testid="clock-icon" />,
  Loader2: () => <svg data-testid="loader-icon" />,
  ShieldAlert: () => <svg data-testid="shield-alert" />,
  ShieldCheck: () => <svg data-testid="shield-check" />,
}));

import DcaValidationPage from "./page";
import { getAccessToken } from "@/lib/auth";
import { fetchDcaValidation } from "@/lib/dca-validation-api";
import type { DcaValidationResponse } from "@/components/portfolio/dca-validation-summary";

const disclaimer = "These are reconstructed and shadow-mode results, not realized trading performance or financial advice.";
const mockedGetAccessToken = getAccessToken as jest.MockedFunction<typeof getAccessToken>;
const mockedFetchDcaValidation = fetchDcaValidation as jest.MockedFunction<typeof fetchDcaValidation>;

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
        last_scan_at: "2026-07-13T00:00:00Z",
        max_scan_gap_seconds: 54 * 60 * 60,
        events: [
          {
            timestamp: "2026-07-13T00:00:00Z",
            symbol: "SOLUSDT:USDT",
            recommendation: "ADD",
            confidence: "HIGH",
            reason: "RSI entered the first DCA band.",
            participates_in_metrics: true,
          },
        ],
        skipped_scans: [{ timestamp: "2026-07-12T00:00:00Z", symbol: "SOLUSDT:USDT", reason: "missing_rsi" }],
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
        buy_and_hold_benchmark: { value: null, reason: "missing first or last usable mark price" },
      },
    ],
  },
  shadow_history: [
    {
      timestamp: "2026-07-13T03:00:00Z",
      exchange: "binance",
      symbol: "SOLUSDT:USDT",
      original_recommendation: "ADD",
      final_outcome: "would_block",
      blocked_gates: ["confluence_score", "exposure_cap"],
      final_reason: "Blocked: confluence score is 8.5, below the required 10.",
      assumption_set: { mode: "shadow_non_live", fee_percent: 0.04, slippage_percent: 0.05, split_ratio: 0.7, min_confluence_score: 10, exposure_cap_pct: 35 },
      gate_breakdown: [
        { name: "Confluence score is at least 10", passed: false, reason: "Confluence score is 8.5, below the required 10." },
        { name: "Total DCA exposure stays under the configured cap", passed: false, reason: "Simulated ADD would exceed the configured exposure cap." },
        { name: "User kill switch is off", passed: true, reason: "User kill switch is off." },
      ],
    },
  ],
};

async function renderPage(overrides: Partial<DcaValidationResponse> = {}, searchParams = {}) {
  mockedFetchDcaValidation.mockResolvedValue({ ...validation, ...overrides } as never);
  const view = await DcaValidationPage({ searchParams: Promise.resolve({ exchange: "binance", ...searchParams }) });
  return render(view);
}

describe("DCA validation page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetAccessToken.mockResolvedValue("test-token");
  });

  it("uses the shared API helper with normalized filters", async () => {
    await renderPage({}, { symbol: " solusdt:usdt ", start_date: "2026-07-01", end_date: "2026-07-13", split_ratio: "0.65", shadow_outcome: "would_block" });

    expect(mockedGetAccessToken).toHaveBeenCalledTimes(1);
    expect(mockedFetchDcaValidation).toHaveBeenCalledWith("binance", "test-token", {
      symbol: "SOLUSDT:USDT",
      startDate: "2026-07-01",
      endDate: "2026-07-13",
      splitRatio: 0.65,
      shadowOutcome: "would_block",
      shadowLimit: 50,
    });
  });

  it("renders the validation disclaimer from the composed summary panel", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { name: /DCA shadow-mode validation/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /DCA validation summary/i })).toBeInTheDocument();
    expect(screen.getAllByText(disclaimer).length).toBeGreaterThanOrEqual(1);
  });

  it("renders insufficient-history state without fake metrics", async () => {
    await renderPage({ state: "insufficient_history" });

    expect(screen.getByText("Insufficient scan history")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT:USDT needs more scan history")).toBeInTheDocument();
    expect(screen.getByText(/We found 1 usable scan\(s\)/)).toBeInTheDocument();
    expect(screen.getAllByText("Not enough usable scans.").length).toBeGreaterThanOrEqual(4);
  });

  it("renders metrics-available state for eligible symbols", async () => {
    await renderPage();

    const solCard = screen.getByRole("article", { name: /SOLUSDT:USDT/i });
    expect(within(solCard).getByText("Metrics available")).toBeInTheDocument();
    expect(within(solCard).getByText("Performance")).toBeInTheDocument();
    expect(within(solCard).getByText("ADD follow-through")).toBeInTheDocument();
    expect(within(solCard).getByText(/Benchmark unavailable — missing first or last usable mark price/)).toBeInTheDocument();
  });

  it("renders latest reconstructed events with skipped-scan reasons", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { name: "Latest reconstructed recommendation events" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Reconstructed events for SOLUSDT:USDT" })).toBeInTheDocument();
    expect(screen.getByText("RSI entered the first DCA band.")).toBeInTheDocument();
    expect(screen.getByText("Missing Rsi")).toBeInTheDocument();
  });

  it("exposes blocked ADD reason and gate breakdown from shadow history", async () => {
    await renderPage();

    expect(screen.getByRole("table", { name: "Shadow history" })).toBeInTheDocument();
    expect(screen.getByText("would_block")).toBeInTheDocument();
    expect(screen.getByText(/2 blocked/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Show blocked safety gates for SOLUSDT:USDT/i }));

    expect(screen.getByText("Why shadow ADD was blocked")).toBeInTheDocument();
    expect(screen.getByText("Blocked: confluence score is 8.5, below the required 10.")).toBeInTheDocument();
    expect(screen.getByText(/Simulated ADD would exceed the configured exposure cap/)).toBeInTheDocument();
    expect(screen.getByText("Passed gates")).toBeInTheDocument();
  });
});
