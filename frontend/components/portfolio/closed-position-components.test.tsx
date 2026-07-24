import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClosedPositionBreakdowns, type ClosedPositionBreakdownsData } from "@/components/portfolio/closed-position-breakdowns";
import { ClosedPositionCalendar, type ClosedPositionCalendarDay } from "@/components/portfolio/closed-position-calendar";
import {
  ClosedPositionFilters,
  DEFAULT_CLOSED_POSITION_FILTERS,
  clampClosedPositionPageSize,
  type ClosedPositionFiltersValue,
} from "@/components/portfolio/closed-position-filters";
import { formatUsdtMoney } from "@/components/portfolio/closed-position-formatters";
import { ClosedPositionOverview, type ClosedPositionOverviewData } from "@/components/portfolio/closed-position-overview";
import { ClosedPositionPeriodChart, type ClosedPositionPeriodItem } from "@/components/portfolio/closed-position-period-chart";

const FILTERS: ClosedPositionFiltersValue = {
  timezone: "UTC",
  from: "",
  to: "",
  symbols: "",
  side: "",
  leverage_min: "",
  leverage_max: "",
  duration_min_minutes: "",
  duration_max_minutes: "",
  close_reason: "",
  pnl_min: "",
  pnl_max: "",
  period: "week",
  limit: 50,
  offset: 0,
  sort: "-close_time",
};

const OVERVIEW: ClosedPositionOverviewData = {
  total_trades: 49,
  winning_trades: 48,
  losing_trades: 1,
  breakeven_trades: 0,
  total_pnl: 49.23,
  win_rate_pct: 97.96,
  average_win: 1.05,
  average_loss: -1.17,
  average_trade_pnl: 1,
  expectancy_per_trade: 1,
  profit_factor: 43.0769,
  payoff_ratio: 0.8974,
  active_days: 1,
  calendar_days: 2,
  average_pnl_per_active_day: 49.23,
  average_pnl_per_active_day_label: "per active trading day",
  average_pnl_per_calendar_day: 24.62,
  average_pnl_per_calendar_day_label: "per calendar day",
};

const BASIS = {
  pnl_source: "PositionHistory.pnl",
  pnl_basis: "MEXC-reported closed-position PnL",
  currency_unit: "USDT",
  fee_status: "fee_net_pnl_unavailable_phase2_ledger_required",
};

const HISTORY = {
  history_scope: "stored_closed_positions",
  history_completeness: "unknown",
  reason: "full_history_sync_not_implemented_phase2",
  row_count: 49,
};

const FILTERS_APPLIED = {
  timezone: "UTC",
  period: "week",
  symbols: ["BTC_USDT"],
  side: "long",
};

const PERIOD_ITEMS: ClosedPositionPeriodItem[] = [
  {
    label: "2026-W30",
    period_start: "2026-07-20T00:00:00+00:00",
    period_end: "2026-07-27T00:00:00+00:00",
    trade_count: 49,
    total_pnl: 49.23,
    basis: "MEXC-reported closed-position PnL",
    currency_unit: "USDT",
  },
];

const CALENDAR_DAYS: ClosedPositionCalendarDay[] = [
  {
    date: "2026-07-24",
    trade_count: 49,
    total_pnl: 49.23,
    basis: "MEXC-reported closed-position PnL",
    currency_unit: "USDT",
  },
];

const row = (key: string, totalPnl = 49.23) => ({
  key,
  trade_count: 49,
  total_pnl: totalPnl,
  gross_profit: 50.4,
  gross_loss_abs: 1.17,
  win_rate_pct: 97.96,
  average_pnl: 1,
  best_trade: 1.05,
  worst_trade: -1.17,
  basis: "MEXC-reported closed-position PnL",
  currency_unit: "USDT",
});

const BREAKDOWNS: ClosedPositionBreakdownsData = {
  symbol: [row("BTC_USDT")],
  side: [row("long")],
  duration: [row("unknown_duration", 2.1)],
  leverage: [row("unknown_leverage", 2.1)],
  pair_direction: [row("BTC_USDT_long")],
};

