import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  clampTradeExplorerPageSize,
  TradeExplorer,
  type TradeExplorerResponse,
} from "@/components/portfolio/trade-explorer";

const BASE_RESPONSE: TradeExplorerResponse = {
  exchange: "mexc",
  filters_applied: { timezone: "UTC", symbols: ["BTC_USDT"] },
  sort: "-close_time",
  limit: 50,
  offset: 50,
  total: 125,
  has_more: true,
  basis: {
    pnl_source: "PositionHistory.pnl",
    pnl_basis: "MEXC-reported closed-position PnL",
    currency_unit: "USDT",
    fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
    size_unit: "contracts",
  },
  history: {
    history_scope: "stored_closed_positions",
    history_completeness: "unknown",
    reason: "full_history_sync_not_implemented_phase2",
    row_count: 125,
    first_close_time: "2026-07-23T10:00:00Z",
    last_close_time: "2026-07-24T12:00:00Z",
  },
  excluded_reasons: { missing_duration: 2 },
  items: [
    {
      id: 911,
      symbol: "BTC_USDT",
      side: "long",
      size: 12,
      size_unit: "contracts",
      contract_size: 0.001,
      entry_price: 118000.25,
      exit_price: 118401.5,
      pnl: 1.05,
      pnl_basis: "MEXC-reported closed-position PnL",
      currency_unit: "USDT",
      fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
      pnl_percent: 0.89,
      leverage: 20,
      open_time: "2026-07-24T10:00:00Z",
      close_time: "2026-07-24T12:00:00Z",
      duration_minutes: 120,
      close_reason: "manual",
      unavailable_reasons: ["fee_net_pnl_unavailable_phase2_ledger_required"],
    },
    {
      id: 912,
      symbol: "ETH_USDT",
      side: "short",
      size: 3,
      contract_size: null,
      entry_price: 3800,
      exit_price: 3825,
      pnl: -1.17,
      pnl_basis: "MEXC-reported closed-position PnL",
      currency_unit: "USDT",
      fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
      pnl_percent: -0.31,
      leverage: null,
      open_time: null,
      close_time: "2026-07-24T11:00:00Z",
      duration_minutes: null,
      close_reason: null,
      unavailable_reasons: { missing_leverage: true, missing_duration: true },
    },
  ],
};

