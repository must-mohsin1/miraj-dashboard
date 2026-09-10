import { act, render, screen } from "@testing-library/react";

import { DeskAutoRefresh } from "./desk-auto-refresh";

const refresh = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

describe("DeskAutoRefresh", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    refresh.mockClear();
  });

  afterEach(() => jest.useRealTimers());

  it("makes the hourly collector cadence explicit and refreshes the server desk every minute", () => {
    render(<DeskAutoRefresh lastRefreshedAt="2026-09-10T04:05:00Z" />);

    expect(screen.getByText("Last refreshed: 2026-09-10T04:05:00Z")).toBeInTheDocument();
    expect(screen.getByText("Collector runs hourly; this desk checks for the latest report every minute.")).toBeInTheDocument();

    act(() => jest.advanceTimersByTime(60_000));

    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
