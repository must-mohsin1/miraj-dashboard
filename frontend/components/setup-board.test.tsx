import { lastFinite, pickCandidates } from "./setup-board";
import type { OrderBlock } from "@/lib/types";

const blocks: OrderBlock[] = [
  { start_time: 1, end_time: 2, price_low: 90, price_high: 95, type: "bullish" },
  { start_time: 1, end_time: 2, price_low: 80, price_high: 84, type: "bullish" },
  { start_time: 1, end_time: 2, price_low: 110, price_high: 115, type: "bearish" },
  { start_time: 1, end_time: 2, price_low: 130, price_high: 140, type: "bearish" },
];

describe("pickCandidates", () => {
  it("picks the nearest bullish zone below price and bearish zone above", () => {
    const { long, short } = pickCandidates(blocks, 100);
    expect(long?.zoneHigh).toBe(95);
    expect(short?.zoneLow).toBe(110);
    expect(long?.label).toMatch(/below price|In range/);
  });

  it("returns nulls when price is missing", () => {
    expect(pickCandidates(blocks, null)).toEqual({ long: null, short: null });
  });

  it("reads the last finite indicator value and skips nulls", () => {
    expect(lastFinite([12, null, 48.2])).toBe(48.2);
    expect(lastFinite([Number.NaN])).toBeNull();
    expect(lastFinite(null)).toBeNull();
  });
});
