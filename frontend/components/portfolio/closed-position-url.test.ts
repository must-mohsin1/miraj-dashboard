import {
  applyClosedPositionFiltersToSearchParams,
  closedPositionFiltersQueryFingerprint,
  parseClosedPositionFiltersFromSearch,
} from "@/components/portfolio/closed-position-url";
import {
  DEFAULT_CLOSED_POSITION_FILTERS,
  type ClosedPositionFiltersValue,
} from "@/components/portfolio/closed-position-filters";

describe("closed-position URL helpers", () => {
  it("parses symbols, side, sort, period, and pagination from search params", () => {
    const filters = parseClosedPositionFiltersFromSearch(
      new URLSearchParams(
        "symbols=btcusdt,ethusdt&side=long&sort=-pnl&period=day&limit=100&offset=50&from=2026-01-01T00:00",
      ),
    );

    expect(filters.symbols).toBe("BTCUSDT,ETHUSDT");
    expect(filters.side).toBe("long");
    expect(filters.sort).toBe("-pnl");
    expect(filters.period).toBe("day");
    expect(filters.limit).toBe(100);
    expect(filters.offset).toBe(50);
    expect(filters.from).toBe("2026-01-01T00:00");
  });

  it("clamps oversize limit and ignores invalid side/sort", () => {
    const filters = parseClosedPositionFiltersFromSearch({
      limit: "999",
      side: "both",
      sort: "not-a-sort",
      period: "year",
    });

    expect(filters.limit).toBe(200);
    expect(filters.side).toBe("");
    expect(filters.sort).toBe(DEFAULT_CLOSED_POSITION_FILTERS.sort);
    expect(filters.period).toBe(DEFAULT_CLOSED_POSITION_FILTERS.period);
  });

  it("serializes only non-default filter keys", () => {
    const params = applyClosedPositionFiltersToSearchParams(new URLSearchParams(), {
      ...DEFAULT_CLOSED_POSITION_FILTERS,
      symbols: "BTCUSDT",
      side: "short",
      sort: "pnl",
      limit: 25,
      offset: 25,
    });

    expect(params.get("symbols")).toBe("BTCUSDT");
    expect(params.get("side")).toBe("short");
    expect(params.get("sort")).toBe("pnl");
    expect(params.get("limit")).toBe("25");
    expect(params.get("offset")).toBe("25");
    expect(params.get("period")).toBeNull();
    expect(params.get("timezone")).toBeNull();
  });

  it("round-trips fingerprint for identical filters", () => {
    const a = {
      ...DEFAULT_CLOSED_POSITION_FILTERS,
      symbols: "BTCUSDT",
      side: "long" as const,
    };
    const b = parseClosedPositionFiltersFromSearch(
      applyClosedPositionFiltersToSearchParams(new URLSearchParams(), a),
    );
    expect(closedPositionFiltersQueryFingerprint(a)).toBe(
      closedPositionFiltersQueryFingerprint(b),
    );
  });

  it("does not throw on empty/missing search params or array values", () => {
    expect(() => parseClosedPositionFiltersFromSearch({})).not.toThrow();
    expect(() =>
      parseClosedPositionFiltersFromSearch({
        symbols: undefined,
        side: ["long"],
        limit: ["50"],
      } as Record<string, string | string[] | undefined>),
    ).not.toThrow();
    const filters = parseClosedPositionFiltersFromSearch({
      side: ["short"],
      symbols: ["btcusdt"],
    } as Record<string, string | string[] | undefined>);
    expect(filters.side).toBe("short");
    expect(filters.symbols).toBe("BTCUSDT");
  });

  it("fingerprints partial filter objects without throwing", () => {
    expect(() =>
      closedPositionFiltersQueryFingerprint({
        symbols: "BTCUSDT",
      } as ClosedPositionFiltersValue),
    ).not.toThrow();
    expect(
      applyClosedPositionFiltersToSearchParams(new URLSearchParams(), {
        symbols: "ETHUSDT",
      } as ClosedPositionFiltersValue).get("symbols"),
    ).toBe("ETHUSDT");
  });
});
