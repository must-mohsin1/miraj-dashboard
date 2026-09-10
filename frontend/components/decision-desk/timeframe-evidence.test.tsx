import { render, screen } from "@testing-library/react";

import { TimeframeEvidence } from "./timeframe-evidence";

jest.mock("./timeframe-candle-chart", () => ({
  TimeframeCandleChart: ({ timeframe }: { timeframe: string }) => <div role="img" aria-label={`${timeframe} completed candle chart`} />,
}));

describe("TimeframeEvidence", () => {
  it("shows the selected timeframe's completed candle chart", () => {
    render(<TimeframeEvidence timeframes={[{ timeframe: "4h", state: "mixed", close: 142.35, as_of: "2026-09-10T04:00:00Z", candles: [{ time: "2026-09-10T00:00:00Z", open: 141, high: 143, low: 140, close: 142.35 }] }]} />);

    expect(screen.getByRole("img", { name: "4h completed candle chart" })).toBeInTheDocument();
  });
});
