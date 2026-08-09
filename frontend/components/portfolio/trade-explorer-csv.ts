/**
 * CSV export for Trade Explorer current-page rows.
 * Pure helpers — no DOM. Callers attach the download.
 */

import type { TradeExplorerItem } from "@/components/portfolio/trade-explorer";

export const TRADE_EXPLORER_CSV_HEADERS = [
  "id",
  "symbol",
  "side",
  "size",
  "size_unit",
  "contract_size",
  "entry_price",
  "exit_price",
  "pnl",
  "pnl_percent",
  "currency_unit",
  "pnl_basis",
  "fee_status",
  "leverage",
  "open_time",
  "close_time",
  "duration_minutes",
  "close_reason",
  "unavailable_reasons",
] as const;

function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function cell(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "";
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function unavailableToString(
  reasons: TradeExplorerItem["unavailable_reasons"],
): string {
  if (!reasons) return "";
  if (Array.isArray(reasons)) return reasons.filter(Boolean).join("|");
  return Object.entries(reasons)
    .filter(([, v]) => Boolean(v))
    .map(([k]) => k)
    .join("|");
}

export function tradeExplorerItemsToCsv(items: TradeExplorerItem[]): string {
  const lines: string[] = [TRADE_EXPLORER_CSV_HEADERS.join(",")];
  for (const item of items) {
    const row = [
      cell(item.id),
      cell(item.symbol),
      cell(item.side),
      cell(item.size),
      cell(item.size_unit),
      cell(item.contract_size),
      cell(item.entry_price),
      cell(item.exit_price),
      cell(item.pnl),
      cell(item.pnl_percent),
      cell(item.currency_unit ?? "USDT"),
      cell(item.pnl_basis),
      cell(item.fee_status),
      cell(item.leverage),
      cell(item.open_time),
      cell(item.close_time),
      cell(item.duration_minutes),
      cell(item.close_reason),
      cell(unavailableToString(item.unavailable_reasons)),
    ].map(csvEscape);
    lines.push(row.join(","));
  }
  // Excel-friendly BOM + trailing newline
  return `\uFEFF${lines.join("\n")}\n`;
}

export function buildTradeExplorerCsvFilename(
  exchange?: string | null,
  now: Date = new Date(),
  scope: "page" | "filtered" = "page",
): string {
  const slug = (exchange || "trades").toLowerCase().replace(/[^a-z0-9_-]+/g, "-");
  const stamp = now.toISOString().slice(0, 19).replace(/[:T]/g, (c) => (c === "T" ? "-" : ""));
  const scopePart = scope === "filtered" ? "filtered-" : "";
  return `trade-explorer-${slug}-${scopePart}${stamp}.csv`;
}

/** Build query string for server full-filtered export (no pagination). */
export function buildTradeExplorerExportQuery(params: {
  timezone?: string;
  period?: string;
  sort?: string;
  from?: string;
  to?: string;
  symbols?: string;
  side?: string;
  leverage_min?: string;
  leverage_max?: string;
  duration_min_minutes?: string;
  duration_max_minutes?: string;
  close_reason?: string;
  pnl_min?: string;
  pnl_max?: string;
}): string {
  const search = new URLSearchParams();
  search.set("timezone", params.timezone || "UTC");
  search.set("period", params.period || "week");
  search.set("sort", params.sort || "-close_time");
  for (const key of [
    "from",
    "to",
    "symbols",
    "side",
    "leverage_min",
    "leverage_max",
    "duration_min_minutes",
    "duration_max_minutes",
    "close_reason",
    "pnl_min",
    "pnl_max",
  ] as const) {
    const value = params[key];
    if (typeof value === "string" && value.trim()) {
      search.set(key, value.trim());
    }
  }
  return search.toString();
}
