"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { EquityCurveMarker, EquityCurvePoint } from "@/lib/types";

/**
 * EquityCurve — Client Component.
 *
 * Futures wallet equity over time (never spot totals). Optional markers show
 * external capital events (deposit / withdrawal / futures transfer).
 * INK & OXIDE tokens only (no Tailwind slate palette).
 */

interface EquityCurveProps {
  points: EquityCurvePoint[];
  markers?: EquityCurveMarker[];
  basis?: string | null;
  settlementAsset?: string | null;
  unavailableReason?: string | null;
}

const TOOLTIP_STYLE = {
  backgroundColor: "#161411",
  border: "1px solid #2A2620",
  borderRadius: "0",
  color: "#EDE7DB",
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

function markerLabel(entryType: string): string {
  if (entryType === "deposit") return "Deposit";
  if (entryType === "withdrawal") return "Withdrawal";
  if (entryType === "futures_transfer") return "Futures transfer";
  return entryType.replaceAll("_", " ");
}

function nearestEquity(
  points: EquityCurvePoint[],
  timestamp: string,
): number | null {
  if (!points.length) return null;
  const target = new Date(timestamp).getTime();
  if (Number.isNaN(target)) return points[points.length - 1]?.total_value ?? null;
  let best = points[0];
  let bestDist = Math.abs(new Date(best.timestamp).getTime() - target);
  for (const p of points) {
    const dist = Math.abs(new Date(p.timestamp).getTime() - target);
    if (dist < bestDist) {
      best = p;
      bestDist = dist;
    }
  }
  return best.total_value;
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
      <div className="font-medium text-[#EDE7DB]">
        {formatDateTime(point.timestamp)}
      </div>
      <div className="mt-0.5 font-mono tabular-nums text-[#6CA98F]">
        ${point.total_value.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </div>
      <div className="mt-0.5 text-[10px] text-[#8E8778]">Futures wallet equity</div>
    </div>
  );
}

export function EquityCurve({
  points,
  markers = [],
  basis,
  settlementAsset,
  unavailableReason,
}: EquityCurveProps) {
  if (!points || points.length === 0) {
    const reason = unavailableReason ? unavailableReason.replaceAll("_", " ") : "no account equity data";
    return (
      <div className="border border-[#2A2620] bg-[#161411] p-8 text-center text-sm text-[#8E8778]">
        <div>Account equity unavailable — {reason}</div>
        <div className="mt-1 text-xs text-[#8E8778]">
          Futures wallet equity history is missing. Spot balances are not account equity for this curve.
        </div>
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

  const chartMarkers = useMemo(
    () =>
      markers.map((m) => ({
        ...m,
        y: nearestEquity(points, m.timestamp) ?? points[points.length - 1]?.total_value ?? 0,
      })),
    [markers, points],
  );

  const firstVal = points[0]?.total_value ?? 0;
  const lastVal = points[points.length - 1]?.total_value ?? 0;
  const isPositive = lastVal >= firstVal;
  const lineColor = isPositive ? "#6CA98F" : "#C96A55";
  const gradId = isPositive ? "equityGradientUp" : "equityGradientDown";

  const basisLabel =
    basis === "futures_equity"
      ? `Futures equity${settlementAsset ? ` (${settlementAsset})` : ""} — spot not included`
      : basis === "account_snapshot"
        ? "Account snapshot"
        : "Account equity data";

  return (
    <div className="border border-[#2A2620] bg-[#161411] p-4">
      <h3 className="mb-1 text-sm font-medium text-[#EDE7DB]">
        Account Equity Curve
      </h3>
      <div className="mb-3 text-xs text-[#8E8778]">{basisLabel}</div>
      {chartMarkers.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-3 text-[11px] text-[#8E8778]">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 bg-sky-400" /> Deposit / transfer in
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 bg-amber-400" /> Withdrawal / transfer out
          </span>
        </div>
      )}
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
          >
            <defs>
              <linearGradient id="equityGradientUp" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6CA98F" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#6CA98F" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="equityGradientDown" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#C96A55" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#C96A55" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#2A2620"
              vertical={false}
            />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatDate}
              tick={{ fill: "#8E8778", fontSize: 11 }}
              axisLine={{ stroke: "#2A2620" }}
              tickLine={false}
              minTickGap={40}
            />
            <YAxis
              tick={{ fill: "#8E8778", fontSize: 11 }}
              axisLine={{ stroke: "#2A2620" }}
              tickLine={false}
              width={56}
              tickFormatter={(v: number) =>
                `$${v.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}`
              }
            />
            <Tooltip content={<EquityTooltip />} />
            <Area
              type="monotone"
              dataKey="total_value"
              stroke={lineColor}
              strokeWidth={2}
              fill={`url(#${gradId})`}
              dot={false}
              activeDot={{ r: 4, fill: lineColor, stroke: "#0F0E0C", strokeWidth: 2 }}
            />
            {chartMarkers.map((m) => {
              const inflow = (m.signed_amount ?? 0) >= 0;
              const fill = inflow ? "#38bdf8" : "#fbbf24";
              return (
                <ReferenceDot
                  key={`${m.entry_type}-${m.timestamp}-${m.exchange_entry_id ?? ""}`}
                  x={m.timestamp}
                  y={m.y}
                  r={5}
                  fill={fill}
                  stroke="#0F0E0C"
                  strokeWidth={1}
                  ifOverflow="extendDomain"
                />
              );
            })}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {chartMarkers.length > 0 && (
        <ul className="mt-3 max-h-28 space-y-1 overflow-y-auto text-[11px] text-[#8E8778]">
          {chartMarkers.map((m) => (
            <li key={`legend-${m.entry_type}-${m.timestamp}-${m.exchange_entry_id ?? ""}`}>
              <span className="text-[#EDE7DB]">{formatDateTime(m.timestamp)}</span>
              {" · "}
              {markerLabel(m.entry_type)}
              {typeof m.signed_amount === "number" && (
                <>
                  {" "}
                  <span className="font-mono tabular-nums">
                    {m.signed_amount >= 0 ? "+" : ""}
                    ${m.signed_amount.toFixed(2)}
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default EquityCurve;
