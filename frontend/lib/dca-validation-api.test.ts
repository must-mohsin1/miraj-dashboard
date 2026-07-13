/// <reference types="jest" />

import { serverFetch } from "@/lib/api";
import {
  buildDcaShadowHistoryQuery,
  buildDcaValidationPath,
  fetchDcaValidation,
  parseDcaValidationResponse,
} from "@/lib/dca-validation-api";
import {
  DCA_VALIDATION_RECONSTRUCTION_LABEL,
  DCA_VALIDATION_RECONSTRUCTION_METHOD,
  DCA_VALIDATION_SIMULATED_METRICS_LABEL,
} from "@/lib/dca-validation-types";

jest.mock("@/lib/api", () => ({
  serverFetch: jest.fn(),
}));

const mockedServerFetch = jest.mocked(serverFetch);

function validationResponse(overrides: Record<string, unknown> = {}) {
  return {
    state: "metrics_available",
    exchange: "binance",
    request: {
      exchange: "binance",
      symbol: "BTCUSDT",
      start_date: "2026-07-01T00:00:00.000Z",
      end_date: "2026-07-04T00:00:00.000Z",
      split_ratio: 0.6,
      timeout_ms: 2500,
    },
    reconstruction: {
      exchange: "binance",
      method: "scan-to-scan",
      method_description: "scan-history reconstruction; not candle-level historical replay",
      fill_assumptions: {
        long_thresholds: [30, 24, 16],
        short_thresholds: [80, 92, 95],
        allocations: [20, 20, 60],
        slippage_percent: 0.05,
        fee_percent: 0.04,
      },
      symbols: [
        {
          symbol: "BTCUSDT",
          status: "metrics_available",
          required_minimum_scans: 2,
          scan_count: 3,
          first_scan_at: "2026-07-01T00:00:00",
          last_scan_at: "2026-07-03T00:00:00",
          max_scan_gap_seconds: 86400,
          events: [{ recommendation: "ADD", participates_in_metrics: true }],
          skipped_scans: [],
        },
      ],
    },
    metrics: {
      exchange: "binance",
      split_ratio: 0.6,
      symbols: [
        {
          symbol: "BTCUSDT",
          status: "metrics_available",
          metrics: {
            win_rate: { value: 100, reason: null },
            profit_factor: { value: null, reason: "gross_loss_is_zero" },
          },
        },
      ],
      portfolio: { metrics: { win_rate: { value: 100, reason: null } } },
    },
    shadow_history: [
      {
        timestamp: "2026-07-04T00:00:00Z",
        exchange: "binance",
        symbol: "BTCUSDT",
        original_recommendation: "ADD",
        final_outcome: "would_block",
        gate_breakdown: [{ name: "dca_safe", passed: false, reason: "DCA SAFE checklist did not pass." }],
        blocked_gates: ["dca_safe"],
        assumption_set: { mode: "shadow_non_live", live_execution: false },
        final_reason: "Shadow ADD would be blocked because these gates failed: DCA SAFE checklist. No live order was placed.",
      },
    ],
    validation_errors: [],
    last_completed: null,
    disclaimer: "These are reconstructed and shadow-mode results, not realized trading performance or financial advice.",
    ...overrides,
  };
}

describe("DCA validation API helpers", () => {
  beforeEach(() => {
    mockedServerFetch.mockReset();
  });

  it("builds validation query strings for exchange, symbol, date range, split ratio, and timeout", () => {
    expect(
      buildDcaValidationPath("Binance", {
        symbol: "btcusdt",
        startDate: new Date("2026-07-01T00:00:00Z"),
        endDate: "2026-07-04T00:00:00Z",
        splitRatio: 0.6,
        timeoutMs: 1500,
        shadowOutcome: "would_block",
        shadowLimit: 50,
      })
    ).toBe(
      "/api/v1/dca-validation/binance?symbol=BTCUSDT&start_date=2026-07-01T00%3A00%3A00.000Z&end_date=2026-07-04T00%3A00%3A00Z&split_ratio=0.6&timeout_ms=1500&outcome=would_block&limit=50"
    );
  });

  it("builds stable shadow-history filter query strings", () => {
    expect(
      buildDcaShadowHistoryQuery({
        symbol: "ethusdt",
        outcome: "would_block",
        startDate: "2026-07-01T00:00:00Z",
        endDate: "2026-07-02T00:00:00Z",
        limit: 50,
      })
    ).toBe(
      "symbol=ETHUSDT&outcome=would_block&start_date=2026-07-01T00%3A00%3A00Z&end_date=2026-07-02T00%3A00%3A00Z&limit=50"
    );
  });

  it("fetches with existing serverFetch token convention and parses a valid response", async () => {
    mockedServerFetch.mockResolvedValueOnce(validationResponse());

    const result = await fetchDcaValidation("binance", "test-token", { symbol: "btcusdt", splitRatio: 0.6 });

    expect(mockedServerFetch).toHaveBeenCalledWith(
      "/api/v1/dca-validation/binance?symbol=BTCUSDT&split_ratio=0.6",
      "test-token"
    );
    expect(result.state).toBe("metrics_available");
    expect(result.reconstruction?.method).toBe("scan-to-scan");
    expect(result.shadow_history[0].final_outcome).toBe("would_block");
  });

  it("throws on invalid response envelopes", () => {
    expect(() => parseDcaValidationResponse({ state: "done" })).toThrow(
      "Invalid DCA validation response: unknown state"
    );
    expect(() => parseDcaValidationResponse(validationResponse({ shadow_history: null }))).toThrow(
      "Invalid DCA validation response: shadow_history must be an array"
    );
  });

  it("accepts insufficient-history responses as a first-class typed state", () => {
    const parsed = parseDcaValidationResponse(
      validationResponse({
        state: "insufficient_history",
        metrics: null,
        reconstruction: {
          exchange: "binance",
          method: "scan-to-scan",
          method_description: "scan-history reconstruction; not candle-level historical replay",
          fill_assumptions: { fee_percent: 0.04, slippage_percent: 0.05 },
          symbols: [
            {
              symbol: "ETHUSDT",
              status: "insufficient_history",
              required_minimum_scans: 2,
              scan_count: 1,
              first_scan_at: "2026-07-01T00:00:00",
              last_scan_at: "2026-07-01T00:00:00",
              max_scan_gap_seconds: null,
              events: [],
              skipped_scans: [],
            },
          ],
        },
      })
    );

    expect(parsed.state).toBe("insufficient_history");
    expect(parsed.metrics).toBeNull();
    expect(parsed.reconstruction?.symbols[0].required_minimum_scans).toBe(2);
  });

  it("exports stable labels for scan-history reconstruction and simulated metrics", () => {
    expect(DCA_VALIDATION_RECONSTRUCTION_METHOD).toBe("scan-to-scan");
    expect(DCA_VALIDATION_RECONSTRUCTION_LABEL).toBe("scan-history reconstruction");
    expect(DCA_VALIDATION_SIMULATED_METRICS_LABEL).toBe("simulated metrics");
  });
});
