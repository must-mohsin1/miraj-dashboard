import { formatUtcDateTime } from "@/lib/date-format";

describe("formatUtcDateTime", () => {
  it("renders ISO timestamps with a deterministic UTC format", () => {
    expect(formatUtcDateTime("2026-07-26T02:30:00Z")).toBe("Jul 26, 2026, 02:30 UTC");
  });

  it("preserves invalid timestamp text instead of inventing a date", () => {
    expect(formatUtcDateTime("not-a-date")).toBe("not-a-date");
  });
});
