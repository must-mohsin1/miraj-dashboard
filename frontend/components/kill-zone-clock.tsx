"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

/**
 * KillZoneClock — Client Component.
 *
 * Renders the four standard ICT kill-zone windows in EST (America/New_York)
 * and highlights the currently active session in emerald. The component
 * re-renders every second via `setInterval` so the "time remaining" / "time
 * to next" countdown stays live.
 *
 * Kill zones (EST / America/New_York):
 *   Asian     19:00 – 00:00  (next-day midnight)
 *   London    02:00 – 05:00
 *   NY Open   08:30 – 11:00
 *   NY Close  11:00 – 12:00
 *
 * Because EST has no daylight-saving transitions, using
 * `timeZone: "America/New_York"` with `Intl.DateTimeFormat` gives the correct
 * local "wall clock" for the zone regardless of the viewer's own timezone.
 */

interface KillZone {
  name: string;
  /** Inclusive start, minutes from local-midnight in NY time. */
  startMin: number;
  /** Exclusive end, minutes from local-midnight in NY time. */
  endMin: number;
  /** Human-readable range label. */
  label: string;
  /**
   * Whether the window wraps past midnight (end <= start), e.g. Asian
   * 19:00→00:00. We treat 00:00 as "midnight at the *end*" of the session,
   * so endMin=1440 and wraps=false works naturally.
   */
  wrapsMidnight?: boolean;
}

/** Each zone's minutes-from-midnight boundaries (1440 = next midnight). */
const KILL_ZONES: KillZone[] = [
  {
    name: "Asian",
    startMin: 19 * 60, // 19:00
    endMin: 24 * 60, // 00:00 (next day)
    label: "19:00 – 00:00",
    wrapsMidnight: false,
  },
  {
    name: "London",
    startMin: 2 * 60, // 02:00
    endMin: 5 * 60, // 05:00
    label: "02:00 – 05:00",
  },
  {
    name: "NY Open",
    startMin: 8 * 60 + 30, // 08:30
    endMin: 11 * 60, // 11:00
    label: "08:30 – 11:00",
  },
  {
    name: "NY Close",
    startMin: 11 * 60, // 11:00
    endMin: 12 * 60, // 12:00
    label: "11:00 – 12:00",
  },
];

const NEW_YORK_TZ = "America/New_York";

/**
 * Return the current minutes-from-midnight in New York time as a number in
 * the range [0, 1440). Using `Intl.DateTimeFormat` parts avoids relying on
 * any server clock or library.
 */
function nyMinutesFromDate(d: Date): number {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: NEW_YORK_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = fmt.formatToParts(d);
  const get = (type: string) =>
    parts.find((p) => p.type === type)?.value ?? "0";
  let h = parseInt(get("hour"), 10);
  if (h === 24) h = 0; // some environments emit "24" for midnight
  const m = parseInt(get("minute"), 10);
  const s = parseInt(get("second"), 10);
  return h * 60 + m + s / 60;
}

/** Format an NY wall-clock time string from a Date (HH:MM:SS EST). */
function nyClockString(d: Date): string {
  return d.toLocaleTimeString("en-US", {
    timeZone: NEW_YORK_TZ,
    hour12: false,
  });
}

/**
 * Determine which kill zone (if any) contains the given NY-time minute count.
 * Returns the matching zone or null.
 */
function activeZone(min: number): KillZone | null {
  for (const z of KILL_ZONES) {
    if (min >= z.startMin && min < z.endMin) return z;
  }
  return null;
}

/**
 * Find the next upcoming kill zone start after the given NY minute count.
 * If today's zones are all exhausted, wraps around to the next day's Asian
 * session (the first entry). Returns the zone and the minutes until it opens.
 */
function nextZone(
  min: number
): { zone: KillZone; minutesUntil: number } {
  // Search today's zones in chronological order (London, NY Open, NY Close,
  // Asian — though Asian starts last, it ends at 24:00).
  const todaySorted = [...KILL_ZONES].sort((a, b) => a.startMin - b.startMin);
  for (const z of todaySorted) {
    if (z.startMin > min) {
      return { zone: z, minutesUntil: z.startMin - min };
    }
  }
  // None left today — earliest zone tomorrow.
  const first = todaySorted[0];
  const minutesUntil = 1440 - min + first.startMin;
  return { zone: first, minutesUntil };
}

/** Format a duration in minutes as `Hh Mm` or `Mm Ss` for sub-hour values. */
function formatDuration(totalMinutes: number): string {
  if (totalMinutes < 0) totalMinutes = 0;
  const totalSeconds = Math.round(totalMinutes * 60);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

export function KillZoneClock() {
  const [now, setNow] = useState<Date | null>(null);

  // Tick every second. The initial render uses `null` so SSR and the first
  // client paint render deterministic placeholder content (no hydration
  // mismatch), then the effect flips to live time.
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Until mounted on the client, render a stable skeleton that matches the
  // dark theme without surfacing a server time that could mismatch.
  if (!now) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-300">
          <Clock className="h-4 w-4 text-emerald-400" />
          ICT Kill Zones
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {KILL_ZONES.map((z) => (
            <div
              key={z.name}
              className="rounded-lg border border-slate-700 bg-slate-700/40 p-3"
            >
              <div className="text-sm font-semibold text-slate-200">
                {z.name}
              </div>
              <div className="text-xs text-slate-400">{z.label} EST</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const nyMin = nyMinutesFromDate(now);
  const active = activeZone(nyMin);
  const clockStr = nyClockString(now);

  // For the countdown text.
  let countdownText: string;
  let countdownLabel: string;
  if (active) {
    const remaining = active.endMin - nyMin;
    countdownText = formatDuration(remaining);
    countdownLabel = "remaining";
  } else {
    const next = nextZone(nyMin);
    countdownText = formatDuration(next.minutesUntil);
    countdownLabel = `until ${next.zone.name}`;
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
          <Clock className="h-4 w-4 text-emerald-400" />
          ICT Kill Zones
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span className="font-mono text-slate-200">{clockStr} EST</span>
          <span className="text-slate-500">|</span>
          <span>
            <span className="font-semibold text-emerald-400">
              {countdownText}
            </span>{" "}
            {countdownLabel}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {KILL_ZONES.map((z) => {
          const isActive = active?.name === z.name;
          return (
            <div
              key={z.name}
              className={
                isActive
                  ? "rounded-lg border border-emerald-600/60 bg-emerald-500/10 p-3"
                  : "rounded-lg border border-slate-700 bg-slate-700/40 p-3"
              }
            >
              <div
                className={
                  isActive
                    ? "text-sm font-semibold text-emerald-300"
                    : "text-sm font-semibold text-slate-200"
                }
              >
                {z.name}
              </div>
              <div
                className={
                  isActive ? "text-xs text-emerald-200/80" : "text-xs text-slate-400"
                }
              >
                {z.label} EST
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default KillZoneClock;
