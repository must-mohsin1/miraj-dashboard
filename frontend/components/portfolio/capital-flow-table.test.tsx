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

describe("CapitalFlowTable", () => {
  it("renders entries with signed amount formatting and type badges", () => {
    render(<CapitalFlowTable entries={entries} sync={[]} />);
    expect(screen.getByText("Deposit")).toBeInTheDocument();
    expect(screen.getByText("Funding")).toBeInTheDocument();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
    expect(screen.getByText(/\+100/)).toBeInTheDocument();
    expect(screen.getByText(/-1\.25/)).toBeInTheDocument();
  });

  it("shows coverage banner when a stream is partial or unavailable", () => {
    render(<CapitalFlowTable entries={entries} sync={partialSync} partial />);
    expect(screen.getByText(/history truncated at exchange boundary/i)).toBeInTheDocument();
  });

  it("uses INK & OXIDE tokens not slate/indigo", () => {
    const { container } = render(<CapitalFlowTable entries={entries} sync={partialSync} />);
    expect(container.innerHTML).toContain("#161411");
    expect(container.innerHTML).toContain("#2A2620");
    expect(container.innerHTML).not.toMatch(/(?:slate|indigo)-/);
  });
});
