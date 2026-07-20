import { render, screen } from "@testing-library/react";

import { DecisionDesk } from "./decision-desk";

describe("DecisionDesk", () => {
  it("renders honest unavailable and empty states without inventing market data", () => {
    render(<DecisionDesk />);

    expect(screen.getByRole("heading", { name: "Market Regime" })).toBeInTheDocument();
    expect(screen.getByText("Market regime unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Confirmed Setups" })).toBeInTheDocument();
    expect(screen.getByText("No confirmed setups at this time.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Watch / Research-only" })).toBeInTheDocument();
    expect(screen.getByText("No watch or research-only items supplied.")).toBeInTheDocument();
    expect(screen.getByText(/Manual review and execution only/)).toBeInTheDocument();
  });

  it("renders supplied advisory summaries and confirmed setup labels", () => {
    render(
      <DecisionDesk
        marketRegime="Range-bound; confirmation pending."
        confirmedSetups={["BTCUSDT — breakout retest confirmed"]}
        watchSummary="ETHUSDT is research-only until a higher-timeframe review is complete."
      />
    );

    expect(screen.getByText("Range-bound; confirmation pending.")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT — breakout retest confirmed")).toBeInTheDocument();
    expect(
      screen.getByText("ETHUSDT is research-only until a higher-timeframe review is complete.")
    ).toBeInTheDocument();
  });

  it("renders the supplied last-updated timestamp", () => {
    render(<DecisionDesk lastUpdated="2026-07-17T14:30:00Z" />);

    expect(screen.getByText("Last updated: 2026-07-17T14:30:00Z")).toBeInTheDocument();
  });

  it("separates realtime lifecycle records from research-only pairs", () => {
    render(
      <DecisionDesk
        realtimePairCount={2}
        researchOnlyPairs={["SNDK-USD"]}
        signals={[
          {
            pair: "BTC-USD",
            direction: "LONG",
            state: "ACTIONABLE",
            missingGates: [],
            updatedAt: "2026-07-17T14:30:00Z",
          },
          {
            pair: "BASE-USD",
            direction: "SHORT",
            state: "WATCH",
            missingGates: ["volume confirmation"],
            updatedAt: "2026-07-17T14:29:00Z",
          },
          {
            pair: "ETH-USD",
            direction: "LONG",
            state: "INVALIDATED",
            missingGates: [],
            updatedAt: "2026-07-17T14:28:00Z",
          },
        ]}
      />
    );

    expect(screen.getByText("2 MEXC realtime pairs")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Actionable" })).toBeInTheDocument();
    expect(screen.getByText("BTC-USD — LONG")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Watch / Ready" })).toBeInTheDocument();
    expect(screen.getByText(/Missing: volume confirmation/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Invalidated / Stale" })).toBeInTheDocument();
    expect(screen.getByText("ETH-USD — LONG")).toBeInTheDocument();
    expect(screen.getByText("SNDK-USD")).toBeInTheDocument();
  });
});
