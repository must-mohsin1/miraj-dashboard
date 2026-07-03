"use client";

import { useEffect, useState, useCallback } from "react";

import type { Timeframe } from "@/lib/types";

/**
 * TimeframeSelector — a row of toggle buttons for chart timeframes.
 *
 * Lets the user switch the chart's OHLCV timeframe between 1m, 5m, 15m,
 * 1h, 4h, 1d, and 1w.  The selection is persisted to ``localStorage``
 * under ``miraj:chart:tf`` so it survives page reloads.
 *
 * On change, calls ``onTimeframeChange`` with the newly selected TF.
 */

const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
  { value: "1w", label: "1W" },
];

const STORAGE_KEY = "miraj:chart:tf";

function loadStoredTf(): Timeframe {
  if (typeof window === "undefined") return "1d";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v && TIMEFRAMES.some((t) => t.value === v)) return v as Timeframe;
  } catch {
    // localStorage may be disabled (private mode)
  }
  return "1d";
}

interface TimeframeSelectorProps {
  /** Currently selected timeframe. */
  timeframe: Timeframe;
  /** Called when the user picks a new timeframe. */
  onTimeframeChange: (tf: Timeframe) => void;
  /** Optional: disable the selector while data is loading. */
  disabled?: boolean;
}

export function TimeframeSelector({
  timeframe,
  onTimeframeChange,
  disabled = false,
}: TimeframeSelectorProps) {
  // Hydrate from localStorage on mount
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const stored = loadStoredTf();
    if (stored !== timeframe) {
      onTimeframeChange(stored);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClick = useCallback(
    (tf: Timeframe) => {
      if (disabled) return;
      try {
        window.localStorage.setItem(STORAGE_KEY, tf);
      } catch {
        // ignore
      }
      onTimeframeChange(tf);
    },
    [disabled, onTimeframeChange]
  );

  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-lg border border-slate-800 bg-slate-900/60 p-0.5"
      role="group"
      aria-label="Chart timeframe"
    >
      {TIMEFRAMES.map((tf) => {
        const active = mounted && timeframe === tf.value;
        return (
          <button
            key={tf.value}
            type="button"
            disabled={disabled}
            onClick={() => handleClick(tf.value)}
            aria-pressed={active}
            className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
              active
                ? "bg-slate-700 text-slate-100 shadow-sm"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
          >
            {tf.label}
          </button>
        );
      })}
    </div>
  );
}

export default TimeframeSelector;
