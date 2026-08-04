import { render, screen } from "@testing-library/react";
import { CapitalFlowTable } from "@/components/portfolio/capital-flow-table";
import type { CapitalFlowEntry, SyncCoverageItem } from "@/lib/types";

const entries: CapitalFlowEntry[] = [
  {
    id: 1,
    entry_type: "deposit",
    asset: "USDT",
    amount: 100,
    signed_amount: 100,
    status: "ok",
    occurred_at: "2026-08-01T12:00:00Z",
    synced_at: "2026-08-04T12:00:00Z",
  },
  {
    id: 2,
    entry_type: "funding",
    asset: "USDT",
    amount: 1.25,
    signed_amount: -1.25,
    status: null,
    occurred_at: "2026-08-02T12:00:00Z",
    synced_at: "2026-08-04T12:00:00Z",
  },
];

const partialSync: SyncCoverageItem[] = [
  {
    stream: "funding",
    status: "partial",
    complete: false,
    reason: "exchange_boundary_before_source_total",
    rows_fetched_total: 2,
    source_total: 10,
  },
];

const unavailableSync: SyncCoverageItem[] = [
  {
    stream: "deposits",
    status: "unavailable",
    complete: false,
    reason: "stream_not_supported",
    rows_fetched_total: 0,
    source_total: 0,
  },
];

const errorSync: SyncCoverageItem[] = [
  {
    stream: "withdrawals",
    status: "error",
    complete: false,
    reason: "rate_limit",
    rows_fetched_total: 0,
    source_total: 0,
  },
];

const staleSync: SyncCoverageItem[] = [
  {
    stream: "funding",
    status: "stale",
    complete: false,
    reason: "no_sync_state",
    rows_fetched_total: 0,
    source_total: 0,
  },
];

describe("CapitalFlowTable", () => {
  it("renders entries with signed amount formatting and type badges", () => {
    render(<CapitalFlowTable entries={entries} sync={[]} />);
    expect(screen.getByText("Deposit")).toBeInTheDocument();
    expect(screen.getByText("Funding")).toBeInTheDocument();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
    expect(screen.getByText(/\+100/)).toBeInTheDocument();
    expect(screen.getByText(/-1\.25/)).toBeInTheDocument();
  });

  it("shows truncated-boundary banner when a stream is partial", () => {
    render(<CapitalFlowTable entries={entries} sync={partialSync} partial />);
    expect(screen.getByText(/history truncated at exchange boundary/i)).toBeInTheDocument();
  });

  it("shows stream-unavailable banner for unavailable capital streams", () => {
    render(<CapitalFlowTable entries={entries} sync={unavailableSync} />);
    expect(screen.getByText(/capital-flow stream unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/history truncated at exchange boundary/i)).not.toBeInTheDocument();
  });

  it("shows sync-error banner for error capital streams", () => {
    render(<CapitalFlowTable entries={entries} sync={errorSync} />);
    expect(screen.getByText(/capital-flow sync error/i)).toBeInTheDocument();
  });

  it("shows not-yet-synchronized banner when partial is true with only stale/no_sync_state", () => {
    render(<CapitalFlowTable entries={entries} sync={staleSync} partial />);
    expect(screen.getByText(/not yet synchronized/i)).toBeInTheDocument();
    expect(screen.queryByText(/history truncated at exchange boundary/i)).not.toBeInTheDocument();
  });

  it("does not show coverage banner for pure stale/no_sync_state without partial", () => {
    render(<CapitalFlowTable entries={entries} sync={staleSync} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("uses INK & OXIDE tokens not slate/indigo", () => {
    const { container } = render(<CapitalFlowTable entries={entries} sync={partialSync} />);
    expect(container.innerHTML).toContain("#161411");
    expect(container.innerHTML).toContain("#2A2620");
    expect(container.innerHTML).not.toMatch(/(?:slate|indigo)-/);
  });
});
