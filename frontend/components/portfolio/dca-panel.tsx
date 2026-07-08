"use client";

import { useEffect, useState } from "react";
import {
  ArrowUp,
  Layers,
  Minus,
  X,
  Loader2,
  RefreshCw,
  BarChart3,
  AlertTriangle,
  Target,
  Shield,
  ChevronRight,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  DcaEntryLevel,
  DcaRecommendation,
  DcaResponse,
} from "@/lib/types";

/**
 * DcaPanel — Client Component.
 *
 * Fetches `GET /api/v1/portfolio/{exchange}/dca` every 5 minutes and renders
 * actionable DCA recommendation cards for each open position. Implements the
 * Miraj three-entry system + pair analysis from DYNAMIC_DCA_IMPLEMENTATION.md
 * §7.3.
 *
 * Cards are sorted by urgency: CLOSE → REDUCE → ADD → HOLD so the positions
 * needing the most attention bubble to the top.
 */

interface DcaPanelProps {
  /** JWT access token (for Authorization header). */
  token: string | null;
  /** Exchange slug (e.g. "mexc"). */
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes

// Urgency rank for sorting — lower = more urgent (renders first).
const URGENCY_RANK: Record<DcaRecommendation["recommendation"], number> = {
  CLOSE: 0,
  REDUCE: 1,
  ADD: 2,
  HOLD: 3,
};

export function DcaPanel({ token, exchange }: DcaPanelProps) {
  const [data, setData] = useState<DcaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchDca() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/portfolio/${exchange}/dca`, { headers });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: DcaResponse = await res.json();
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
      await fetchDca();
    }
    load();

    const interval = setInterval(() => {
      if (!cancelled) fetchDca();
    }, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  // ── Render states ─────────────────────────────────────────────────
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Computing DCA recommendations from pair analysis…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        <AlertTriangle className="h-4 w-4" />
        Failed to load DCA recommendations: {error}
      </div>
    );
  }

  // Spec §7.3: no positions → don't render the panel.
  if (!data || data.total_positions === 0) return null;

  const positions = [...data.positions].sort(
    (a, b) => URGENCY_RANK[a.recommendation] - URGENCY_RANK[b.recommendation],
  );

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      {/* Header row */}
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex flex-wrap items-center gap-2">
          <BarChart3 className="h-5 w-5 text-emerald-400" />
          <span className="font-semibold text-slate-100">Dynamic DCA</span>

          {/* Summary badges — [2 ADD] [1 REDUCE] [0 CLOSE] [0 HOLD] */}
          <div className="flex items-center gap-1.5">
            <CountBadge
              count={data.add_count}
              label="ADD"
              variant="add"
            />
            <CountBadge
              count={data.reduce_count}
              label="REDUCE"
              variant="reduce"
            />
            <CountBadge
              count={data.close_count}
              label="CLOSE"
              variant="close"
            />
            <CountBadge
              count={data.hold_count}
              label="HOLD"
              variant="hold"
            />
          </div>

          <span className="hidden text-[11px] text-slate-500 sm:inline">
            Miraj three-entry system + pair analysis
          </span>
        </div>
        <div className="flex items-center gap-2">
          {refreshing && <Loader2 className="h-3 w-3 animate-spin opacity-60" />}
          <RefreshCw
            className="h-3.5 w-3.5 opacity-60 transition hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              fetchDca();
            }}
          />
          <ChevronRight
            className={`h-4 w-4 opacity-60 transition-transform ${collapsed ? "" : "rotate-90"}`}
          />
        </div>
      </button>

      {/* DCA cards */}
      {!collapsed && (
        <div className="grid gap-3 p-3 pt-0 lg:grid-cols-2">
          {positions.map((pos) => (
            <DcaCard key={pos.symbol} position={pos} />
          ))}
        </div>
      )}

      {error && (
        <div className="border-t border-slate-800 px-4 py-2 text-xs text-amber-500">
          (refresh failed: {error})
        </div>
      )}
    </div>
  );
}

// ── Count badge in the header ──────────────────────────────────────────────

function CountBadge({
  count,
  label,
  variant,
}: {
  count: number;
  label: string;
  variant: "add" | "reduce" | "close" | "hold";
}) {
  const colors: Record<typeof variant, string> = {
    add: "border-emerald-700 bg-emerald-500/10 text-emerald-400",
    reduce: "border-amber-700 bg-amber-500/10 text-amber-400",
    close: "border-red-700 bg-red-500/10 text-red-400",
    hold: "border-sky-700 bg-sky-500/10 text-sky-400",
  };
  return (
    <Badge
      variant="outline"
      className={`h-5 px-1.5 text-[10px] font-bold ${colors[variant]}`}
    >
      {count} {label}
    </Badge>
  );
}

// ── Recommendation badge ──────────────────────────────────────────────────

function RecommendationBadge({
  rec,
}: {
  rec: DcaRecommendation["recommendation"];
}) {
  const config = RECOMMENDATION_CONFIG[rec];
  const Icon = config.icon;
  return (
    <Badge
      variant="outline"
      className={`gap-1 ${config.badge}`}
    >
      <Icon className="h-3 w-3" />
      {rec}
    </Badge>
  );
}

const RECOMMENDATION_CONFIG: Record<
  DcaRecommendation["recommendation"],
  { icon: typeof ArrowUp; badge: string; border: string; bg: string }
> = {
  ADD: {
    icon: ArrowUp,
    badge: "border-emerald-700 bg-emerald-500/10 text-emerald-400",
    border: "border-emerald-800/60",
    bg: "bg-emerald-500/5",
  },
  HOLD: {
    icon: Layers,
    badge: "border-sky-700 bg-sky-500/10 text-sky-400",
    border: "border-sky-800/60",
    bg: "bg-sky-500/5",
  },
  REDUCE: {
    icon: Minus,
    badge: "border-amber-700 bg-amber-500/10 text-amber-400",
    border: "border-amber-800/60",
    bg: "bg-amber-500/5",
  },
  CLOSE: {
    icon: X,
    badge: "border-red-700 bg-red-500/10 text-red-400",
    border: "border-red-800/60",
    bg: "bg-red-500/5",
  },
};

// ── Single DCA recommendation card ────────────────────────────────────────

function DcaCard({ position }: { position: DcaRecommendation }) {
  const config = RECOMMENDATION_CONFIG[position.recommendation];
  const pnlPositive = position.pnl >= 0;

  return (
    <div className={`rounded-lg border ${config.border} ${config.bg} p-3 space-y-2`}>
      {/* Row 1: Symbol | Side | Leverage | Recommendation */}
      <div className="flex flex-wrap items-center justify-between gap-2">
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
          <Badge
            variant="outline"
            className="border-slate-700 bg-slate-800/50 text-slate-400"
          >
            {position.leverage}x
          </Badge>
        </div>
        <RecommendationBadge rec={position.recommendation} />
      </div>

      {/* Row 2: Entry | Mark | PnL + PnL% */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
        <span className="text-slate-400">
          Entry:{" "}
          <span className="text-slate-200">{fmtPrice(position.entry_price)}</span>
        </span>
        <span className="text-slate-400">
          Mark:{" "}
          <span className="text-slate-200">{fmtPrice(position.mark_price)}</span>
        </span>
        <span
          className={pnlPositive ? "text-emerald-400" : "text-red-400"}
        >
          PnL: {pnlPositive ? "+" : ""}
          {position.pnl.toFixed(2)} ({pnlPositive ? "+" : ""}
          {position.pnl_percent.toFixed(2)}%)
        </span>
      </div>

      {/* Row 3: Reason text */}
      <p className="text-xs text-slate-300 leading-relaxed">{position.reason}</p>

      {/* Row 4: RSI | Confidence | OTE zone */}
      <div className="flex flex-wrap items-center gap-1.5">
        {position.rsi_current != null && (
          <RsiBadge rsi={position.rsi_current} />
        )}
        <ConfidenceBadge confidence={position.confidence} />
        {position.dca_zone && <OteZoneBadge zone={position.dca_zone} />}
      </div>

      {/* Row 5: RSI Three-Entry table */}
      {position.rsi_entries.length > 0 && (
        <RsiEntryTable entries={position.rsi_entries} />
      )}

      {/* Row 6: Next entry highlight */}
      {position.next_entry && (
        <div className="rounded-md border border-emerald-800/40 bg-emerald-500/5 px-2 py-1.5 text-xs">
          <span className="text-emerald-400">Next: </span>
          <span className="text-slate-200">{position.next_entry.entry}</span>
          <span className="text-slate-400"> — deploy </span>
          <span className="text-slate-200">
            {position.next_entry.position_size_pct}
          </span>
          <span className="text-slate-400"> at </span>
          <span className="text-slate-200">
            {position.next_entry.trigger}
          </span>
          <span className="text-slate-400"> (cumulative </span>
          <span className="text-slate-200">
            {position.next_entry.cumulative_pct}
          </span>
          <span className="text-slate-400">)</span>
        </div>
      )}

      {/* Row 7: TP levels */}
      {position.tp_levels.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Target className="h-3.5 w-3.5 text-slate-500" />
          {position.tp_levels.map((tp, i) => {
            const isHere = Math.abs(position.mark_price - tp) <=
              Math.abs(tp) * 0.0015; // within 0.15% → "HERE"
            return (
              <span key={i} className="font-mono">
                <span className="text-slate-500">TP{i + 1}: </span>
                <span className="text-slate-200">${tp.toFixed(2)}</span>
                {isHere && (
                  <Badge
                    variant="outline"
                    className="ml-1 h-4 px-1 text-[9px] font-bold border-emerald-700 bg-emerald-500/10 text-emerald-400"
                  >
                    HERE
                  </Badge>
                )}
                {i < position.tp_levels.length - 1 && (
                  <span className="mx-1 text-slate-700">·</span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Row 8: Action items (→ prefix) */}
      {position.action_items.length > 0 && (
        <ul className="space-y-1">
          {position.action_items.map((item, i) => (
            <li key={i} className="flex gap-1.5 text-xs text-slate-300">
              <span className="text-emerald-400">→</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Row 9: Future ADD triggers */}
      {position.future_add_triggers.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            <ChevronRight className="h-3 w-3" />
            Future ADD triggers
          </div>
          <ul className="space-y-0.5">
            {position.future_add_triggers.map((trig, i) => (
              <li key={i} className="flex gap-1.5 text-xs text-slate-400">
                <span className="text-slate-600">•</span>
                <span>{trig}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Row 10: Risk rules (compact, max 3) */}
      {position.risk_rules.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-800/60 pt-2">
          <Shield className="h-3 w-3 text-slate-500" />
          {position.risk_rules.slice(0, 3).map((rule, i) => (
            <span key={i} className="text-[10px] text-slate-500">
              {rule}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Row 4 sub-badges ───────────────────────────────────────────────────────

function RsiBadge({ rsi }: { rsi: number }) {
  const color =
    rsi < 30
      ? "border-emerald-700 bg-emerald-500/10 text-emerald-400"
      : rsi < 45
        ? "border-amber-700 bg-amber-500/10 text-amber-400"
        : rsi > 70
          ? "border-red-700 bg-red-500/10 text-red-400"
          : "border-slate-700 bg-slate-800/50 text-slate-400";
  return (
    <Badge variant="outline" className={`gap-1 ${color}`}>
      <span className="font-mono">{rsi.toFixed(1)}</span>
      <span className="opacity-70">RSI</span>
    </Badge>
  );
}

function ConfidenceBadge({
  confidence,
}: {
  confidence: DcaRecommendation["confidence"];
}) {
  const color =
    confidence === "CRITICAL"
      ? "border-red-700 bg-red-500/10 text-red-400"
      : confidence === "HIGH"
        ? "border-emerald-700 bg-emerald-500/10 text-emerald-400"
        : confidence === "MEDIUM"
          ? "border-amber-700 bg-amber-500/10 text-amber-400"
          : "border-slate-700 bg-slate-800/50 text-slate-400";
  return (
    <Badge variant="outline" className={color}>
      {confidence}
    </Badge>
  );
}

function OteZoneBadge({ zone }: { zone: NonNullable<DcaRecommendation["dca_zone"]> }) {
  return (
    <Badge
      variant="outline"
      className="border-purple-700/60 bg-purple-500/10 text-purple-300 font-mono"
    >
      {zone.label || `OTE ${zone.low}-${zone.high}`}
    </Badge>
  );
}

// ── Row 5: RSI three-entry table ───────────────────────────────────────────

function RsiEntryTable({ entries }: { entries: DcaEntryLevel[] }) {
  return (
    <div className="rounded-md border border-slate-800/80 bg-slate-950/40 overflow-hidden">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-slate-800/80 text-slate-500">
            <th className="px-2 py-1 text-left font-medium">#</th>
            <th className="px-2 py-1 text-left font-medium">Entry</th>
            <th className="px-2 py-1 text-left font-medium">Trigger</th>
            <th className="px-2 py-1 text-right font-medium">Size</th>
            <th className="px-2 py-1 text-right font-medium">Cum.</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {entries.map((e, i) => (
            <tr
              key={i}
              className="border-b border-slate-800/40 last:border-0"
            >
              <td className="px-2 py-1">
                <span
                  className={
                    e.status === "filled" ? "text-emerald-400" : "text-slate-600"
                  }
                  title={e.status}
                >
                  {e.status === "filled" ? "●" : "○"}
                </span>
              </td>
              <td className="px-2 py-1 text-slate-300">{e.entry}</td>
              <td className="px-2 py-1 text-slate-400">{e.trigger}</td>
              <td className="px-2 py-1 text-right text-slate-200">
                {e.position_size_pct}
              </td>
              <td className="px-2 py-1 text-right text-slate-400">
                {e.cumulative_pct}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Format a price compactly (2 dp for small, more for sub-dollar). */
function fmtPrice(n: number): string {
  if (Math.abs(n) < 1) return `$${n.toFixed(5)}`;
  if (Math.abs(n) < 10) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export default DcaPanel;
