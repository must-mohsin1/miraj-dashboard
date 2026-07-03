"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { EquityCurvePoint } from "@/lib/types";

/**
 * EquityCurve — Client Component.
 *
 * Renders a recharts area chart of the portfolio's total value over time,
 * built from PortfolioSnapshot history. The gradient fill under the line
 * transitions from emerald (top) to transparent (bottom) to match the dark
 * theme.
 *
 * Tooltip shows the date and the portfolio value at that point.
 */

interface EquityCurveProps {
  points: EquityCurvePoint[];
}

const TOOLTIP_STYLE = {
  backgroundColor: "#0f172a",
  border: "1px solid #1e293b",
  borderRadius: "0.5rem",
  color: "#e2e8f0",
  fontSize: "0.75rem",
} as const;

function formatDate(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "2-digit",
  });
}

function formatDateTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

interface TooltipPayloadItem {
  payload: { timestamp: string; total_value: number };
}

function EquityTooltip({ active, payload }: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <div className="font-medium text-slate-100">
        {formatDateTime(point.timestamp)}
      </div>
      <div className="mt-0.5 text-emerald-400">
        ${point.total_value.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </div>
    </div>
  );
}

export function EquityCurve({ points }: EquityCurveProps) {
  if (!points || points.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No equity history yet. The curve will populate as portfolio snapshots
        are recorded on each refresh.
      </div>
    );
  }

  const data = useMemo(
    () =>
      points.map((p) => ({
        timestamp: p.timestamp,
        total_value: p.total_value,
      })),
    [points],
  );

  // Determine if the overall trend is positive or negative for gradient colour.
  const firstVal = points[0]?.total_value ?? 0;
  const lastVal = points[points.length - 1]?.total_value ?? 0;
  const isPositive = lastVal >= firstVal;
  const lineColor = isPositive ? "#10b981" : "#f87171"; // emerald-500 / red-400
  const gradId = isPositive ? "equityGradientUp" : "equityGradientDown";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="mb-3 text-sm font-medium text-slate-300">
        Equity Curve
      </h3>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
          >
            <defs>
              <linearGradient id="equityGradientUp" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="equityGradientDown" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f87171" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#f87171" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#1e293b"
              vertical={false}
            />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatDate}
              tick={{ fill: "#64748b", fontSize: 11 }}
              axisLine={{ stroke: "#1e293b" }}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              tick={{ fill: "#64748b", fontSize: 11 }}
              axisLine={{ stroke: "#1e293b" }}
              tickLine={false}
              width={56}
              tickFormatter={(v: number) =>
                `$${v.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}`
              }
            />
            <Tooltip
              content={<EquityTooltip />}
            />
            <Area
              type="monotone"
              dataKey="total_value"
              stroke={lineColor}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              dot={false}
              activeDot={{ r: 4, fill: lineColor, stroke: "#0f172a", strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default EquityCurve;
