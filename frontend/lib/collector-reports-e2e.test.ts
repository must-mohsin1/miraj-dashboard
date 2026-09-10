/// <reference types="jest" />

import { readFileSync } from "node:fs";

import { parseLatestCollectorReport } from "@/lib/collector-reports-api";

const responsePath = process.env.COLLECTOR_E2E_RESPONSE_PATH;
const senderToFrontendContract = responsePath ? it : it.skip;

describe("collector sender-to-frontend runtime contract", () => {
  senderToFrontendContract("parses the backend latest response created from an actual sender report (requires COLLECTOR_E2E_RESPONSE_PATH)", () => {
    const response = JSON.parse(readFileSync(responsePath!, "utf8")) as unknown;

    const parsed = parseLatestCollectorReport(response);

    expect(parsed.status).toBe("validated");
    expect(parsed.report?.symbol).toBe("SOLUSDT");
    expect(parsed.report?.timeframes[0]).toEqual(expect.objectContaining({
      timeframe: "4h",
      state: "observed",
      close: 142.35,
      candles: expect.any(Array),
    }));
  });
});
