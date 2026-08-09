import {
  buildTradeExplorerCsvFilename,
  buildTradeExplorerExportQuery,
  tradeExplorerItemsToCsv,
  TRADE_EXPLORER_CSV_HEADERS,
} from "@/components/portfolio/trade-explorer-csv";
import type { TradeExplorerItem } from "@/components/portfolio/trade-explorer";

const SAMPLE: TradeExplorerItem[] = [
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
    symbol: 'ETH,"USDT"',
    side: "short",
    size: 3,
    entry_price: 3800,
    exit_price: 3825,
    pnl: -1.17,
    pnl_percent: -0.31,
    leverage: null,
    open_time: null,
    close_time: "2026-07-24T11:00:00Z",
    duration_minutes: null,
    close_reason: null,
    unavailable_reasons: { missing_leverage: true, missing_duration: true },
  },
];

describe("tradeExplorerItemsToCsv", () => {
  it("emits BOM header row and one line per item", () => {
    const csv = tradeExplorerItemsToCsv(SAMPLE);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    const body = csv.replace(/^\uFEFF/, "").trimEnd();
    const lines = body.split("\n");
    expect(lines[0]).toBe(TRADE_EXPLORER_CSV_HEADERS.join(","));
    expect(lines).toHaveLength(3);
    expect(lines[1]).toContain("911");
    expect(lines[1]).toContain("BTC_USDT");
    expect(lines[1]).toContain("1.05");
  });

  it("escapes commas and quotes in symbol cells", () => {
    const csv = tradeExplorerItemsToCsv(SAMPLE);
    expect(csv).toContain('"ETH,""USDT"""');
  });

  it("flattens unavailable reason objects", () => {
    const csv = tradeExplorerItemsToCsv(SAMPLE);
    expect(csv).toContain("missing_leverage|missing_duration");
  });
});

describe("buildTradeExplorerCsvFilename", () => {
  it("includes exchange slug and ISO-ish stamp", () => {
    const name = buildTradeExplorerCsvFilename(
      "mexc",
      new Date("2026-08-05T12:30:00.000Z"),
    );
    expect(name).toBe("trade-explorer-mexc-2026-08-05-123000.csv");
  });

  it("marks full filtered exports in the filename", () => {
    const name = buildTradeExplorerCsvFilename(
      "mexc",
      new Date("2026-08-05T12:30:00.000Z"),
      "filtered",
    );
    expect(name).toBe("trade-explorer-mexc-filtered-2026-08-05-123000.csv");
  });
});

describe("buildTradeExplorerExportQuery", () => {
  it("omits empty filter fields and pagination", () => {
    const q = buildTradeExplorerExportQuery({
      timezone: "UTC",
      period: "week",
      sort: "-pnl",
      symbols: "BTCUSDT",
      side: "long",
      from: "",
    });
    const params = new URLSearchParams(q);
    expect(params.get("sort")).toBe("-pnl");
    expect(params.get("symbols")).toBe("BTCUSDT");
    expect(params.get("side")).toBe("long");
    expect(params.get("limit")).toBeNull();
    expect(params.get("offset")).toBeNull();
    expect(params.get("from")).toBeNull();
  });
});
