import { render, screen } from "@testing-library/react";

jest.mock("@/lib/auth", () => ({
  getAccessToken: jest.fn().mockResolvedValue("test-token"),
}));

jest.mock("@/lib/api", () => ({
  serverFetch: jest.fn(),
}));

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";

const mockedGetAccessToken = jest.mocked(getAccessToken);
const mockedServerFetch = jest.mocked(serverFetch);

describe("Decision Desk Now page", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetAccessToken.mockResolvedValue("test-token");
  });

  it("shows an honest unavailable state when the read-only desk endpoint cannot be loaded", async () => {
    mockedServerFetch.mockRejectedValueOnce(new Error("backend unavailable"));
    const NowPage = (await import("./page")).default;

    render(await NowPage());

    expect(mockedGetAccessToken).toHaveBeenCalledTimes(1);
    expect(mockedServerFetch).toHaveBeenCalledWith(
      "/api/v1/decision-desk/now",
      "test-token"
    );
    expect(screen.getByRole("heading", { name: "Decision Desk" })).toBeInTheDocument();
    expect(
      screen.getByText("Decision Desk data is currently unavailable.")
    ).toBeInTheDocument();
    expect(screen.getByText(/Manual review and execution only/)).toBeInTheDocument();
  });

  it("renders notification and authenticated account evidence from the now contract", async () => {
    mockedServerFetch.mockResolvedValueOnce({
      generated_at: "2026-07-20T14:30:00Z",
      watchlist: [],
      signals: [],
      notification_channels: [],
      notification_outbox: [
        {
          pair: "BTC_USDT",
          direction: "LONG",
          signal_state: "ACTIONABLE",
          channel_type: "discord",
          status: "sent",
          attempts: 1,
          created_at: "2026-07-20T14:29:00Z",
          next_attempt_at: null,
          sent_at: "2026-07-20T14:29:00Z",
          error: null,
        },
      ],
      account_reconciliation: [{
        exchange: "mexc",
        freshness: "stale",
        last_reconciled_at: "2026-07-20T14:00:00Z",
        positions: [{ symbol: "BTC_USDT", side: "long", size: 1 }],
      }],
    });
    const NowPage = (await import("./page")).default;

    render(await NowPage());

    expect(screen.getByText("Sent at: 2026-07-20T14:29:00Z")).toBeInTheDocument();
    expect(screen.getByText("Account truth stale.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Journal BTC_USDT position" })).toHaveAttribute(
      "href",
      "/journal?exchange=mexc&symbol=BTC_USDT"
    );
  });
});
