/// <reference types="jest" />

import { serverFetch } from "@/lib/api";
import {
  buildLatestCollectorReportPath,
  fetchLatestCollectorReport,
  parseLatestCollectorReport,
} from "@/lib/collector-reports-api";

jest.mock("@/lib/api", () => ({ serverFetch: jest.fn() }));

const mockedServerFetch = jest.mocked(serverFetch);

const validatedResponse = {
  status: "validated",
  stale: false,
  received_at: "2026-09-10T04:05:00Z",
  report: {
    report_id: "solusdt-20260910-040000",
    payload_sha256: "a".repeat(64),
    generated_at: "2026-09-10T04:00:00Z",
    symbol: "SOLUSDT",
    venue: "mexc_spot",
    source: "hourly_collector",
    schema_version: "1.0",
    verdict: { state: "NO_TRADE", summary: "No trade today.", gates: [{ label: "HTF alignment", state: "blocked", reason: "Daily trend is mixed." }] },
    quote: { price: 142.35, as_of: "2026-09-10T04:00:00Z", context_only: true },
    scores: [{ label: "Trend", value: 52, maximum: 100 }, { label: "Structure", value: 38, maximum: 100 }],
    timeframes: [{ timeframe: "4h", state: "mixed", close: 142.35, as_of: "2026-09-10T04:00:00Z", candles: [{ time: "2026-09-10T00:00:00Z", open: 141, high: 143, low: 140, close: 142.35, volume: 3200 }], fvg: { low: 140.2, high: 141.1 }, ote: { low: 139.8, high: 141.6 } }],
    source_health: [{ source: "mexc_spot_4h", status: "ok", checked_at: "2026-09-10T04:00:00Z", fallback: false }],
    limitations: ["Public market data only."],
    setup_states: [
      { state: "S0", status: "passed", label: "Public data collection", reason: "Collection completed." },
      { state: "S1", status: "passed", label: "Setup gate S1", reason: "Higher timeframe aligned." },
      { state: "S2", status: "blocked", label: "Setup gate S2", reason: "Liquidity confirmation missing." },
      { state: "S3", status: "pending", label: "Setup gate S3", reason: "Waiting for retracement." },
      { state: "S4", status: "unavailable", label: "Setup gate S4", reason: "No entry trigger supplied." },
      { state: "S5", status: "pending", label: "Setup gate S5", reason: "Risk review pending." },
    ],
  },
};

describe("collector report API", () => {
  beforeEach(() => mockedServerFetch.mockReset());

  it("builds the stable SOLUSDT latest-report boundary", () => {
    expect(buildLatestCollectorReportPath(" solusdt ")).toBe("/api/v1/collector-reports/latest?symbol=SOLUSDT");
  });

  it("fetches and parses a validated collector report with the authenticated server convention", async () => {
    mockedServerFetch.mockResolvedValueOnce(validatedResponse);

    const result = await fetchLatestCollectorReport("SOLUSDT", "test-token");

    expect(mockedServerFetch).toHaveBeenCalledWith("/api/v1/collector-reports/latest?symbol=SOLUSDT", "test-token");
    expect(result.status).toBe("validated");
    expect(result.report?.quote.price).toBe(142.35);
    expect(result.report?.verdict.state).toBe("NO_TRADE");
  });

  it("retains an unavailable response without inventing a report", () => {
    expect(parseLatestCollectorReport({ status: "unavailable", stale: true, received_at: null, report: null })).toEqual({
      status: "unavailable",
      stale: true,
      received_at: null,
      report: null,
    });
  });

  it("rejects reports that contain an unrecognized verdict state", () => {
    expect(() => parseLatestCollectorReport({ ...validatedResponse, report: { ...validatedResponse.report, verdict: { ...validatedResponse.report.verdict, state: "BUY_NOW" } } })).toThrow("Invalid collector report: unknown verdict state");
  });

  it("rejects a report that omits a required setup state", () => {
    expect(() => parseLatestCollectorReport({
      ...validatedResponse,
      report: { ...validatedResponse.report, setup_states: validatedResponse.report.setup_states.filter((entry) => entry.state !== "S5") },
    })).toThrow("Invalid collector report: setup_states must include S0 through S5");
  });

  it("rejects a setup state with a malformed status", () => {
    expect(() => parseLatestCollectorReport({
      ...validatedResponse,
      report: { ...validatedResponse.report, setup_states: validatedResponse.report.setup_states.map((entry) => entry.state === "S3" ? { ...entry, status: "complete" } : entry) },
    })).toThrow("Invalid collector report: setup_states must include S0 through S5");
  });

  it("rejects a report with an unallowlisted nested verdict field", () => {
    expect(() => parseLatestCollectorReport({
      ...validatedResponse,
      report: { ...validatedResponse.report, verdict: { ...validatedResponse.report.verdict, note: "collector credential: private-key-material" } },
    })).toThrow(/Invalid collector report:/);
  });

  it.each([
    ["gate", { verdict: { ...validatedResponse.report.verdict, gates: [{ label: "HTF", state: "unknown" }] } }],
    ["score", { scores: [{ label: "Trend", value: "52", maximum: 100 }] }],
    ["timeframe", { timeframes: [{ ...validatedResponse.report.timeframes[0], state: 4 }] }],
    ["candle", { timeframes: [{ ...validatedResponse.report.timeframes[0], candles: [{ ...validatedResponse.report.timeframes[0].candles[0], high: "143" }] }] }],
    ["range", { timeframes: [{ ...validatedResponse.report.timeframes[0], fvg: { low: "140.2", high: 141.1 } }] }],
    ["source health", { source_health: [{ ...validatedResponse.report.source_health[0], status: "healthy" }] }],
    ["limitation", { limitations: [42] }],
  ])("rejects malformed nested %s evidence", (_name, changes) => {
    expect(() => parseLatestCollectorReport({
      ...validatedResponse,
      report: { ...validatedResponse.report, ...changes },
    })).toThrow(/Invalid collector report:/);
  });
});
