"use client";

import { useEffect, useCallback } from "react";

/**
 * IndicatorTogglePanel — checkbox toggles for chart overlay visibility.
 *
 * Controls visibility of:
 *   - EMA (20/50/200)
 *   - Bollinger Bands
 *   - RSI
 *   - MACD
 *   - Volume
 *   - Order Blocks
 *   - Fair Value Gaps
 *
 * Preferences are persisted to ``localStorage`` under
 * ``miraj:chart:indicators`` as a JSON record.
 */

export interface IndicatorVisibility {
  ema: boolean;
  bollinger: boolean;
  rsi: boolean;
  macd: boolean;
  volume: boolean;
  orderBlocks: boolean;
  fairValueGaps: boolean;
}

export const DEFAULT_INDICATOR_VISIBILITY: IndicatorVisibility = {
  ema: true,
  bollinger: true,
  rsi: true,
  macd: true,
  volume: true,
  orderBlocks: true,
  fairValueGaps: true,
};

const STORAGE_KEY = "miraj:chart:indicators";

function loadFromStorage(): IndicatorVisibility {
  if (typeof window === "undefined") return DEFAULT_INDICATOR_VISIBILITY;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_INDICATOR_VISIBILITY;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_INDICATOR_VISIBILITY, ...parsed };
  } catch {
    return DEFAULT_INDICATOR_VISIBILITY;
  }
}

const TOGGLE_ITEMS: { key: keyof IndicatorVisibility; label: string; color: string }[] = [
  { key: "ema", label: "EMA (20/50/200)", color: "#a78bfa" },
  { key: "bollinger", label: "Bollinger Bands", color: "#38bdf8" },
  { key: "rsi", label: "RSI", color: "#f59e0b" },
  { key: "macd", label: "MACD", color: "#6CA98F" },
  { key: "volume", label: "Volume", color: "#8E8778" },
  { key: "orderBlocks", label: "Order Blocks", color: "#C96A55" },
  { key: "fairValueGaps", label: "Fair Value Gaps", color: "#facc15" },
];

interface IndicatorTogglePanelProps {
  /** Current visibility state. */
  visibility: IndicatorVisibility;
  /** Called when any toggle changes. */
  onChange: (v: IndicatorVisibility) => void;
  /** Optional: compact mode for sidebars. */
  compact?: boolean;
}

export function IndicatorTogglePanel({
  visibility,
  onChange,
  compact = false,
}: IndicatorTogglePanelProps) {
  useEffect(() => {
    const stored = loadFromStorage();
    onChange(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleToggle = useCallback(
    (key: keyof IndicatorVisibility) => {
      const next = { ...visibility, [key]: !visibility[key] };
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      onChange(next);
    },
    [visibility, onChange]
  );

  return (
    <div
      className={`${
        compact ? "" : "border border-[#2A2620] bg-[#161411] p-3"
      }`}
    >
      {!compact && (
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8E8778]">
          Indicators
        </h4>
      )}
      <div
        className={`grid ${
          compact ? "grid-cols-1" : "grid-cols-2"
        } gap-x-3 gap-y-1.5`}
      >
        {TOGGLE_ITEMS.map((item) => {
          const checked = visibility[item.key];
          return (
            <label
              key={item.key}
              className="flex cursor-pointer items-center gap-2 text-xs text-[#D8D1C4] select-none"
            >
              <span
                className="relative flex h-4 w-7 items-center rounded-full transition-colors"
                style={{
                  backgroundColor: checked ? item.color : "#2A2620",
                }}
                onClick={(e) => {
                  e.preventDefault();
                  handleToggle(item.key);
                }}
              >
                <span
                  className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                    checked ? "translate-x-3.5" : "translate-x-0.5"
                  }`}
                />
              </span>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => handleToggle(item.key)}
                className="sr-only"
              />
              <span className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                {item.label}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

export default IndicatorTogglePanel;
