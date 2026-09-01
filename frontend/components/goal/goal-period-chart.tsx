"use client";

import { useMemo, useState } from "react";

import type {
  GoalPeriodAnalytics,
  GoalProfitBucket,
} from "@/lib/goal-types";

type Resolution = "day" | "week" | "month";

const WIDTH = 720;
const HEIGHT = 176;
const PLOT_TOP = 12;
const PLOT_BOTTOM = 126;
const PLOT_LEFT = 24;
const PLOT_RIGHT = 696;

function money(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function shortLabel(period: string, resolution: Resolution): string {
  if (resolution === "day") {
    const [, month, day] = period.split("-");
    return `${month}/${day}`;
  }
  if (resolution === "week") return period.replace(/^\d{4}-/, "");
  return period;
}

function bucketsFor(
  analytics: GoalPeriodAnalytics,
  resolution: Resolution,
): GoalProfitBucket[] {
  if (resolution === "day") return analytics.daily;
  if (resolution === "week") return analytics.weekly;
  return analytics.monthly;
}

export function GoalPeriodChart({
  analytics,
}: {
  analytics: GoalPeriodAnalytics;
}) {
  const [resolution, setResolution] = useState<Resolution>("day");
  const buckets = bucketsFor(analytics, resolution);
  const geometry = useMemo(() => {
    const values = buckets.map((bucket) => bucket.net_profit);
    let maximum = Math.max(0, ...values);
    let minimum = Math.min(0, ...values);
    if (maximum === minimum) {
      maximum = 1;
      minimum = -1;
    }
    const spread = maximum - minimum;
    const y = (value: number) =>
      PLOT_TOP + ((maximum - value) / spread) * (PLOT_BOTTOM - PLOT_TOP);
    const x = (index: number) =>
      buckets.length <= 1
        ? WIDTH / 2
        : PLOT_LEFT + (index / (buckets.length - 1)) * (PLOT_RIGHT - PLOT_LEFT);
    return { x, y, zero: y(0) };
  }, [buckets]);
  const total = buckets.reduce((sum, bucket) => sum + bucket.net_profit, 0);
  const labelInterval = Math.max(1, Math.ceil(buckets.length / 6));

  return (
    <section className="border border-[#2A2620] bg-[#161411] p-4" aria-labelledby="goal-profit-heading">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[#2A2620] pb-3">
        <div>
          <h2 id="goal-profit-heading" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
            Account profit
          </h2>
          <p className="mt-1 text-xs text-[#8E8778]">
            Futures equity change, less deposits, withdrawals, and futures transfers.
          </p>
        </div>
        <div className="flex border border-[#2A2620]" aria-label="Profit bucket interval">
          {(["day", "week", "month"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={resolution === item}
              onClick={() => setResolution(item)}
              className={`border-r border-[#2A2620] px-3 py-1.5 text-xs capitalize last:border-r-0 ${
                resolution === item
                  ? "bg-[#1D1A16] text-[#C2A36B]"
                  : "bg-[#0F0E0C] text-[#8E8778]"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {!analytics.available ? (
        <p className="py-8 text-sm text-[#8E8778]">
          Period analytics unavailable: {analytics.reason ?? "unknown"}.
        </p>
      ) : buckets.length === 0 ? (
        <p className="py-8 text-sm text-[#8E8778]">No equity snapshots in this period.</p>
      ) : (
        <>
          <div className="mt-4 overflow-x-auto">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label={`${resolution} cash-flow-adjusted account profit bars`}
              className="h-44 min-w-[560px] w-full"
            >
              <line
                x1={PLOT_LEFT}
                x2={PLOT_RIGHT}
                y1={geometry.zero}
                y2={geometry.zero}
                stroke="#2A2620"
                strokeWidth="1"
              />
              {buckets.map((bucket, index) => {
                const x = geometry.x(index);
                const showLabel =
                  index === 0 || index === buckets.length - 1 || index % labelInterval === 0;
                return (
                  <g key={`${resolution}-${bucket.period}`}>
                    <line
                      x1={x}
                      x2={x}
                      y1={geometry.zero}
                      y2={geometry.y(bucket.net_profit)}
                      stroke={bucket.net_profit < 0 ? "#C96A55" : "#C2A36B"}
                      strokeWidth="2"
                    >
                      <title>{`${bucket.period}: ${money(bucket.net_profit)}`}</title>
                    </line>
                    {showLabel && (
                      <text
                        x={x}
                        y="154"
                        textAnchor="middle"
                        fill="#8E8778"
                        fontSize="10"
                        fontFamily="ui-monospace, monospace"
                      >
                        {shortLabel(bucket.period, resolution)}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="flex items-baseline justify-between border-t border-[#2A2620] pt-3 text-xs text-[#8E8778]">
            <span className="capitalize">{resolution} buckets</span>
            <span className="font-mono tabular-nums text-[#EDE7DB]">Total {money(total)}</span>
          </div>
        </>
      )}
    </section>
  );
}
