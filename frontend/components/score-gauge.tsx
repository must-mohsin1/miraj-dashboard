"use client";

import { useEffect, useRef, useState } from "react";

/**
 * ScoreGauge — Client Component.
 *
 * A circular SVG gauge that displays a 0–100 confluence score. The arc fills
 * clockwise from the top and is colour-coded by band:
 *
 *   < 30  → red      (bearish / weak)
 *   30–50 → orange   (caution)
 *   50–70 → yellow   (moderate)
 *   > 70  → green    (strong / bullish)
 *
 * The gauge animates from empty to the target value on mount using a simple
 * requestAnimationFrame tween, giving the page a polished feel without a
 * heavyweight animation library. The component is pure SVG (no
 * lightweight-charts / recharts dependency) so it renders crisply at any size
 * and works in SSR.
 */

/** Colour for a given score band. */
function scoreColor(score: number): string {
  if (score < 30) return "#ef4444"; // red-500
  if (score < 50) return "#f97316"; // orange-500
  if (score < 70) return "#eab308"; // yellow-500
  return "#22c55e"; // green-500
}

/** Human-readable label for a score band. */
function scoreLabel(score: number): string {
  if (score < 30) return "Weak";
  if (score < 50) return "Caution";
  if (score < 70) return "Moderate";
  return "Strong";
}

/**
 * Animate a numeric value from 0 to `target` over `durationMs` using rAF.
 * Returns the current animated value. Uses easeOutCubic for a natural feel.
 */
function useAnimatedValue(target: number, durationMs = 800): number {
  const [value, setValue] = useState(0);
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const from = 0;
    const to = targetRef.current;

    const tick = (now: number) => {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / durationMs);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (to - from) * eased);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      }
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return value;
}

interface ScoreGaugeProps {
  /** Score value 0–100. Out-of-range values are clamped. */
  score: number | null | undefined;
  /** Optional width/height in px (the gauge is square). Defaults to 180. */
  size?: number;
  /** Heading shown above the number inside the gauge. Defaults to "Score". */
  label?: string;
}

export function ScoreGauge({
  score,
  size = 180,
  label = "Score",
}: ScoreGaugeProps) {
  const hasScore =
    score !== null && score !== undefined && !Number.isNaN(score);
  const clamped = hasScore ? Math.max(0, Math.min(100, Number(score))) : 0;
  const animated = useAnimatedValue(clamped);

  const color = scoreColor(clamped);
  const displayLabel = scoreLabel(clamped);

  // SVG geometry
  const stroke = 14;
  const radius = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * radius;

  // Arc covers 270° (from -225° to 45°), leaving a 90° gap at the bottom
  const arcFraction = 0.75; // 270/360
  const arcLength = circumference * arcFraction;
  const trackDash = `${arcLength} ${circumference}`;
  // Value proportion of the arc
  const valueLength = (animated / 100) * arcLength;
  const valueDash = `${valueLength} ${circumference}`;

  // Rotate so the gap sits at the bottom centre (start at bottom-left, 135°)
  const rotation = 135;

  return (
    <div
      className="flex flex-col items-center justify-center"
      style={{ width: size }}
    >
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="block"
        >
          {/* Track */}
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke="#1e293b" // slate-800
            strokeWidth={stroke}
            strokeDasharray={trackDash}
            strokeLinecap="round"
            transform={`rotate(${rotation} ${cx} ${cy})`}
          />
          {/* Value arc (animated) */}
          {hasScore && (
            <circle
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth={stroke}
              strokeDasharray={valueDash}
              strokeLinecap="round"
              transform={`rotate(${rotation} ${cx} ${cy})`}
              style={{ transition: "stroke 0.3s ease" }}
            />
          )}
          {/* Center text — score number */}
          <text
            x={cx}
            y={cy - 6}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-slate-100"
            style={{ fontSize: size * 0.22, fontWeight: 700 }}
          >
            {hasScore ? Math.round(animated) : "—"}
          </text>
          {/* Center sub-label */}
          <text
            x={cx}
            y={cy + size * 0.14}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-slate-500"
            style={{ fontSize: size * 0.07, fontWeight: 500 }}
          >
            {label} / 100
          </text>
        </svg>
      </div>
      <span
        className="mt-2 text-sm font-medium"
        style={{ color: hasScore ? color : "#64748b" }}
      >
        {hasScore ? displayLabel : "No data"}
      </span>
    </div>
  );
}

export default ScoreGauge;
