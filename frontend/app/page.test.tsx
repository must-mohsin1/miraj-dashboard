import { render, screen } from "@testing-library/react";

// Mock the auth helper so the page renders without a real session.
jest.mock("@/lib/auth", () => ({
  getAccessToken: jest.fn().mockResolvedValue("test-token"),
}));

// Mock serverFetch so no real network call is made.
jest.mock("@/lib/api", () => ({
  serverFetch: jest.fn().mockResolvedValue({
    data: {
      btc_dominance: 52.34,
      usdt_dominance: 4.21,
      dxy: 104.5,
      dxy_error: null,
      fear_greed_index: 45,
      fear_greed_label: "Fear",
      binance_ls_ratio: 1.2,
      regime: "mixed",
    },
    cached_at: "2026-01-01T00:00:00Z",
    stale: false,
    errors: null,
  }),
}));

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import { HomeView } from "@/components/home-view";
import type { MacroResponse } from "@/lib/types";

const mockMacro: MacroResponse = {
  data: {
    btc_dominance: 52.34,
    usdt_dominance: 4.21,
    dxy: 104.5,
    dxy_error: null,
    fear_greed_index: 45,
    fear_greed_label: "Fear",
    binance_ls_ratio: 1.2,
    regime: "mixed",
  },
  cached_at: "2026-01-01T00:00:00Z",
  stale: false,
  errors: null,
};

describe("HomeView (home page layout)", () => {
  it("renders the welcome heading", () => {
    render(<HomeView macro={mockMacro} />);
    expect(
      screen.getByRole("heading", { name: /Crypto Analysis Dashboard/i })
    ).toBeInTheDocument();
  });

  it("renders the macro cards with values", () => {
    const { container } = render(<HomeView macro={mockMacro} />);
    expect(screen.getByText(/52\.34%/)).toBeInTheDocument();
    expect(screen.getByText(/4\.21%/)).toBeInTheDocument();
    expect(screen.getByText("Fear")).toBeInTheDocument();
    expect(screen.getByText(/1\.200/)).toBeInTheDocument();
    expect(container).toHaveTextContent("BTC Dominance");
    expect(container).toHaveTextContent("USDT Dominance");
    expect(container).toHaveTextContent("Long / Short Ratio");
  });

  it("renders quick action links pointing to /macro and /scanner", () => {
    render(<HomeView macro={mockMacro} />);
    expect(
      screen.getByRole("link", { name: /Open Macro Dashboard/i })
    ).toHaveAttribute("href", "/macro");
    expect(
      screen.getByRole("link", { name: /Scan a Pair/i })
    ).toHaveAttribute("href", "/scanner");
  });

  it("renders placeholders when macro data is null", () => {
    render(<HomeView macro={null} />);
    // Each card shows an em-dash when its value is unavailable.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(4);
  });
});

describe("Home page (Server Component data fetch)", () => {
  it("getAccessToken and serverFetch are wired for the macro endpoint", async () => {
    // Dynamically import after mocks are installed so the async body runs.
    const Home = (await import("./page")).default;
    // React/jsdom cannot render an async Server Component, so we simply
    // invoke the factory and assert the mocked fetches were called with
    // the expected arguments. The rendered output is covered by the
    // HomeView tests above.
    await Home();
    expect(getAccessToken).toHaveBeenCalledTimes(1);
    expect(serverFetch).toHaveBeenCalledWith("/api/v1/macro", "test-token");
  });
});