describe("Phase 1 closed-position components", () => {
  it("formats USDT adjacent to dollar-style money", () => {
    expect(formatUsdtMoney(49.23, { dollarStyle: true })).toBe("$49.23 USDT");
    expect(formatUsdtMoney(-1.17, { signed: true, dollarStyle: true })).toBe("−$1.17 USDT");
  });

  it("renders frozen fixture KPI and fee labels", () => {
    render(
      <ClosedPositionOverview
        overview={OVERVIEW}
        basis={BASIS}
        history={HISTORY}
        unavailable={{
          fee_net_pnl: {
            value: null,
            reason: "fee_net_pnl_unavailable_phase2_ledger_required",
          },
        }}
      />,
    );

    expect(screen.getByText("49")).toBeInTheDocument();
    expect(screen.getAllByText("+$49.23 USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MEXC-reported closed-position PnL").length).toBeGreaterThan(0);
    expect(screen.getByText("Fee-net PnL")).toBeInTheDocument();
    expect(screen.getByText("fee net pnl unavailable phase2 ledger required")).toBeInTheDocument();
    expect(screen.getByText("Average PnL per active trading day")).toBeInTheDocument();
    expect(screen.getByText("Average PnL per calendar day")).toBeInTheDocument();
  });

  it("renders empty and approved error states without unsafe history or raw status copy", () => {
    const { rerender } = render(<ClosedPositionOverview overview={null} />);

    expect(screen.getByText(/No stored closed positions match these filters/)).toBeInTheDocument();
    expect(screen.queryByText(/partial history/i)).not.toBeInTheDocument();

    rerender(<ClosedPositionOverview overview={null} error="500 Server Error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Closed-position analytics could not load. No exchange action was taken. Try again.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("500 Server Error");
  });

  it("uses the approved closed-position error copy across Phase 1 panels", () => {
    render(
      <>
        <ClosedPositionPeriodChart items={[]} totals={{ trade_count: 0, total_pnl: null }} period="week" error="raw 502" />
        <ClosedPositionCalendar days={[]} totals={{ trade_count: 0, total_pnl: null }} error="raw 502" />
        <ClosedPositionBreakdowns breakdowns={{}} error="raw 502" />
      </>,
    );

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(3);
    alerts.forEach((alert) => {
      expect(alert).toHaveTextContent("Closed-position analytics could not load. No exchange action was taken. Try again.");
      expect(alert).not.toHaveTextContent("raw 502");
      expect(alert).not.toHaveTextContent("unavailable");
    });
  });

  it("exposes reachable labels, visible [from,to) helper text, mobile-stacking grid classes, and caps page size at 200", async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();
    const onApply = jest.fn();

    const { container } = render(
      <ClosedPositionFilters value={FILTERS} onChange={onChange} onApply={onApply} />,
    );

    expect(container.querySelector("form")?.className).toContain("grid gap-4");
    expect(screen.getByText("Date range uses [from,to): From is inclusive; To is exclusive.")).toBeInTheDocument();
    expect(screen.getByLabelText("Timezone")).toHaveValue("UTC");
    expect(screen.getByLabelText("From close time")).toBeInTheDocument();
    expect(screen.getByLabelText("From close time")).toHaveAccessibleDescription("Date range uses [from,to): From is inclusive; To is exclusive. Inclusive range start.");
    expect(screen.getByLabelText("To close time")).toBeInTheDocument();
    expect(screen.getByLabelText("To close time")).toHaveAccessibleDescription("Date range uses [from,to): From is inclusive; To is exclusive. Exclusive range end.");
    expect(screen.getByLabelText("Symbols")).toBeInTheDocument();
    expect(screen.getByLabelText("Side")).toBeInTheDocument();
    expect(screen.getByLabelText("Leverage min")).toBeInTheDocument();
    expect(screen.getByLabelText("Duration max minutes")).toBeInTheDocument();
    expect(screen.getByLabelText("PnL max USDT")).toBeInTheDocument();
    expect(screen.getByLabelText("Page size")).toHaveValue("50");

    expect(clampClosedPositionPageSize(500)).toBe(200);
    expect(clampClosedPositionPageSize(0)).toBe(1);

    await user.selectOptions(screen.getByLabelText("Page size"), "200");
    expect(onChange).toHaveBeenCalledWith({ ...FILTERS, limit: 200, offset: 0 });

    await user.click(screen.getByRole("button", { name: "Apply closed-position filters" }));
    expect(onApply).toHaveBeenCalled();
  });

  it("shows a Filters applied summary and resets non-default filter controls", async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();
    const activeFilters: ClosedPositionFiltersValue = {
      ...FILTERS,
      from: "2026-07-24T10:00",
      to: "2026-07-25T10:00",
      symbols: "BTCUSDT,ETHUSDT",
      side: "long",
      limit: 200,
    };

    render(<ClosedPositionFilters value={activeFilters} onChange={onChange} />);

    expect(screen.getByText(/Filters applied:/).closest("p")).toHaveTextContent(
      "from 2026-07-24T10:00 inclusive; to 2026-07-25T10:00 exclusive; symbols BTCUSDT,ETHUSDT; side long; page size 200",
    );

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(onChange).toHaveBeenCalledWith(DEFAULT_CLOSED_POSITION_FILTERS);
  });

  it("renders accessible period chart and calendar summaries from server totals", () => {
    render(
      <>
        <ClosedPositionPeriodChart
          items={PERIOD_ITEMS}
          totals={{ trade_count: 49, total_pnl: 49.23 }}
          period="week"
          filtersApplied={FILTERS_APPLIED}
          basis={BASIS}
          history={HISTORY}
        />
        <ClosedPositionCalendar
          days={CALENDAR_DAYS}
          totals={{ trade_count: 49, total_pnl: 49.23 }}
          filtersApplied={FILTERS_APPLIED}
          basis={BASIS}
          history={HISTORY}
        />
      </>,
    );

    expect(screen.getByRole("img", { name: /Closed-position week chart totals \+\$49\.23 USDT.*symbols BTC_USDT.*side long.*timezone UTC.*MEXC-reported closed-position PnL/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Closed-position PnL calendar total \+\$49\.23 USDT.*symbols BTC_USDT.*side long.*timezone UTC.*MEXC-reported closed-position PnL/ })).toBeInTheDocument();
    expect(screen.getAllByText("2026-W30").length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/2026-07-24: Profit; \+\$49\.23 USDT; 49 positions; MEXC-reported closed-position PnL/)).toBeInTheDocument();
  });

  it("renders all closed-position breakdown groups, unknown buckets, exclusions, and gross concentration semantics", () => {
    render(
      <ClosedPositionBreakdowns
        breakdowns={BREAKDOWNS}
        concentration={{
          gross_profit_top_1_contribution_pct: 100,
          gross_profit_hhi: 1,
          gross_loss_top_1_contribution_pct: 100,
          gross_loss_hhi: 1,
        }}
        excludedReasons={{ missing_duration: 2, missing_leverage: 1 }}
        basis={BASIS}
        history={HISTORY}
      />,
    );

    expect(screen.getByText("Symbol")).toBeInTheDocument();
    expect(screen.getByText("Side")).toBeInTheDocument();
    expect(screen.getByText("Duration bucket")).toBeInTheDocument();
    expect(screen.getByText("Leverage bucket")).toBeInTheDocument();
    expect(screen.getByText("Pair / direction")).toBeInTheDocument();
    expect(screen.getByText("Unknown duration")).toBeInTheDocument();
    expect(screen.getByText("Unknown leverage")).toBeInTheDocument();
    expect(screen.getByText(/rows excluded for missing duration/)).toBeInTheDocument();
    expect(screen.getByText(/rows excluded for missing leverage/)).toBeInTheDocument();
    expect(screen.getAllByText(/Gross contribution concentration uses nonnegative gross profit\/loss, not signed net PnL/).length).toBe(4);
    expect(screen.getAllByText("+$49.23 USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("−$1.17 USDT").length).toBeGreaterThan(0);
  });
});
