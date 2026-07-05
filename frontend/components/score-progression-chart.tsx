"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import useSWR from "swr";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ScanChangesTimelineResponse } from "@/lib/types";

/**
 * ScoreProgressionChart — Client Component.
 *
 * Fetches `GET /api/v1/scan/{symbol}/changes` and renders a recharts line
 * chart of the confluence score over time:
 *   - X axis: scan timestamps
 *   - Y axis: confluence score (0–30)
 *   - Green reference line at y=20 (trade zone, ≥20)
 *   - Red reference line at y=10 (no trade, <10)
 *   - Each data dot is green (≥20), red (<10), or amber (10–19.9)
 *
 * Props:
 *   - symbol: the trading pair
 *   - token:  JWT for the SWR fetch (or null when unauthenticated)
 *   - height?: chart height in px (default 240)
 */

/** Fetcher used by SWR — attaches the Bearer token. */
async function fetcher<T>(url: string, token: string | null): Promise<T> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    const err = new Error(`GET ${url} failed: ${res.status} ${res.statusText}`) as Error & { status?: number };
    (err as { status?: number }).status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

interface ScoreProgressionChartProps {
  symbol: string;
  token: string | null;
  height?: number;
}

/** Pick a dot colour for a data point based on its confluence score. */
function dotColor(score: number | null | undefined): string {
  if (score == null) return "#64748b"; // slate-500
  if (score >= 20) return "#22c55e"; // green-500
  if (score < 10) return "#ef4444"; // red-500
  return "#f59e0b"; // amber-500
}

/** Format an ISO timestamp as "MM/DD HH:mm". */
function formatTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}

/** Custom recharts point — renders a coloured circle per data point. */
interface DotProps {
  cx?: number;
  cy?: number;
  payload?: ChartRow;
}

function ColouredDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload) return <g />;
  const fill = dotColor(payload.confluence_score);
  return (
    <circle
      cx={cx}
      cy={cy}
      r={4}
      fill={fill}
      stroke="#0f172a"
      strokeWidth={1.5}
    />
  );
}

interface ChartRow {
  timestamp: string;
  label: string;
  confluence_score: number | null;
  overall_score: number | null;
  direction: string | null;
  trade_decision: boolean | null;
}

/** Custom tooltip content for the chart. */
interface TooltipPayloadItem {
  payload?: ChartRow;
}
function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  if (!row) return null;
  const d = new Date(row.timestamp);
  const tsStr = Number.isNaN(d.getTime())
    ? row.timestamp
    : d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      });

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs shadow-xl">
      <p className="font-medium text-slate-300">{tsStr}</p>
      <p className="mt-1 text-slate-400">
        Score:{" "}
        <span
          className={cn(
            "font-semibold",
            row.confluence_score != null && row.confluence_score >= 20
              ? "text-emerald-400"
              : row.confluence_score != null && row.confluence_score < 10
              ? "text-red-400"
              : "text-amber-400",
          )}
        >
          {row.confluence_score != null
            ? row.confluence_score.toFixed(1)
            : "—"}
        </span>
        <span className="text-slate-500"> / 30</span>
      </p>
      {row.overall_score != null && (
        <p className="text-slate-400">
          Overall: <span className="font-medium text-slate-300">{row.overall_score.toFixed(1)}</span>
        </p>
      )}
      {row.direction && (
        <p className="text-slate-400">
          Direction:{" "}
          <span
            className={cn(
              "font-medium",
              row.direction === "LONG"
                ? "text-emerald-400"
                : row.direction === "SHORT"
                ? "text-red-400"
                : "text-slate-300",
            )}
          >
            {row.direction}
          </span>
        </p>
      )}
      {row.trade_decision != null && (
        <p className="text-slate-400">
          Trade:{" "}
          <span
            className={cn(
              "font-medium",
              row.trade_decision ? "text-emerald-400" : "text-slate-500",
            )}
          >
            {row.trade_decision ? "Yes" : "No"}
          </span>
        </p>
      )}
    </div>
  );
}

export function ScoreProgressionChart({
  symbol,
  token,
  height = 240,
}: ScoreProgressionChartProps) {
  const { data, error, isLoading } = useSWR<ScanChangesTimelineResponse>(
    token
      ? [`/api/v1/scan/${encodeURIComponent(symbol)}/changes?limit=50`, token]
      : null,
    ([url, tok]: [string, string | null]) => fetcher<ScanChangesTimelineResponse>(url, tok),
  );

  // Flatten score_progression → chart rows with a short tick label.
  const rows: ChartRow[] = useMemo(() => {
    if (!data?.score_progression) return [];
    return data.score_progression.map((p) => ({
      timestamp: p.timestamp,
      label: formatTick(p.timestamp),
      confluence_score: p.confluence_score,
      overall_score: p.overall_score,
      direction: p.direction,
      trade_decision: p.trade_decision,
    }));
  }, [data]);

  // ── Loading state ─────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────
  if (error) {
    const status = (error as Error & { status?: number }).status;
    if (status === 404) {
      return (
        <p className="text-xs text-slate-500" style={{ minHeight: height }}>
          No scan history for {symbol} yet — run a scan to start the
          progression.
        </p>
      );
    }
    return (
      <p className="text-xs text-slate-500" style={{ minHeight: height }}>
        Could not load score progression for {symbol}.
      </p>
    );
  }

  // ── Empty state: need at least 2 points to plot a line ───────────────
  if (rows.length < 2) {
    return (
      <p className="flex items-center justify-center text-xs text-slate-500" style={{ height }}>
        Need at least 2 scans to plot score progression.
      </p>
    );
  }

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={rows}
          margin={{ top: 8, right: 12, bottom: 4, left: -8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="label"
            stroke="#64748b"
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            interval="preserveStartEnd"
            minTickGap={20}
          />
          <YAxis
            domain={[0, 30]}
            ticks={[0, 5, 10, 15, 20, 25, 30]}
            stroke="#64748b"
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            width={36}
          />
          <Tooltip
            content={<ChartTooltip />}
            cursor={{ stroke: "#475569", strokeDasharray: "3 3" }}
          />
          {/* Trade zone reference line */}
          <ReferenceLine
            y={20}
            stroke="#22c55e"
            strokeDasharray="4 4"
            strokeOpacity={0.6}
            label={{
              value: "Trade (≥20)",
              fill: "#22c55e",
              fontSize: 10,
              position: "insideTopRight",
            }}
          />
          {/* No-trade zone reference line */}
          <ReferenceLine
            y={10}
            stroke="#ef4444"
            strokeDasharray="4 4"
            strokeOpacity={0.6}
            label={{
              value: "No trade (<10)",
              fill: "#ef4444",
              fontSize: 10,
              position: "insideBottomRight",
            }}
          />
          <Line
            type="monotone"
            dataKey="confluence_score"
            stroke="#22c55e"
            strokeWidth={2}
            dot={<ColouredDot />}
            activeDot={{ r: 6, fill: "#22c55e", stroke: "#0f172a", strokeWidth: 2 }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default ScoreProgressionChart;
