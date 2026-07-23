"use client";

import { useMemo } from "react";

import type { DailyPnlPoint } from "@/lib/types";

/**
 * PnlHeatmap — Client Component.
 *
 * Renders a GitHub-style calendar heatmap of daily PnL over the last 12
 * weeks. Each day is a cell coloured:
 *  - green (profit) with intensity by magnitude
 *  - red (loss) with intensity by magnitude
 *  - slate (no trades or flat)
 *
 * Built with plain CSS grid (no recharts) for performance and theme
 * consistency. Hovering a cell shows a tooltip with the date and PnL.
 */

interface PnlHeatmapProps {
  days: DailyPnlPoint[];
  timezone?: string;
}

const WEEKS = 12;
const DAYS_PER_WEEK = 7;

/** Map a PnL value to a background colour. */
function pnlColor(pnl: number | undefined, maxAbs: number): string {
  if (pnl === undefined) return "#1e293b"; // slate-800 — no trades
  if (pnl === 0) return "#334155"; // slate-700 — flat
  // Normalize intensity: 0 (small) → 1 (large)
  const intensity = maxAbs > 0 ? Math.min(1, Math.abs(pnl) / maxAbs) : 0.5;
  if (pnl > 0) {
    // Green scale: emerald-900 → emerald-400
    if (intensity > 0.75) return "#10b981";
    if (intensity > 0.5) return "#34d399";
    if (intensity > 0.25) return "#6ee7b7";
    return "#a7f3d0";
  } else {
    // Red scale: red-900 → red-400
    if (intensity > 0.75) return "#f87171";
    if (intensity > 0.5) return "#fca5a5";
    if (intensity > 0.25) return "#fda4af";
    return "#fecaca";
  }
}

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Build a 12-week grid ending today. Returns array of weeks, each 7 days. */
function buildGrid(
  days: DailyPnlPoint[],
): { date: string; pnl: number | undefined }[][] {
  // Map daily PnL points by date string for O(1) lookup.
  const pnlMap = new Map<string, number>();
  for (const d of days) {
    pnlMap.set(d.date, d.pnl);
  }

  // Find the max absolute PnL for intensity scaling (computed by caller).
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Align to the start of the current week (Sunday).
  const dayOfWeek = today.getDay(); // 0=Sun, 6=Sat
  const endOfGrid = new Date(today);
  endOfGrid.setDate(today.getDate() + (6 - dayOfWeek)); // upcoming Saturday

  const grid: { date: string; pnl: number | undefined }[][] = [];
  const totalDays = WEEKS * DAYS_PER_WEEK;

  // Start from the oldest day (totalDays - 1 before endOfGrid).
  const startDate = new Date(endOfGrid);
  startDate.setDate(endOfGrid.getDate() - totalDays + 1);

  for (let w = 0; w < WEEKS; w++) {
    const week: { date: string; pnl: number | undefined }[] = [];
    for (let d = 0; d < DAYS_PER_WEEK; d++) {
      const cellDate = new Date(startDate);
      cellDate.setDate(startDate.getDate() + w * 7 + d);
      const dateStr = cellDate.toISOString().slice(0, 10); // YYYY-MM-DD
      const pnl = pnlMap.get(dateStr);
      week.push({ date: dateStr, pnl });
    }
    grid.push(week);
  }

  return grid;
}

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const DAY_LABELS = ["", "Mon", "", "Wed", "", "Fri", ""];

export function PnlHeatmap({ days, timezone = "UTC" }: PnlHeatmapProps) {
  const maxAbs = useMemo(() => {
    if (days.length === 0) return 0;
    return Math.max(...days.map((d) => Math.abs(d.pnl)), 1);
  }, [days]);

  const grid = useMemo(() => buildGrid(days), [days]);

  // Compute month labels for the week columns.
  const monthLabels = useMemo(() => {
    const labels: { weekIndex: number; label: string }[] = [];
    let lastMonth = -1;
    grid.forEach((week, weekIndex) => {
      // Use the first day of the week.
      const firstCellDate = new Date(week[0].date + "T00:00:00");
      const month = firstCellDate.getMonth();
      if (month !== lastMonth) {
        labels.push({ weekIndex, label: MONTH_LABELS[month] });
        lastMonth = month;
      }
    });
    return labels;
  }, [grid]);

  const hasData = days.length > 0;

  if (!hasData) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No closed trades in this period. Daily PnL will appear on the calendar
        as positions close.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-300">
          P&amp;L Calendar — Last 12 Weeks ({timezone})
        </h3>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>Less</span>
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: pnlColor(undefined, maxAbs) }}
          />
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: pnlColor(maxAbs * 0.25, maxAbs) }}
          />
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: pnlColor(maxAbs * 0.5, maxAbs) }}
          />
          <span
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ backgroundColor: pnlColor(maxAbs, maxAbs) }}
          />
          <span>More</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="inline-flex gap-2">
          {/* Day labels column */}
          <div className="flex flex-col gap-1 pt-5">
            {DAY_LABELS.map((label, i) => (
              <div
                key={i}
                className="flex h-3.5 items-center text-[10px] text-slate-500"
              >
                {label}
              </div>
            ))}
          </div>

          {/* Weeks grid */}
          <div className="flex flex-col gap-1">
            {/* Month labels row */}
            <div className="relative mb-1 flex gap-1" style={{ height: 16 }}>
              {monthLabels.map(({ weekIndex, label }) => (
                <div
                  key={weekIndex}
                  className="absolute text-[10px] text-slate-500"
                  style={{
                    left: `calc(${weekIndex} * (0.5rem + 1px))`,
                  }}
                >
                  {label}
                </div>
              ))}
            </div>

            {/* Weeks (columns) */}
            <div className="flex gap-1">
              {grid.map((week, weekIdx) => (
                <div key={weekIdx} className="flex flex-col gap-1">
                  {week.map((cell, dayIdx) => {
                    const color = pnlColor(cell.pnl, maxAbs);
                    const tooltip = cell.pnl === undefined
                      ? `${formatDateLabel(cell.date)} — No trades`
                      : `${formatDateLabel(cell.date)} — ${
                          cell.pnl >= 0 ? "+" : ""
                        }$${cell.pnl.toFixed(2)}`;
                    return (
                      <div
                        key={dayIdx}
                        className="h-3.5 w-3.5 rounded-sm transition-transform hover:scale-125 hover:ring-1 hover:ring-slate-400"
                        style={{ backgroundColor: color }}
                        title={tooltip}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PnlHeatmap;
