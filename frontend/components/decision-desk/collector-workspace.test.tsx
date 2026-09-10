import { render, screen } from "@testing-library/react";

jest.mock("./timeframe-candle-chart", () => ({ TimeframeCandleChart: () => <div /> }));
jest.mock("./desk-auto-refresh", () => ({ DeskAutoRefresh: () => <p>Collector runs hourly; this desk checks for the latest report every minute.</p> }));

import { CollectorWorkspace } from "./collector-workspace";
import type { LatestCollectorReportResponse } from "@/lib/collector-report-types";

const report: LatestCollectorReportResponse = {
  status: "validated",
  stale: false,
  received_at: "2026-09-10T04:05:00Z",
  report: {
    report_id: "solusdt-20260910-040000",
    payload_sha256: "a".repeat(64),
    generated_at: "2026-09-10T04:00:00Z",
    symbol: "SOLUSDT",
    venue: "mexc_spot",
    source: "hourly_collector",
    schema_version: "1.0",
    verdict: {
      state: "NO_TRADE",
      summary: "No trade today.",
      gates: [
        { label: "HTF alignment", state: "blocked", reason: "Daily trend is mixed." },
        { label: "Volume confirmation", state: "passed", reason: "Completed 4h candle cleared threshold." },
      ],
    },
    quote: { price: 142.35, as_of: "2026-09-10T04:00:00Z", context_only: true },
    scores: [{ label: "Trend", value: 52, maximum: 100, detail: "Mixed higher timeframe." }],
    timeframes: [{ timeframe: "4h", state: "mixed", close: 142.35, as_of: "2026-09-10T04:00:00Z", candles: [{ time: "2026-09-10T00:00:00Z", open: 141, high: 143, low: 140, close: 142.35, volume: 3200 }], fvg: { low: 140.2, high: 141.1 }, ote: { low: 139.8, high: 141.6 } }],
    source_health: [{ source: "mexc_spot_4h", status: "ok", checked_at: "2026-09-10T04:00:00Z", fallback: false }],
    limitations: ["Public market data only."],
    setup_states: [
      { state: "S0", status: "passed", label: "Public data collection", reason: "Collection completed." },
      { state: "S1", status: "passed", label: "Setup gate S1", reason: "Higher timeframe aligned." },
      { state: "S2", status: "blocked", label: "Setup gate S2", reason: "Liquidity confirmation missing." },
      { state: "S3", status: "pending", label: "Setup gate S3", reason: "Waiting for retracement." },
      { state: "S4", status: "unavailable", label: "Setup gate S4", reason: "No entry trigger supplied." },
      { state: "S5", status: "pending", label: "Setup gate S5", reason: "Risk review pending." },
    ],
  },
};

describe("CollectorWorkspace", () => {
  it("renders only collector-backed decision evidence and marks the quote as context", () => {
    render(<CollectorWorkspace response={report} />);

    expect(screen.getByRole("heading", { name: "No trade today." })).toBeInTheDocument();
    expect(screen.getByText("SOLUSDT")).toBeInTheDocument();
    expect(screen.getAllByText("142.35").length).toBeGreaterThan(0);
    expect(screen.getByText("Context only — excluded from gate confirmation.")).toBeInTheDocument();
    expect(screen.getByText("Collector runs hourly; this desk checks for the latest report every minute.")).toBeInTheDocument();
    for (const state of ["S0", "S1", "S2", "S3", "S4", "S5"]) {
      expect(screen.getByText(state)).toBeInTheDocument();
    }
    expect(screen.getByText("Liquidity confirmation missing.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Confluence" })).toBeInTheDocument();
    expect(screen.getByText("FVG 140.20–141.10")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Source health" })).toBeInTheDocument();
    expect(screen.getByText("mexc_spot_4h")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open audit record" })).toBeInTheDocument();
  });

  it("does not turn an unavailable or stale endpoint into a trading verdict", () => {
    const { rerender } = render(<CollectorWorkspace response={{ status: "unavailable", stale: true, received_at: null, report: null }} />);
    expect(screen.getByRole("heading", { name: "Desk unavailable." })).toBeInTheDocument();
    expect(screen.getByText(/No validated collector report is available/)).toBeInTheDocument();

    rerender(<CollectorWorkspace response={{ ...report, status: "stale", stale: true }} />);
    expect(screen.getByText("Stale report")).toBeInTheDocument();
    expect(screen.getByText(/Evidence is retained for review, not confirmation/)).toBeInTheDocument();
  });
});
