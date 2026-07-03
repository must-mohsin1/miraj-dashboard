"use client";

import { useMemo } from "react";
import {
  Cell,
  Label,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { AllocationItem } from "@/lib/types";

/**
 * AllocationPie — Client Component.
 *
 * Renders a recharts donut/pie chart of the current portfolio's asset
 * allocation by USD value. Each slice is an asset, with percentage labels
 * and dark-theme colours. Hovering shows asset + USD value + percentage.
 */

interface AllocationPieProps {
  items: AllocationItem[];
}

/** Dark-theme palette for pie slices. */
const PIE_COLORS = [
  "#10b981", // emerald-500
  "#3b82f6", // blue-500
  "#a855f7", // purple-500
  "#f59e0b", // amber-500
  "#ec4899", // pink-500
  "#14b8a6", // teal-500
  "#6366f1", // indigo-500
  "#f97316", // orange-500
  "#84cc16", // lime-500
  "#06b6d4", // cyan-500
  "#8b5cf6", // violet-500
  "#ef4444", // red-500
];

interface TooltipPayloadEntry {
  payload: AllocationItem & { fill: string };
}

function AllocationTooltip({ active, payload }: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const entry = payload[0]?.payload;
  if (!entry) return null;
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/95 px-3 py-2 text-xs shadow-lg">
      <div className="flex items-center gap-1.5 font-medium text-slate-100">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: entry.fill }}
        />
        {entry.asset}
      </div>
      <div className="mt-0.5 text-emerald-400">
        ${entry.usd_value.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </div>
      <div className="text-slate-400">{entry.percentage.toFixed(2)}%</div>
    </div>
  );
}

export function AllocationPie({ items }: AllocationPieProps) {
  const data = useMemo(
    () =>
      items.map((item, i) => ({
        ...item,
        fill: PIE_COLORS[i % PIE_COLORS.length],
      })),
    [items],
  );

  if (!items || items.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No allocation data. Connect your exchange and refresh to see your asset
        breakdown.
      </div>
    );
  }

  const totalUsd = items.reduce((sum, i) => sum + i.usd_value, 0);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-medium text-slate-300">
        Asset Allocation
      </h3>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="usd_value"
              nameKey="asset"
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              paddingAngle={2}
              stroke="#0f172a"
              strokeWidth={1}
            >
              {data.map((entry, i) => (
                <Cell
                  key={`cell-${i}`}
                  fill={entry.fill}
                  stroke="#0f172a"
                  strokeWidth={1}
                />
              ))}
              <Label
                position="center"
                content={({ viewBox }) => {
                  if (!viewBox || !("cx" in viewBox) || !("cy" in viewBox)) {
                    return null;
                  }
                  const { cx, cy } = viewBox as { cx: number; cy: number };
                  return (
                    <text
                      x={cx}
                      y={cy - 8}
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="fill-slate-100"
                      style={{ fontSize: "0.7rem", fontWeight: 600 }}
                    >
                      Total
                    </text>
                  );
                }}
              />
            </Pie>
            <Tooltip content={<AllocationTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Legend table */}
      <div className="mt-3 space-y-1">
        {data.map((item, i) => (
          <div
            key={item.asset}
            className="flex items-center justify-between rounded px-2 py-1 text-xs transition-colors hover:bg-slate-800/40"
          >
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: item.fill }}
              />
              <span className="font-medium text-slate-200">{item.asset}</span>
            </div>
            <div className="flex items-center gap-3 tabular-nums">
              <span className="text-slate-300">
                ${item.usd_value.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
              <span className="w-12 text-right text-slate-400">
                {item.percentage.toFixed(1)}%
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 border-t border-slate-800 pt-2 text-right text-xs text-slate-500">
        Total: ${totalUsd.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </div>
    </div>
  );
}

export default AllocationPie;
