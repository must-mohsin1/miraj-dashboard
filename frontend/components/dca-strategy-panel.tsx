import {
  AlertTriangle,
  CheckCircle2,
  DollarSign,
  Layers,
  ListChecks,
  ShieldCheck,
  Target,
  TrendingDown,
  XCircle,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type {
  BMSB,
  QqeSignals,
  TradePlanFull,
} from "@/lib/types";

/**
 * DcaStrategyPanel — Server Component.
 *
 * Surfaces the "hidden" DCA data that the backend already returns inside the
 * full `trade_plan` object but the flat TradePlan card does not render:
 *
 *   1. RSI Three-Entry System (current RSI + 3 entry ladder)
 *   2. DCA Strategy rules (checklist)
 *   3. Risk Management rules (icon list, "0.5-1% risk" highlighted,
 *      "Withdraw capital at 2x" badged)
 *   4. Confirmations Met (grouped by confluence category)
 *   5. DCA Validation Checklist (5 boolean checks → DCA SAFE / NOT ADVISED
 *      badge)
 *
 * Dark theme, compact layout. Follows the existing Card-with-border-slate-800
 * pattern used by QqeSignalPanel / StructurePanel.
 */

// ── Props ──────────────────────────────────────────────────────────────────

interface DcaStrategyPanelProps {
  /** The full nested trade_plan object from the scan response. */
  tradePlan: Record<string, unknown> | null;
  /** Raw confluence score (0–30). */
  confluenceScore: number;
  /** Per-TF QQE signals (daily/4h/1h). */
  qqeSignals: QqeSignals | null;
  /** Simplified per-TF indicators dict (rsi, bb_squeeze, macd_cross, ...). */
  indicators: Record<string, unknown> | null;
  /** Bull Market Support Band summary. */
  bmsb: BMSB | null;
  /** "LONG" | "SHORT" | null. When null we fall back to trade_plan.direction. */
  direction: string | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Coerce the raw trade_plan dict into the typed shape (best-effort). */
function asTradePlanFull(
  raw: Record<string, unknown> | null,
): TradePlanFull | null {
  if (!raw || typeof raw !== "object") return null;
  return raw as unknown as TradePlanFull;
}

/** Safely read a per-TF indicator sub-object. */
function tfIndicators(
  indicators: Record<string, unknown> | null,
  tf: "daily" | "4h" | "1h",
): Record<string, unknown> | null {
  if (!indicators) return null;
  const v = indicators[tf];
  return v && typeof v === "object" ? (v as Record<string, unknown>) : null;
}

/** Is the daily QQE trend aligned for the given direction? */
function isQqeAligned(
  signals: QqeSignals | null,
  direction: string,
): boolean {
  if (!signals) return false;
  const daily = signals.daily;
  if (!daily) return false;
  const isLong = direction.toUpperCase() === "LONG";
  return isLong
    ? daily.trend === "GREEN"
    : daily.trend === "RED";
}

/** Is the daily Bollinger Band NOT in a squeeze? */
function isBbNotSqueezing(
  indicators: Record<string, unknown> | null,
): boolean {
  const daily = tfIndicators(indicators, "daily");
  if (!daily) return false;
  return daily.bb_squeeze !== true;
}

/** Does a valid OTE entry zone exist with real low/high? */
function hasValidEntryZone(tp: TradePlanFull | null): boolean {
  const z = tp?.entry_zone;
  if (!z) return false;
  return (
    z.low != null && z.high != null && !Number.isNaN(z.low) && !Number.isNaN(z.high)
  );
}

/** Is price above the Bull Market Support Band (valid for longs only)? */
function isBmsbAboveBand(bmsb: BMSB | null): boolean {
  if (!bmsb) return false;
  return bmsb.status === "above";
}

/** Map a confluence category key to a human label. */
const CATEGORY_LABELS: Record<string, string> = {
  regime: "Regime",
  location: "Location",
  confirmation: "Confirmation",
  volume_retest: "Volume / Retest",
  risk: "Risk",
};

/** The canonical order to render confirmation categories in. */
const CATEGORY_ORDER = ["regime", "location", "confirmation", "volume_retest", "risk"];

// ── Component ───────────────────────────────────────────────────────────────

export function DcaStrategyPanel({
  tradePlan,
  confluenceScore,
  qqeSignals,
  indicators,
  bmsb,
  direction,
}: DcaStrategyPanelProps) {
  const tp = asTradePlanFull(tradePlan);
  const dir = (direction ?? (tp as unknown as { direction?: string })?.direction ?? "LONG").toUpperCase();
  const isLong = dir !== "SHORT";

  // ── Block 1: RSI Three-Entry System ──
  const rsiSystem = tp?.rsi_entry_system ?? null;
  const currentRsi = rsiSystem?.current_rsi ?? null;
  const entries = rsiSystem?.entries ?? [];

  // ── Block 2: DCA Strategy ──
  const dcaRules = tp?.dca_strategy ?? [];

  // ── Block 3: Risk Management ──
  const riskRules = tp?.risk_management ?? [];

  // ── Block 4: Confirmations Met ──
  const confirmations = tp?.confirmations_met ?? [];

  // ── Block 5: DCA Validation Checklist ──
  const checks = {
    confluence: confluenceScore >= 10,
    qqeAligned: isQqeAligned(qqeSignals, dir),
    bbNotSqueezing: isBbNotSqueezing(indicators),
    validZone: hasValidEntryZone(tp),
    bmsbAbove: isBmsbAboveBand(bmsb),
  };
  const allPassed = Object.values(checks).every(Boolean);

  // Empty state: no nested data at all.
  const hasAnyData =
    rsiSystem != null ||
    dcaRules.length > 0 ||
    riskRules.length > 0 ||
    confirmations.length > 0;

  if (!hasAnyData) {
    return (
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-sm font-medium text-slate-300">
              DCA Strategy
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-500">
            No DCA / trade-plan data available for this analysis.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-sm font-medium text-slate-300">
              DCA Strategy
            </CardTitle>
          </div>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
              isLong
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-700/50"
                : "bg-red-500/10 text-red-400 border-red-700/50",
            )}
          >
            {isLong ? "▲ LONG" : "▼ SHORT"} ladder
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* ── 1. RSI Three-Entry System ── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Target className="h-4 w-4 text-emerald-400" />
            <h4 className="text-sm font-medium text-slate-300">
              RSI Three-Entry System
            </h4>
          </div>
          <div className="mb-3 flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
            <span className="text-xs uppercase tracking-wide text-slate-500">
              Current RSI
            </span>
            <span
              className={cn(
                "text-lg font-bold tabular-nums",
                currentRsi == null
                  ? "text-slate-600"
                  : currentRsi <= (isLong ? 30 : 80)
                    ? "text-emerald-400"
                    : currentRsi >= (isLong ? 70 : 80)
                      ? "text-amber-400"
                      : "text-slate-100",
              )}
            >
              {currentRsi != null ? currentRsi.toFixed(1) : "—"}
            </span>
            {isLong ? null : (
              <span className="ml-auto text-[10px] text-slate-500">
                biggest entry at RSI 95
              </span>
            )}
          </div>
          {entries.length > 0 ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {entries.map((e, i) => {
                const isSafest = e.position_size.includes("60");
                return (
                  <div
                    key={i}
                    className={cn(
                      "flex flex-col gap-1 rounded-lg border p-3",
                      isSafest
                        ? "border-emerald-700/50 bg-emerald-500/5"
                        : "border-slate-800 bg-slate-950/40",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-slate-300">
                        {e.entry}
                      </span>
                      {isSafest && (
                        <span className="rounded-full border border-emerald-700/50 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-bold text-emerald-400">
                          SAFEST ZONE
                        </span>
                      )}
                    </div>
                    <span
                      className={cn(
                        "text-base font-bold tabular-nums",
                        isSafest ? "text-emerald-400" : "text-slate-100",
                      )}
                    >
                      RSI {e.rsi_target}
                    </span>
                    <span className="text-xs text-slate-400">
                      {e.position_size} size
                    </span>
                    <span className="text-[10px] text-slate-600">
                      {e.trigger}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              RSI entry ladder not available.
            </p>
          )}
        </section>

        {/* ── 2. DCA Strategy ── */}
        {dcaRules.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-emerald-400" />
              <h4 className="text-sm font-medium text-slate-300">
                DCA Strategy
              </h4>
            </div>
            <ul className="space-y-2">
              {dcaRules.map((rule, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 rounded-md border border-slate-800/60 bg-slate-950/40 px-3 py-2"
                >
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                  <span className="text-sm text-slate-300">{rule}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ── 3. Risk Management ── */}
        {riskRules.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              <h4 className="text-sm font-medium text-slate-300">
                Risk Management
              </h4>
            </div>
            <ul className="space-y-2">
              {riskRules.map((rule, i) => {
                const isRiskRule = /0\.5-?1%|risk.*per.*trade/i.test(rule);
                const isWithdrawRule =
                  /withdraw|doubles|house.*money|2x/i.test(rule);
                const isInvalidation = /invalidation/i.test(rule);
                const Icon = isInvalidation ? AlertTriangle : DollarSign;
                return (
                  <li
                    key={i}
                    className={cn(
                      "flex items-start gap-2 rounded-md border px-3 py-2",
                      isRiskRule
                        ? "border-emerald-700/50 bg-emerald-500/5"
                        : "border-slate-800/60 bg-slate-950/40",
                    )}
                  >
                    <Icon
                      className={cn(
                        "mt-0.5 h-3.5 w-3.5 shrink-0",
                        isRiskRule
                          ? "text-emerald-400"
                          : isInvalidation
                            ? "text-amber-400"
                            : "text-slate-500",
                      )}
                    />
                    <span
                      className={cn(
                        "text-sm",
                        isRiskRule
                          ? "font-medium text-emerald-300"
                          : "text-slate-300",
                      )}
                    >
                      {rule}
                    </span>
                    {isWithdrawRule && (
                      <span className="ml-auto shrink-0 rounded-full border border-amber-700/50 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold text-amber-400">
                        KEY RULE
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* ── 4. Confirmations Met ── */}
        {confirmations.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <h4 className="text-sm font-medium text-slate-300">
                Confirmations Met
              </h4>
              <span className="text-xs text-slate-500">
                ({confirmations.length})
              </span>
            </div>
            <ConfirmationsGrid confirmations={confirmations} />
          </section>
        )}

        {/* ── 5. DCA Validation Checklist ── */}
        <section className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-emerald-400" />
              <h4 className="text-sm font-medium text-slate-300">
                DCA Validation Checklist
              </h4>
            </div>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-bold",
                allPassed
                  ? "border-emerald-700/50 bg-emerald-500/10 text-emerald-400"
                  : "border-red-700/50 bg-red-500/10 text-red-400",
              )}
            >
              {allPassed ? "✅ DCA SAFE" : "❌ DCA NOT ADVISED"}
            </span>
          </div>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <ValidationRow
              label={`Confluence score ≥ 10/30 (${confluenceScore.toFixed(1)})`}
              passed={checks.confluence}
            />
            <ValidationRow
              label={`QQE aligned (${isLong ? "green for longs" : "red for shorts"})`}
              passed={checks.qqeAligned}
            />
            <ValidationRow
              label="BB NOT squeezing"
              passed={checks.bbNotSqueezing}
            />
            <ValidationRow
              label="Valid demand zone (entry_zone exists)"
              passed={checks.validZone}
            />
            <ValidationRow
              label="BMSB above band"
              passed={checks.bmsbAbove}
            />
          </ul>
        </section>
      </CardContent>
    </Card>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

/** A single validation row with a green ✅ / red ❌ marker. */
function ValidationRow({ label, passed }: { label: string; passed: boolean }) {
  return (
    <li className="flex items-center gap-2">
      {passed ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
      ) : (
        <XCircle className="h-4 w-4 shrink-0 text-red-400" />
      )}
      <span
        className={cn(
          "text-sm",
          passed ? "text-slate-300" : "text-slate-400 line-through",
        )}
      >
        {label}
      </span>
    </li>
  );
}

/**
 * Group the flat confirmations_met array (entries like "regime:btc_d_aligned")
 * by their category prefix and render one column per category.
 */
function ConfirmationsGrid({ confirmations }: { confirmations: string[] }) {
  const groups: Record<string, string[]> = {};
  for (const c of confirmations) {
    const idx = c.indexOf(":");
    const cat = idx > 0 ? c.slice(0, idx) : "other";
    const item = idx > 0 ? c.slice(idx + 1) : c;
    (groups[cat] ??= []).push(item);
  }

  // Render categories in canonical order; unknown categories go last.
  const orderedCats = [
    ...CATEGORY_ORDER.filter((c) => groups[c]),
    ...Object.keys(groups).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  if (orderedCats.length === 0) {
    return (
      <p className="text-xs text-slate-500">No confirmations recorded.</p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {orderedCats.map((cat) => (
        <div
          key={cat}
          className="rounded-md border border-slate-800/60 bg-slate-950/40 p-3"
        >
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            {CATEGORY_LABELS[cat] ?? cat}
          </p>
          <ul className="space-y-1">
            {groups[cat].map((item, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
                <span className="text-xs text-slate-300">
                  {item.replace(/_/g, " ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default DcaStrategyPanel;
