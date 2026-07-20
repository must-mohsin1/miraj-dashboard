import { render, screen } from "@testing-library/react";

import { PositionDesk } from "@/components/portfolio/position-desk";
import type { PositionDeskResponse, PositionDeskRow } from "@/lib/types";

const ROW: PositionDeskRow = {
  symbol: "HYPE_USDT",
  scan_symbol: "HYPE-USD",
  side: "long",
  size: 10,
  entry_price: 70,
  mark_price: 62,
  pnl: -80,
  pnl_percent: -11.4,
  leverage: 3,
  liquidation_price: 40,
  liq_distance_pct: 35.48,
  verdict: null,
  regime: "bear",
  regime_band_low: 52.67,
  regime_band_high: 54.23,
  alignment: "COUNTER_REGIME",
  recommendation: "REDUCE",
  confidence: "HIGH",
  ruling: "Reduce — wrong side of the weekly band.",
  detail: "Below BMSB (bear regime). Miraj: avoid longs below BMSB.",
  add_zone: null,
  next_entry: null,
  tp_levels: [],
  action_items: [],
  next_review: "next 4H candle close",
};

function mockDesk(response: PositionDeskResponse) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => response,
  }) as unknown as typeof fetch;
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("PositionDesk", () => {
  it("renders a ruling row per open position", async () => {
    mockDesk({ exchange: "mexc", total_positions: 1, positions: [ROW] });

    render(<PositionDesk token="token" exchange="mexc" />);

    expect(
      await screen.findByText("Reduce — wrong side of the weekly band.")
    ).toBeInTheDocument();
    expect(screen.getByText("HYPE_USDT")).toBeInTheDocument();
    expect(screen.getByText("REDUCE")).toBeInTheDocument();
    expect(screen.getByText("Counter-regime")).toBeInTheDocument();
    expect(screen.getByText("-11.40%")).toBeInTheDocument();
    expect(screen.getByText("52.67–54.23")).toBeInTheDocument();
  });

  it("shows the empty state when there are no open positions", async () => {
    mockDesk({ exchange: "mexc", total_positions: 0, positions: [] });

    render(<PositionDesk token="token" exchange="mexc" />);

    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
  });

  it("shows an unavailable state when the request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
    }) as unknown as typeof fetch;

    render(<PositionDesk token="token" exchange="mexc" />);

    expect(
      await screen.findByText(/Position desk unavailable/)
    ).toBeInTheDocument();
  });
});
