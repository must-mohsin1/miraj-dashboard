/**
 * Closed-position / Trade Explorer filter ↔ URL search param helpers.
 *
 * Deep-link shape (portfolio page):
 *   /portfolio?exchange=mexc&tab=analytics&analytics_tab=closed-positions
 *     &symbols=BTCUSDT&side=long&sort=-pnl&period=week&limit=50&offset=0
 */

import {
  clampClosedPositionPageSize,
  DEFAULT_CLOSED_POSITION_FILTERS,
  type ClosedPositionFiltersValue,
  type ClosedPositionPeriodFilter,
  type ClosedPositionSideFilter,
  type ClosedPositionSortFilter,
} from "@/components/portfolio/closed-position-filters";

const SORT_VALUES = new Set<ClosedPositionSortFilter>([
  "-close_time",
  "close_time",
  "-pnl",
  "pnl",
  "symbol",
  "side",
  "leverage",
  "duration_minutes",
]);

const SIDE_VALUES = new Set<ClosedPositionSideFilter>(["", "long", "short"]);
const PERIOD_VALUES = new Set<ClosedPositionPeriodFilter>(["day", "week", "month"]);

/** Keys we own on the portfolio URL for closed-position filters. */
export const CLOSED_POSITION_URL_KEYS = [
  "symbols",
  "side",
  "sort",
  "period",
  "limit",
  "offset",
  "from",
  "to",
  "close_reason",
  "leverage_min",
  "leverage_max",
  "duration_min_minutes",
  "duration_max_minutes",
  "pnl_min",
  "pnl_max",
  "timezone",
] as const;

export type ClosedPositionUrlKey = (typeof CLOSED_POSITION_URL_KEYS)[number];

function readParam(
  source: URLSearchParams | Record<string, string | string[] | undefined>,
  key: string,
): string {
  let value: unknown;
  if (typeof URLSearchParams !== "undefined" && source instanceof URLSearchParams) {
    value = source.get(key);
  } else if (source && typeof source === "object") {
    const raw = (source as Record<string, unknown>)[key];
    value = Array.isArray(raw) ? raw[0] : raw;
  } else {
    value = undefined;
  }
  // Next searchParams values are usually string | string[] | undefined; coerce
  // anything else so missing/odd shapes never throw on .trim().
  if (value == null) return "";
  return String(value).trim();
}

export function parseClosedPositionFiltersFromSearch(
  source: URLSearchParams | Record<string, string | string[] | undefined> | null | undefined,
): ClosedPositionFiltersValue {
  const base: ClosedPositionFiltersValue = {
    ...DEFAULT_CLOSED_POSITION_FILTERS,
  };
  if (!source) return base;

  const symbols = readParam(source, "symbols")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
    .join(",");
  if (symbols) base.symbols = symbols;

  const side = readParam(source, "side").toLowerCase() as ClosedPositionSideFilter;
  if (SIDE_VALUES.has(side)) base.side = side;

  const sort = readParam(source, "sort") as ClosedPositionSortFilter;
  if (SORT_VALUES.has(sort)) base.sort = sort;

  const period = readParam(source, "period").toLowerCase() as ClosedPositionPeriodFilter;
  if (PERIOD_VALUES.has(period)) base.period = period;

  const limitRaw = Number(readParam(source, "limit"));
  if (Number.isFinite(limitRaw) && limitRaw > 0) {
    base.limit = clampClosedPositionPageSize(limitRaw);
  }

  const offsetRaw = Number(readParam(source, "offset"));
  if (Number.isFinite(offsetRaw) && offsetRaw >= 0) {
    base.offset = Math.trunc(offsetRaw);
  }

  for (const key of [
    "from",
    "to",
    "close_reason",
    "leverage_min",
    "leverage_max",
    "duration_min_minutes",
    "duration_max_minutes",
    "pnl_min",
    "pnl_max",
    "timezone",
  ] as const) {
    const value = readParam(source, key);
    if (value) base[key] = value;
  }

  return base;
}

/**
 * Apply closed-position filters onto a URLSearchParams instance.
 * Removes keys when they match defaults (keeps links short).
 */
export function applyClosedPositionFiltersToSearchParams(
  params: URLSearchParams,
  filters: ClosedPositionFiltersValue,
): URLSearchParams {
  const defaults = DEFAULT_CLOSED_POSITION_FILTERS;

  const setOrDelete = (key: string, value: string, defaultValue: string) => {
    // Coerce — callers may pass partial filter objects or undefined fields.
    const trimmed = String(value ?? "").trim();
    const defaultTrimmed = String(defaultValue ?? "").trim();
    if (!trimmed || trimmed === defaultTrimmed) {
      params.delete(key);
    } else {
      params.set(key, trimmed);
    }
  };

  setOrDelete("symbols", filters.symbols, defaults.symbols);
  setOrDelete("side", filters.side, defaults.side);
  setOrDelete("sort", filters.sort, defaults.sort);
  setOrDelete("period", filters.period, defaults.period);
  setOrDelete("timezone", filters.timezone, defaults.timezone);
  setOrDelete("from", filters.from, defaults.from);
  setOrDelete("to", filters.to, defaults.to);
  setOrDelete("close_reason", filters.close_reason, defaults.close_reason);
  setOrDelete("leverage_min", filters.leverage_min, defaults.leverage_min);
  setOrDelete("leverage_max", filters.leverage_max, defaults.leverage_max);
  setOrDelete(
    "duration_min_minutes",
    filters.duration_min_minutes,
    defaults.duration_min_minutes,
  );
  setOrDelete(
    "duration_max_minutes",
    filters.duration_max_minutes,
    defaults.duration_max_minutes,
  );
  setOrDelete("pnl_min", filters.pnl_min, defaults.pnl_min);
  setOrDelete("pnl_max", filters.pnl_max, defaults.pnl_max);

  const limit = Number(filters.limit);
  if (!Number.isFinite(limit) || limit === defaults.limit) {
    params.delete("limit");
  } else {
    params.set("limit", String(clampClosedPositionPageSize(limit)));
  }

  const offset = Number(filters.offset);
  if (!Number.isFinite(offset) || offset === defaults.offset || offset <= 0) {
    params.delete("offset");
  } else {
    params.set("offset", String(Math.max(0, Math.trunc(offset))));
  }

  return params;
}

/** Stable string for comparing filter URL footprints. */
export function closedPositionFiltersQueryFingerprint(
  filters: ClosedPositionFiltersValue,
): string {
  const params = applyClosedPositionFiltersToSearchParams(
    new URLSearchParams(),
    filters,
  );
  params.sort();
  return params.toString();
}
