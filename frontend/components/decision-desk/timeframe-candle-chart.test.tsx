import { render, screen } from "@testing-library/react";
import { createChart } from "lightweight-charts";

import { TimeframeCandleChart } from "./timeframe-candle-chart";

jest.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "Solid" },
  LineStyle: { Dashed: 2 },
  createChart: jest.fn(),
}), { virtual: true });

const setData = jest.fn();
const createPriceLine = jest.fn();
const remove = jest.fn();

beforeEach(() => {
  jest.mocked(createChart).mockClear();
  jest.mocked(createChart).mockReturnValue({
    addSeries: jest.fn(() => ({ setData, createPriceLine })),
    timeScale: () => ({ fitContent: jest.fn() }),
    applyOptions: jest.fn(),
    remove,
  } as never);
  setData.mockClear();
  createPriceLine.mockClear();
  remove.mockClear();
});

describe("TimeframeCandleChart", () => {
  it("renders only supplied completed candles and supplied FVG/OTE overlays", () => {
    render(
      <TimeframeCandleChart
        timeframe="4h"
        candles={[
          { time: "2026-09-10T00:00:00Z", open: 141, high: 143, low: 140, close: 142.35, volume: 3200 },
          { time: "2026-09-10T04:00:00Z", open: 142.35, high: 145, low: 142, close: 144, volume: 4100 },
        ]}
        fvg={{ low: 140.2, high: 141.1 }}
        ote={{ low: 139.8, high: 141.6 }}
      />,
    );

    expect(screen.getByRole("img", { name: "4h completed candle chart" })).toBeInTheDocument();
    expect(setData).toHaveBeenCalledWith([
      { time: 1788998400, open: 141, high: 143, low: 140, close: 142.35 },
      { time: 1789012800, open: 142.35, high: 145, low: 142, close: 144 },
    ]);
    expect(createPriceLine).toHaveBeenCalledTimes(4);
    expect(screen.getByText("FVG 140.20–141.10")).toBeInTheDocument();
    expect(screen.getByText("OTE 139.80–141.60")).toBeInTheDocument();
  });

  it("has a safe no-data state and does not create a chart", () => {
    render(<TimeframeCandleChart timeframe="1h" candles={[]} />);

    expect(screen.getByText("No completed candle evidence was supplied for 1h.")).toBeInTheDocument();
    expect(createChart).not.toHaveBeenCalled();
  });
});
