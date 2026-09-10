import { render, screen } from "@testing-library/react";

jest.mock("@/lib/auth", () => ({ getAccessToken: jest.fn().mockResolvedValue("desk-token") }));
jest.mock("@/lib/collector-reports-api", () => ({ fetchLatestCollectorReport: jest.fn() }));
jest.mock("next/navigation", () => ({ useRouter: () => ({ refresh: jest.fn() }) }));

import { fetchLatestCollectorReport } from "@/lib/collector-reports-api";

const mockedFetch = jest.mocked(fetchLatestCollectorReport);

describe("Collector Decision Desk page", () => {
  beforeEach(() => jest.clearAllMocks());

  it("loads the protected SOLUSDT collector boundary and degrades honestly when it is unavailable", async () => {
    mockedFetch.mockRejectedValueOnce(new Error("endpoint not deployed"));
    const DeskPage = (await import("./page")).default;

    render(await DeskPage());

    expect(mockedFetch).toHaveBeenCalledWith("SOLUSDT", "desk-token");
    expect(screen.getByRole("heading", { name: "Desk unavailable." })).toBeInTheDocument();
    expect(screen.getByText(/No validated collector report is available/)).toBeInTheDocument();
  });
});
