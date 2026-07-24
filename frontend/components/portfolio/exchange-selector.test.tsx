import { render, screen, waitFor } from "@testing-library/react";

import { ExchangeSelector } from "@/components/portfolio/exchange-selector";

const push = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams("exchange=mexc"),
}));

afterEach(() => {
  jest.restoreAllMocks();
  push.mockClear();
});

describe("ExchangeSelector authenticated requests", () => {
  it("waits for the client token before fetching exchanges and sends the bearer header", async () => {
    let resolveSession: (value: unknown) => void = () => {};
    const sessionPromise = new Promise((resolve) => {
      resolveSession = resolve;
    });
    const fetchMock = jest.fn((url: RequestInfo | URL) => {
      const path = String(url);
      if (path === "/api/auth/session") {
        return sessionPromise as Promise<Response>;
      }
      if (path === "/api/v1/portfolio/exchanges") {
        return Promise.resolve({
          ok: true,
          json: async () => ({ exchanges: ["mexc", "binance"] }),
        });
      }
      if (path.includes("/api/v1/portfolio/") && path.endsWith("/keys")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ connected: path.includes("mexc"), masked_key: "***" }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<ExchangeSelector value="mexc" />);

    expect(screen.getByRole("radiogroup", { name: "Select exchange" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session");
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/v1/portfolio/exchanges",
      expect.anything(),
    );

    resolveSession({ json: async () => ({ user: { accessToken: "client-token" } }) });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/portfolio/exchanges",
        expect.objectContaining({
          headers: { Authorization: "Bearer client-token" },
        }),
      );
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/portfolio/mexc/keys",
        expect.objectContaining({
          headers: { Authorization: "Bearer client-token" },
        }),
      );
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/portfolio/binance/keys",
        expect.objectContaining({
          headers: { Authorization: "Bearer client-token" },
        }),
      );
    });
  });
});
