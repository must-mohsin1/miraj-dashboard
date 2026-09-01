import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { GoalNowResponse } from "@/lib/goal-types";
import { GoalPlanForm } from "@/components/goal/goal-plan-form";
import { GoalPeriodChart } from "@/components/goal/goal-period-chart";

export const dynamic = "force-dynamic";

function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function percent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export default async function GoalPage() {
  const token = await getAccessToken();
  let desk: GoalNowResponse | null = null;
  if (token) {
    try {
      desk = await serverFetch<GoalNowResponse>("/api/v1/goal/now?exchange=mexc", token);
    } catch {
      desk = null;
    }
  }

  const monthLabel = desk
    ? new Date(Date.UTC(desk.period_year, desk.period_month - 1, 1)).toLocaleString("en-US", {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      })
    : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <header className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          Goal {monthLabel ? `· ${monthLabel}` : ""}
        </p>
        <h1 className="font-verdict text-4xl text-[#EDE7DB] sm:text-5xl">
          {desk?.display ?? "Sign in to set a monthly goal."}
        </h1>
        <p className="max-w-xl text-sm text-[#8E8778]">
          Progress is cash-flow-adjusted futures equity for this month. Deposits are not profit.
          Closed-trade PnL is not the goal.
        </p>
      </header>

      {desk?.goal && !desk.progress.available && (
        <p className="border border-[#2A2620] bg-[#161411] p-4 text-sm text-[#8E8778]">
          Account return unavailable: {desk.progress.reason ?? "unknown"}.
        </p>
      )}

      {desk && (
        <section className="grid gap-4 sm:grid-cols-3" aria-label="Goal progress">
          <div className="border border-[#2A2620] bg-[#161411] p-4">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#8E8778]">Return</p>
            <p className="mt-2 font-mono text-2xl text-[#EDE7DB]">
              {desk.progress.return_pct == null ? "—" : `${desk.progress.return_pct.toFixed(2)}%`}
            </p>
            <p className="mt-1 text-xs text-[#8E8778]">
              Target {desk.goal ? `${desk.goal.target_return_pct}%` : "not set"}
            </p>
          </div>
          <div className="border border-[#2A2620] bg-[#161411] p-4">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#8E8778]">Net profit</p>
            <p className="mt-2 font-mono text-2xl text-[#EDE7DB]">{money(desk.progress.net_profit)}</p>
            <p className="mt-1 text-xs text-[#8E8778]">Remaining {money(desk.remaining_usd)}</p>
          </div>
          <div className="border border-[#2A2620] bg-[#161411] p-4">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[#8E8778]">Days left</p>
            <p className="mt-2 font-mono text-2xl text-[#EDE7DB]">{desk.days_left}</p>
            <p className="mt-1 text-xs text-[#8E8778]">
              As of {desk.progress.as_of ?? "—"}
            </p>
          </div>
        </section>
      )}

      {desk && <GoalPeriodChart analytics={desk.period_analytics} />}

      {desk && (
        <section className="border border-[#2A2620] bg-[#161411] p-4" aria-labelledby="goal-year-heading">
          <div className="border-b border-[#2A2620] pb-3">
            <h2 id="goal-year-heading" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
              {desk.period_year} archive
            </h2>
            <p className="mt-1 text-xs text-[#8E8778]">Closed months show realized return against the saved target.</p>
          </div>
          <div className="overflow-x-auto">
            <div className="grid min-w-[840px] grid-cols-12 border-l border-[#2A2620]">
              {Array.from({ length: 12 }, (_, index) => {
                const month = index + 1;
                const archived = desk.year_archive.find((row) => row.period_month === month);
                const label = new Date(Date.UTC(desk.period_year, index, 1)).toLocaleString("en-US", {
                  month: "short",
                  timeZone: "UTC",
                });
                return (
                  <div key={month} className="min-h-24 border-r border-[#2A2620] p-2">
                    <p className="text-[10px] uppercase tracking-[0.12em] text-[#8E8778]">{label}</p>
                    {archived ? (
                      <div className="mt-3 space-y-1 font-mono text-[11px] tabular-nums">
                        <p className="text-[#EDE7DB]">{percent(archived.realized_return_pct)}</p>
                        <p className="text-[#8E8778]">vs {archived.target_return_pct.toFixed(2)}%</p>
                      </div>
                    ) : month === desk.period_month ? (
                      <p className="mt-3 text-[11px] text-[#C2A36B]">Current</p>
                    ) : (
                      <p className="mt-3 font-mono text-[11px] text-[#8E8778]">—</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {desk && (
        <section className="grid border border-[#2A2620] bg-[#161411] sm:grid-cols-[1fr_2fr]" aria-labelledby="goal-pace-heading">
          <div className="border-b border-[#2A2620] p-4 sm:border-b-0 sm:border-r">
            <h2 id="goal-pace-heading" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
              MTD ×12
            </h2>
            <p className="mt-3 font-mono text-2xl tabular-nums text-[#EDE7DB]">
              {desk.progress.return_pct == null ? "—" : percent(desk.progress.return_pct * 12)}
            </p>
            <p className="mt-1 text-xs text-[#8E8778]">Month-to-date return × 12, not annualized by days elapsed</p>
          </div>
          <div className="flex items-center p-4 text-sm text-[#8E8778]">
            Compounding the target is not a forecast. This number is a linear comparison only.
          </div>
        </section>
      )}

      <GoalPlanForm initial={desk} />

      {desk?.goal && (
        <p className="text-xs text-[#8E8778]">
          Redeem {desk.goal.redeem_pct}% / reinvest {desk.goal.reinvest_pct}% of this month's profit
          is a plan, not a withdrawal.
        </p>
      )}
    </div>
  );
}
