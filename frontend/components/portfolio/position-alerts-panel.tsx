"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  PositionAlert,
  PositionAlertItem,
  PositionAlertsResponse,
} from "@/lib/types";

/**
 * PositionAlertsPanel — Client Component.
 *
 * Fetches `GET /api/v1/portfolio/{exchange}/position-alerts` and renders
 * warning cards for every at-risk position. DANGER alerts are red; WARNING
 * alerts are amber. Auto-refreshes every 5 minutes alongside the dashboard.
 *
 * The panel is collapsible — when collapsed it shows a summary badge with
 * the alert count so it doesn't take screen real-estate when all is clear.
 */

interface PositionAlertsPanelProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

export function PositionAlertsPanel({ token, exchange }: PositionAlertsPanelProps) {
  const [data, setData] = useState<PositionAlertsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchAlerts() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/portfolio/${exchange}/position-alerts`, {
        headers,
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: PositionAlertsResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    async function load() {
      if (cancelled) return;
      await fetchAlerts();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchAlerts();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  // ── Render states ─────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Checking positions against Miraj scan…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 p-4 text-sm text-red-400">
        <AlertTriangle className="h-4 w-4" />
        Failed to load position alerts: {error}
      </div>
    );
  }

  const positions = data?.positions ?? [];
  const dangerCount = data?.danger_count ?? 0;
  const warningCount = data?.warning_count ?? 0;
  const totalAlerts = dangerCount + warningCount;

  // No alerts — show a calm "all clear" banner.
  if (totalAlerts === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-emerald-800/40 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-400">
        <ShieldAlert className="h-4 w-4" />
        All positions align with the Miraj scan — no conflicting signals.
        {error && (
          <span className="ml-2 text-xs text-amber-500">
            (refresh failed: {error})
          </span>
        )}
      </div>
    );
  }

  const headerColor =
    dangerCount > 0
      ? "border-red-800/50 bg-red-500/10 text-red-400"
      : "border-amber-800/50 bg-amber-500/10 text-amber-400";

  return (
    <div
      className={`rounded-xl border ${headerColor} overflow-hidden`}
    >
      {/* Header row */}
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5" />
          <span className="font-semibold">
            {dangerCount > 0
              ? `${dangerCount} position${dangerCount > 1 ? "s" : ""} in DANGER`
              : `${warningCount} position${warningCount > 1 ? "s" : ""} with warnings`}
          </span>
          <Badge
            variant="outline"
            className={
              dangerCount > 0
                ? "border-red-700 bg-red-500/10 text-red-300"
                : "border-amber-700 bg-amber-500/10 text-amber-300"
            }
          >
            {totalAlerts} alert{totalAlerts > 1 ? "s" : ""}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {refreshing && <Loader2 className="h-3 w-3 animate-spin opacity-60" />}
          <RefreshCw
            className="h-3.5 w-3.5 opacity-60 transition hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              fetchAlerts();
            }}
          />
          {collapsed ? "Show" : "Hide"}
        </div>
      </button>

      {/* Alert cards */}
      {!collapsed && (
        <div className="grid gap-3 p-3 pt-0 sm:grid-cols-2 lg:grid-cols-3">
          {positions.map((pos) => (
            <PositionAlertCard key={pos.symbol} position={pos} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Single position alert card ─────────────────────────────────────────────


function PositionAlertCard({ position }: { position: PositionAlertItem }) {
  const isDanger = position.max_severity === "DANGER";
  const borderColor = isDanger ? "border-red-800/60" : "border-amber-800/60";
  const bgColor = isDanger ? "bg-red-500/5" : "bg-amber-500/5";

  return (
    <div
      className={`rounded-lg border ${borderColor} ${bgColor} p-3`}
    >
      {/* Symbol + side header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-bold text-slate-100">
            {position.symbol}
          </span>
          <Badge
            variant="outline"
            className={
              position.position_side === "LONG"
                ? "border-emerald-700 bg-emerald-500/10 text-emerald-400"
                : "border-red-700 bg-red-500/10 text-red-400"
            }
          >
            {position.position_side}
          </Badge>
        </div>
        {isDanger ? (
          <ShieldAlert className="h-4 w-4 text-red-400" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-400" />
        )}
      </div>

      {/* Alerts list */}
      <ul className="space-y-1.5">
        {position.alerts.map((alert, i) => (
          <AlertLine key={i} alert={alert} />
        ))}
      </ul>
    </div>
  );
}


function AlertLine({ alert }: { alert: PositionAlert }) {
  const isDanger = alert.severity === "DANGER";
  const dotColor = isDanger ? "bg-red-500" : "bg-amber-500";
  const typeColor = isDanger ? "text-red-400" : "text-amber-400";

  return (
    <li className="flex gap-2 text-xs">
      <span
        className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotColor}`}
        aria-hidden
      />
      <div className="flex-1">
        <div className="flex items-center gap-1.5">
          <span className={`font-mono font-semibold ${typeColor}`}>
            {alert.type.replace("_", " ")}
          </span>
          <Badge
            variant="outline"
            className={`h-4 px-1 text-[9px] font-bold ${
              isDanger
                ? "border-red-700 bg-red-500/10 text-red-400"
                : "border-amber-700 bg-amber-500/10 text-amber-400"
            }`}
          >
            {alert.severity}
          </Badge>
        </div>
        <p className="text-slate-300">{alert.message}</p>
        {alert.action && (
          <p className="mt-0.5 text-slate-500">
            <span className="italic">→ {alert.action}</span>
          </p>
        )}
      </div>
    </li>
  );
}

export default PositionAlertsPanel;
