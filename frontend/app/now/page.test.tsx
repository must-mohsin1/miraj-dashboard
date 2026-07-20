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
});
