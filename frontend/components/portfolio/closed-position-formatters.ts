export const CLOSED_POSITION_PNL_BASIS = "MEXC-reported closed-position PnL";
export const CLOSED_POSITION_FEE_UNAVAILABLE =
  "Fee-net PnL unavailable — exchange fee/funding ledger not reconciled in Phase 1";
export const CLOSED_POSITION_HISTORY_SCOPE = "History scope: stored closed positions";
export const CLOSED_POSITION_HISTORY_UNKNOWN = "Completeness: unknown";
export const CLOSED_POSITION_HISTORY_PHASE2 = "Full history sync not implemented until Phase 2";
export const CLOSED_POSITION_ANALYTICS_ERROR =
  "Closed-position analytics could not load. No exchange action was taken. Try again.";

const NUMBER_FORMAT = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const COUNT_FORMAT = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

export function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return COUNT_FORMAT.format(value);
}

export function formatUsdtMoney(
  value: number | null | undefined,
  options: { signed?: boolean; dollarStyle?: boolean } = {},
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 && options.signed ? "+" : value < 0 ? "−" : "";
  const magnitude = NUMBER_FORMAT.format(Math.abs(value));
  const prefix = options.dollarStyle ? "$" : "";
  return `${sign}${prefix}${magnitude} USDT`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${NUMBER_FORMAT.format(value)}%`;
}

export function formatRatio(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function formatMinutes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 60) return `${Math.round(value)} min`;
  if (value < 60 * 24) return `${(value / 60).toFixed(1)} hr`;
  return `${(value / (60 * 24)).toFixed(1)} d`;
}

export function readableReason(reason: string | null | undefined): string {
  if (!reason) return "reason unavailable";
  return reason.replaceAll("_", " ");
}

export function pnlToneClass(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-foreground";
  return value > 0 ? "text-profit" : "text-loss";
}
