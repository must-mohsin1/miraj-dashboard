"use client";

import type { ReactNode } from "react";

export type ClosedPositionSideFilter = "" | "long" | "short";
export type ClosedPositionPeriodFilter = "day" | "week" | "month";
export type ClosedPositionSortFilter =
  | "-close_time"
  | "close_time"
  | "-pnl"
  | "pnl"
  | "symbol"
  | "side"
  | "leverage"
  | "duration_minutes";

export type ClosedPositionFiltersValue = {
  timezone: string;
  from: string;
  to: string;
  symbols: string;
  side: ClosedPositionSideFilter;
  leverage_min: string;
  leverage_max: string;
  duration_min_minutes: string;
  duration_max_minutes: string;
  close_reason: string;
  pnl_min: string;
  pnl_max: string;
  period: ClosedPositionPeriodFilter;
  limit: number;
  offset: number;
  sort: ClosedPositionSortFilter;
};

export const DEFAULT_CLOSED_POSITION_FILTERS: ClosedPositionFiltersValue = {
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

export interface ClosedPositionFiltersProps {
  value: ClosedPositionFiltersValue;
  onChange: (value: ClosedPositionFiltersValue) => void;
  onApply?: () => void;
  disabled?: boolean;
}

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;

export function clampClosedPositionPageSize(value: number): number {
  if (!Number.isFinite(value)) return 50;
  return Math.max(1, Math.min(200, Math.trunc(value)));
}

export function ClosedPositionFilters({
  value,
  onChange,
  onApply,
  disabled = false,
}: ClosedPositionFiltersProps) {
  const activeFilters = describeActiveFilters(value);
  const hasActiveFilters = activeFilters.length > 0;

  function update<K extends keyof ClosedPositionFiltersValue>(
    key: K,
    nextValue: ClosedPositionFiltersValue[K],
  ) {
    onChange({ ...value, [key]: nextValue, offset: key === "offset" ? Number(nextValue) : 0 });
  }

  function resetFilters() {
    onChange(DEFAULT_CLOSED_POSITION_FILTERS);
  }

  return (
    <form
      className="grid gap-4 border border-border bg-card p-4 md:grid-cols-2 xl:grid-cols-4"
      aria-label="Closed-position analytics filters"
      onSubmit={(event) => {
        event.preventDefault();
        onApply?.();
      }}
    >
      {hasActiveFilters ? (
        <div className="grid gap-3 border border-border bg-background p-3 md:col-span-2 xl:col-span-4 md:grid-cols-[1fr_auto] md:items-center">
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Filters applied:</span>{" "}
            {activeFilters.join("; ")}
          </p>
          <button
            type="button"
            onClick={resetFilters}
            disabled={disabled}
            className="min-h-10 border border-border bg-card px-3 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
          >
            Reset filters
          </button>
        </div>
      ) : null}

      <p id="closed-position-range-contract" className="text-xs leading-relaxed text-muted-foreground md:col-span-2 xl:col-span-4">
        Date range uses [from,to): From is inclusive; To is exclusive.
      </p>

      <FilterField label="Timezone" htmlFor="closed-position-timezone">
        <input
          id="closed-position-timezone"
          value={value.timezone}
          onChange={(event) => update("timezone", event.target.value)}
          disabled={disabled}
          placeholder="UTC"
          className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </FilterField>

      <FilterField label="From close time" htmlFor="closed-position-from" descriptionId="closed-position-from-helper" description="Inclusive range start.">
        <input
          id="closed-position-from"
          type="datetime-local"
          value={value.from}
          onChange={(event) => update("from", event.target.value)}
          disabled={disabled}
          aria-describedby="closed-position-range-contract closed-position-from-helper"
          className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </FilterField>

      <FilterField label="To close time" htmlFor="closed-position-to" descriptionId="closed-position-to-helper" description="Exclusive range end.">
        <input
          id="closed-position-to"
          type="datetime-local"
          value={value.to}
          onChange={(event) => update("to", event.target.value)}
          disabled={disabled}
          aria-describedby="closed-position-range-contract closed-position-to-helper"
          className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </FilterField>

      <FilterField label="Symbols" htmlFor="closed-position-symbols">
        <input
          id="closed-position-symbols"
          value={value.symbols}
          onChange={(event) => update("symbols", event.target.value.toUpperCase())}
          disabled={disabled}
          placeholder="BTCUSDT, ETHUSDT"
          className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </FilterField>

      <FilterField label="Side" htmlFor="closed-position-side">
        <select
          id="closed-position-side"
          value={value.side}
          onChange={(event) => update("side", event.target.value as ClosedPositionSideFilter)}
          disabled={disabled}
          className="h-10 w-full border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        >
          <option value="">All sides</option>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
      </FilterField>

      <NumberField id="closed-position-leverage-min" label="Leverage min" value={value.leverage_min} disabled={disabled} onChange={(nextValue) => update("leverage_min", nextValue)} />
      <NumberField id="closed-position-leverage-max" label="Leverage max" value={value.leverage_max} disabled={disabled} onChange={(nextValue) => update("leverage_max", nextValue)} />
      <NumberField id="closed-position-duration-min" label="Duration min minutes" value={value.duration_min_minutes} disabled={disabled} onChange={(nextValue) => update("duration_min_minutes", nextValue)} />
      <NumberField id="closed-position-duration-max" label="Duration max minutes" value={value.duration_max_minutes} disabled={disabled} onChange={(nextValue) => update("duration_max_minutes", nextValue)} />
      <NumberField id="closed-position-pnl-min" label="PnL min USDT" value={value.pnl_min} disabled={disabled} onChange={(nextValue) => update("pnl_min", nextValue)} />
      <NumberField id="closed-position-pnl-max" label="PnL max USDT" value={value.pnl_max} disabled={disabled} onChange={(nextValue) => update("pnl_max", nextValue)} />

      <FilterField label="Close reason" htmlFor="closed-position-close-reason">
        <input
          id="closed-position-close-reason"
          value={value.close_reason}
          onChange={(event) => update("close_reason", event.target.value)}
          disabled={disabled}
          placeholder="take_profit, stop_loss"
          className="h-10 w-full border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        />
      </FilterField>

      <FilterField label="Period" htmlFor="closed-position-period">
        <select
          id="closed-position-period"
          value={value.period}
          onChange={(event) => update("period", event.target.value as ClosedPositionPeriodFilter)}
          disabled={disabled}
          className="h-10 w-full border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        >
          <option value="day">Day</option>
          <option value="week">Week</option>
          <option value="month">Month</option>
        </select>
      </FilterField>

      <FilterField label="Sort" htmlFor="closed-position-sort">
        <select
          id="closed-position-sort"
          value={value.sort}
          onChange={(event) => update("sort", event.target.value as ClosedPositionSortFilter)}
          disabled={disabled}
          className="h-10 w-full border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        >
          <option value="-close_time">Newest close time</option>
          <option value="close_time">Oldest close time</option>
          <option value="-pnl">Highest PnL</option>
          <option value="pnl">Lowest PnL</option>
          <option value="symbol">Symbol</option>
          <option value="side">Side</option>
          <option value="leverage">Leverage</option>
          <option value="duration_minutes">Duration</option>
        </select>
      </FilterField>

      <FilterField label="Page size" htmlFor="closed-position-limit">
        <select
          id="closed-position-limit"
          value={String(value.limit)}
          onChange={(event) => update("limit", clampClosedPositionPageSize(Number(event.target.value)))}
          disabled={disabled}
          className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        >
          {PAGE_SIZE_OPTIONS.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      </FilterField>

      <div className="flex items-end">
        <button
          type="submit"
          disabled={disabled}
          className="min-h-11 w-full border border-border bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
        >
          Apply closed-position filters
        </button>
      </div>
    </form>
  );
}

function NumberField({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <FilterField label={label} htmlFor={id}>
      <input
        id={id}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="h-10 w-full border border-input bg-background px-3 font-mono text-sm tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
      />
    </FilterField>
  );
}

function FilterField({
  label,
  htmlFor,
  descriptionId,
  description,
  children,
}: {
  label: string;
  htmlFor: string;
  descriptionId?: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </label>
      {children}
      {description ? <p id={descriptionId} className="text-xs text-muted-foreground">{description}</p> : null}
    </div>
  );
}

function describeActiveFilters(value: ClosedPositionFiltersValue): string[] {
  const parts: string[] = [];
  if (value.timezone !== DEFAULT_CLOSED_POSITION_FILTERS.timezone) parts.push(`timezone ${value.timezone || "unset"}`);
  if (value.from) parts.push(`from ${value.from} inclusive`);
  if (value.to) parts.push(`to ${value.to} exclusive`);
  if (value.symbols) parts.push(`symbols ${value.symbols}`);
  if (value.side) parts.push(`side ${value.side}`);
  if (value.leverage_min) parts.push(`leverage min ${value.leverage_min}`);
  if (value.leverage_max) parts.push(`leverage max ${value.leverage_max}`);
  if (value.duration_min_minutes) parts.push(`duration min ${value.duration_min_minutes} min`);
  if (value.duration_max_minutes) parts.push(`duration max ${value.duration_max_minutes} min`);
  if (value.close_reason) parts.push(`close reason ${value.close_reason}`);
  if (value.pnl_min) parts.push(`PnL min ${value.pnl_min} USDT`);
  if (value.pnl_max) parts.push(`PnL max ${value.pnl_max} USDT`);
  if (value.period !== DEFAULT_CLOSED_POSITION_FILTERS.period) parts.push(`period ${value.period}`);
  if (value.limit !== DEFAULT_CLOSED_POSITION_FILTERS.limit) parts.push(`page size ${value.limit}`);
  if (value.offset !== DEFAULT_CLOSED_POSITION_FILTERS.offset) parts.push(`offset ${value.offset}`);
  if (value.sort !== DEFAULT_CLOSED_POSITION_FILTERS.sort) parts.push(`sort ${value.sort}`);
  return parts;
}

export default ClosedPositionFilters;
