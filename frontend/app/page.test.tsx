import { render, screen, act } from "@testing-library/react";

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
import Home from "./page";

// Helper: render an async Server Component and wait for it to flush.
async function renderAsync(ui: React.ReactElement) {
  await act(async () => {
    render(ui);
  });
}

describe("Home page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders the welcome heading and fetches macro data", async () => {
    await renderAsync(<Home />);

    expect(
      screen.getByRole("heading", { name: /Crypto Analysis Dashboard/i })
    ).toBeInTheDocument();
    // The token was used to call the macro endpoint.
    expect(getAccessToken).toHaveBeenCalledTimes(1);
    expect(serverFetch).toHaveBeenCalledWith("/api/v1/macro", "test-token");
  });

  it("renders the macro cards with values", async () => {
    await renderAsync(<Home />);

    expect(screen.getByText(/52\.34%/)).toBeInTheDocument();
    expect(screen.getByText(/4\.21%/)).toBeInTheDocument();
    expect(screen.getByText(/Fear/)).toBeInTheDocument();
    expect(screen.getByText(/1\.200/)).toBeInTheDocument();
    expect(screen.getByText("BTC Dominance")).toBeInTheDocument();
    expect(screen.getByText("USDT Dominance")).toBeInTheDocument();
    expect(screen.getByText("Long / Short Ratio")).toBeInTheDocument();
  });

  it("renders quick action links pointing to /macro and /scanner", async () => {
    await renderAsync(<Home />);

    expect(
      screen.getByRole("link", { name: /Open Macro Dashboard/i })
    ).toHaveAttribute("href", "/macro");
    expect(
      screen.getByRole("link", { name: /Scan a Pair/i })
    ).toHaveAttribute("href", "/scanner");
  });
});