describe("TradeExplorer", () => {
  it("renders server pagination metadata, deterministic sort indicators, and accessible pagination controls", async () => {
    const user = userEvent.setup();
    const onPageChange = jest.fn();
    const onPageSizeChange = jest.fn();

    render(<TradeExplorer data={BASE_RESPONSE} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />);

    expect(screen.getByText(/Server-paginated closed positions/)).toHaveTextContent(
      "Showing 51–100 of 125; limit 50, offset 50, has_more true",
    );
    expect(screen.getByText(/Sort:/)).toHaveTextContent("Close time descending");
    expect(screen.getByRole("columnheader", { name: /Close time.*descending/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("columnheader", { name: /PnL.*not sorted/ })).toHaveAttribute("aria-sort", "none");

    await user.click(screen.getByRole("button", { name: "Go to previous Trade Explorer page" }));
    expect(onPageChange).toHaveBeenCalledWith(0);

    await user.click(screen.getByRole("button", { name: "Go to next Trade Explorer page" }));
    expect(onPageChange).toHaveBeenCalledWith(100);

    await user.selectOptions(screen.getByLabelText("Trade Explorer page size"), "200");
    expect(onPageSizeChange).toHaveBeenCalledWith(200);
  });

  it("shows the 200 page-size cap behavior visibly and clamps oversize input", () => {
    render(<TradeExplorer data={{ ...BASE_RESPONSE, limit: 500, offset: 0, total: 250, has_more: true }} />);

    expect(clampTradeExplorerPageSize(500)).toBe(200);
    expect(screen.getByText(/Page size cap:/)).toHaveTextContent("200 max — cap reached");
    expect(screen.getByLabelText("Trade Explorer page size")).toHaveValue("200");
  });

  it("renders row/card fields with USDT, basis labels, fee status, and unknown history copy without history_complete", () => {
    const { container } = render(<TradeExplorer data={BASE_RESPONSE} />);

    expect(screen.getAllByText("BTC_USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ID 911").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/12 contracts/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("118000.25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("118401.5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+$1.05 USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MEXC-reported closed-position PnL").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/fee net pnl unavailable phase2 ledger required/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Profit 0.89%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("20x").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Open/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("2.0 hr").length).toBeGreaterThan(0);
    expect(screen.getAllByText("manual").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Unavailable: fee net pnl unavailable phase2 ledger required/).length).toBeGreaterThan(0);
    expect(screen.getByText(/History scope: stored closed positions/)).toBeInTheDocument();
    expect(screen.getByText(/Completeness: unknown/)).toBeInTheDocument();
    expect(screen.getByText(/Full history sync not implemented until Phase 2/)).toBeInTheDocument();
    expect(container).not.toHaveTextContent("history_complete");
  });

  it("renders unknown/unavailable row copy for missing duration and leverage", () => {
    render(<TradeExplorer data={BASE_RESPONSE} />);

    const ethCard = screen.getByLabelText("Trade Explorer row 912");
    expect(within(ethCard).getByText(/Short/)).toBeInTheDocument();
    expect(within(ethCard).getByText(/−\$1\.17 USDT/)).toBeInTheDocument();
    expect(within(ethCard).getByText(/Loss -0.31%/)).toBeInTheDocument();
    expect(screen.getAllByText(/Unavailable: missing leverage/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Unavailable: missing duration/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Trade Explorer basis and history")).toHaveTextContent("2 rows excluded for missing duration");
  });

  it("does not rely on color-only PnL state", () => {
    render(<TradeExplorer data={BASE_RESPONSE} />);

    expect(screen.getAllByText("Profit").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Loss").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+$1.05 USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("−$1.17 USDT").length).toBeGreaterThan(0);
  });

  it("makes the desktop horizontal scroll table region keyboard-focusable with a clear name", async () => {
    const user = userEvent.setup();
    render(<TradeExplorer data={BASE_RESPONSE} />);

    const scrollRegion = screen.getByRole("region", { name: "Scrollable Trade Explorer closed positions table" });
    expect(scrollRegion).toHaveClass("overflow-x-auto");
    expect(scrollRegion).toHaveAttribute("tabIndex", "0");
    expect(within(scrollRegion).getByRole("table", { name: /Server-paginated Trade Explorer rows/ })).toBeInTheDocument();

    await user.tab();
    expect(screen.getByRole("button", { name: "Export current Trade Explorer page as CSV" })).toHaveFocus();

    await user.tab();
    expect(screen.getByLabelText("Trade Explorer page size")).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "Go to previous Trade Explorer page" })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "Go to next Trade Explorer page" })).toHaveFocus();

    // Mobile card actions render in DOM before the desktop scroll region.
    await user.tab();
    expect(screen.getAllByRole("button", { name: /Open trade detail for BTC_USDT ID 911/ })[0]).toHaveFocus();
  });

  it("exports current page CSV control and opens trade detail drawer from a row", async () => {
    const user = userEvent.setup();
    const createObjectURL = jest.fn(() => "blob:trade-csv");
    const revokeObjectURL = jest.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<TradeExplorer data={BASE_RESPONSE} />);

    expect(screen.getByRole("button", { name: "Export current Trade Explorer page as CSV" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Export current Trade Explorer page as CSV" }));
    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:trade-csv");

    const openers = screen.getAllByRole("button", { name: /Open trade detail for BTC_USDT ID 911/ });
    await user.click(openers[0]);
    expect(screen.getByRole("heading", { name: "BTC_USDT" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open journal for BTC_USDT/ })).toHaveAttribute(
      "href",
      "/journal?symbol=BTC_USDT&exchange=mexc",
    );

    clickSpy.mockRestore();
  });

  it("invokes onSortChange when a sortable column header is activated", async () => {
    const user = userEvent.setup();
    const onSortChange = jest.fn();
    render(<TradeExplorer data={BASE_RESPONSE} onSortChange={onSortChange} />);

    await user.click(screen.getByRole("button", { name: /Sort by PnL/ }));
    expect(onSortChange).toHaveBeenCalledWith("-pnl");
  });

  it("loads trade detail with orders and scan when drawer opens", async () => {
    const user = userEvent.setup();
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        exchange: "mexc",
        position: BASE_RESPONSE.items[0],
        orders: [
          {
            id: 1,
            exchange_order_id: "ord-1",
            side: "buy",
            type: "market",
            filled: 12,
            filled_price: 118000,
            fee: 0.02,
            fee_currency: "USDT",
            timestamp: "2026-07-24T10:01:00Z",
            side_action: "Open Long",
          },
        ],
        orders_match: {
          strategy: "symbol_time_window",
          count: 1,
          note: "Matched by symbol and time window.",
        },
        scan: {
          found: true,
          scan_symbol: "BTC-USD",
          score: 22.5,
          direction: "LONG",
          href_path: "/analysis/BTC-USD",
          created_at: "2026-07-24T09:00:00Z",
        },
        journal: { count: 0, entries: [], href_path: "/journal?symbol=BTC_USDT&exchange=mexc" },
        fees: { sum_order_fees: 0.02, currency_unit: "USDT" },
      }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<TradeExplorer data={BASE_RESPONSE} token="test-token" exchange="mexc" />);
    const openers = screen.getAllByRole("button", { name: /Open trade detail for BTC_USDT ID 911/ });
    await user.click(openers[0]);

    expect(await screen.findByRole("heading", { name: "Pre-entry scan" })).toBeInTheDocument();
    expect(await screen.findByText(/Score/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open scan \(BTC-USD\)/ })).toHaveAttribute(
      "href",
      "/analysis/BTC-USD",
    );
    expect(screen.getByLabelText("Matched orders")).toHaveTextContent("Open Long");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/analytics/mexc/trade-explorer/911",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer test-token" }),
      }),
    );
  });

  it("uses the approved closed-position analytics error copy without raw status text", () => {
    render(<TradeExplorer data={null} error="raw 503" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Closed-position analytics could not load. No exchange action was taken. Try again.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("raw 503");
    expect(screen.getByRole("alert")).not.toHaveTextContent("Trade Explorer unavailable");
  });

  it("keeps the mobile card layout available for a 390px viewport without page-overflow-only tables", () => {
    const { container } = render(<TradeExplorer data={BASE_RESPONSE} />);

    expect(container.querySelector(".sm\\:hidden")).toBeTruthy();
    expect(screen.getByLabelText("Trade Explorer row 911")).toHaveClass("min-w-0");
    expect(container.querySelector(".overflow-x-auto")).toBeTruthy();
  });
});
