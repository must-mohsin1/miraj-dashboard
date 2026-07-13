"use client";

import { useEffect, useState } from "react";
import {
  ArrowUp,
  Layers,
  Loader2,
  Minus,
  RefreshCw,
  TrendingDown,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { DcaValidationEntry } from "@/components/portfolio/dca-validation-entry";
import type {
  DcaEntryLevel,
  DcaRecommendation,
  DcaResponse,
  DcaZone,
} from "@/lib/types";

interface DcaPanelProps {
  token: string | null;
  exchange: string;
}

const REFRESH_MS = 5 * 60 * 1000;

function recMeta(rec: string) {
  switch (rec) {
    case "ADD":
      return { label: "ADD", icon: ArrowUp, badge: "border-emerald-700 bg-emerald-500/10 text-emerald-400", border: "border-emerald-700/50", bg: "bg-emerald-500/5" };
    case "REDUCE":
      return { label: "REDUCE", icon: Minus, badge: "border-amber-700 bg-amber-500/10 text-amber-400", border: "border-amber-700/50", bg: "bg-amber-500/5" };
    case "CLOSE":
      return { label: "CLOSE", icon: X, badge: "border-red-700 bg-red-500/10 text-red-400", border: "border-red-700/50", bg: "bg-red-500/5" };
    default:
      return { label: "HOLD", icon: Layers, badge: "border-sky-700 bg-sky-500/10 text-sky-400", border: "border-sky-700/50", bg: "bg-sky-500/5" };
  }
}

function confColor(c: string) {
  return c === "CRITICAL" ? "text-red-400" : c === "HIGH" ? "text-amber-400" : c === "MEDIUM" ? "text-sky-400" : "text-slate-400";
}

function fmt(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  if (Math.abs(n) >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return parseFloat(n.toFixed(6)).toString();
}

export function DcaPanel({ token, exchange }: DcaPanelProps) {
  const [data, setData] = useState<DcaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  async function fetchDca() {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/v1/portfolio/${exchange}/dca`, { headers });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      setData(await res.json());
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
    (async () => { if (!cancelled) await fetchDca(); })();
    const interval = setInterval(() => { if (!cancelled) fetchDca(); }, REFRESH_MS);
    return () => { cancelled = true; clearInterval(interval); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />
        Computing DCA recommendations from pair analysis…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-800/50 bg-red-500/10 p-4 text-sm text-red-400">
        <TrendingDown className="h-4 w-4" />
        Failed to load DCA: {error}
      </div>
    );
  }

  const positions = data?.positions ?? [];
  const total = data?.total_positions ?? 0;
  if (total === 0) return null;

  const sortOrder: Record<string, number> = { CLOSE: 0, REDUCE: 1, ADD: 2, HOLD: 3 };
  const sorted = [...positions].sort((a, b) => sortOrder[a.recommendation] - sortOrder[b.recommendation]);

  const headerColor =
    (data?.close_count ?? 0) > 0 ? "border-red-800/50 bg-red-500/5"
    : (data?.add_count ?? 0) > 0 ? "border-emerald-800/50 bg-emerald-500/5"
    : "border-slate-800 bg-slate-900/60";

  return (
    <div className={`rounded-xl border ${headerColor} overflow-hidden`}>
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-slate-300" />
          <span className="font-semibold text-slate-200">Dynamic DCA</span>
          <span className="text-xs text-slate-500">Miraj three-entry + pair analysis</span>
          <div className="flex items-center gap-1.5">
            {(data?.add_count ?? 0) > 0 && <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-400">{data!.add_count} ADD</Badge>}
            {(data?.reduce_count ?? 0) > 0 && <Badge variant="outline" className="border-amber-700 bg-amber-500/10 text-amber-400">{data!.reduce_count} REDUCE</Badge>}
            {(data?.close_count ?? 0) > 0 && <Badge variant="outline" className="border-red-700 bg-red-500/10 text-red-400">{data!.close_count} CLOSE</Badge>}
            {(data?.hold_count ?? 0) > 0 && <Badge variant="outline" className="border-sky-700 bg-sky-500/10 text-sky-400">{data!.hold_count} HOLD</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {refreshing && <Loader2 className="h-3 w-3 animate-spin opacity-60" />}
          <RefreshCw className="h-3.5 w-3.5 opacity-60 transition hover:opacity-100" onClick={(e) => { e.stopPropagation(); fetchDca(); }} />
          {collapsed ? "Show" : "Hide"}
        </div>
      </button>

      {!collapsed && (
        <div className="border-t border-slate-800 px-3 py-2">
          <DcaValidationEntry exchange={exchange} compact />
          <span className="ml-2 text-xs text-slate-500">
            Review reconstructed shadow-mode validation without changing these recommendations.
          </span>
        </div>
      )}

      {!collapsed && (
        <div className="grid gap-3 p-3 pt-0 sm:grid-cols-2 xl:grid-cols-3">
          {sorted.map((pos) => <DcaCard key={pos.symbol} rec={pos} />)}
        </div>
      )}
    </div>
  );
}

function DcaCard({ rec }: { rec: DcaRecommendation }) {
  const meta = recMeta(rec.recommendation);
  const Icon = meta.icon;
  const isLong = rec.position_side === "LONG";
  const pnlPositive = rec.pnl >= 0;

  return (
    <div className={`rounded-lg border ${meta.border} ${meta.bg} p-3`}>
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-bold text-slate-100">{rec.symbol}</span>
          <Badge variant="outline" className={isLong ? "border-emerald-700 bg-emerald-500/10 text-emerald-400" : "border-red-700 bg-red-500/10 text-red-400"}>
            {isLong ? "▲" : "▼"} {rec.position_side}
          </Badge>
          <span className="text-xs text-slate-500">{rec.leverage}x</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Icon className={`h-4 w-4 ${meta.badge.includes("emerald") ? "text-emerald-400" : meta.badge.includes("amber") ? "text-amber-400" : meta.badge.includes("red") ? "text-red-400" : "text-sky-400"}`} />
          <Badge variant="outline" className={meta.badge}>{meta.label}</Badge>
        </div>
      </div>

      {/* Position info */}
      <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
        <span>Entry: <span className="text-slate-300 tabular-nums">{fmt(rec.entry_price)}</span></span>
        <span>Mark: <span className="text-slate-300 tabular-nums">{fmt(rec.mark_price)}</span></span>
        <span className={pnlPositive ? "text-emerald-400" : "text-red-400"}>
          PnL: {pnlPositive ? "+" : ""}{fmt(rec.pnl)} ({rec.pnl_percent.toFixed(2)}%)
        </span>
      </div>

      {/* Reason */}
      <p className="mb-2 text-xs leading-relaxed text-slate-300">{rec.reason}</p>

      {/* Badges */}
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {rec.rsi_current != null && (
          <Badge variant="outline" className="border-slate-700 bg-slate-900/60 text-slate-300">RSI {rec.rsi_current.toFixed(1)}</Badge>
        )}
        <Badge variant="outline" className="border-slate-700 bg-slate-900/60">
          <span className={confColor(rec.confidence)}>{rec.confidence}</span>
        </Badge>
        {rec.dca_zone && (
          <Badge variant="outline" className="border-slate-700 bg-slate-900/60 text-slate-400">{rec.dca_zone.label}</Badge>
        )}
      </div>

      {/* RSI Three-Entry table */}
      {rec.recommendation !== "CLOSE" && rec.rsi_entries.length > 0 && (
        <div className="mb-2 rounded-md border border-slate-800 bg-slate-950/40 p-2">
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Miraj RSI Three-Entry</div>
          <div className="space-y-1">
            {rec.rsi_entries.map((e, i) => (
              <div key={i} className={`flex items-center justify-between text-xs ${e.status === "filled" ? "opacity-100" : "opacity-50"}`}>
                <div className="flex items-center gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full ${e.status === "filled" ? "bg-emerald-500" : "bg-slate-600"}`} />
                  <span className="text-slate-300">{e.entry}</span>
                  <span className="text-slate-500">{e.trigger}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">{e.position_size_pct}</span>
                  <span className="text-slate-500">({e.cumulative_pct})</span>
                </div>
              </div>
            ))}
          </div>
          {rec.next_entry && (
            <div className="mt-1.5 border-t border-slate-800 pt-1.5 text-xs text-emerald-400">
              Next: <span className="font-semibold">{rec.next_entry.entry}</span> — deploy {rec.next_entry.position_size_pct} at {rec.next_entry.trigger}
            </div>
          )}
        </div>
      )}

      {/* TP levels */}
      {rec.tp_levels.length > 0 && (
        <div className="mb-2 text-xs text-slate-500">
          TP levels: {rec.tp_levels.map((t, i) => `$${fmt(t)}`).join(" → ")}
        </div>
      )}

      {/* Action items */}
      {rec.action_items.length > 0 && (
        <div className="mt-2 border-t border-slate-800 pt-2">
          <ul className="space-y-0.5">
            {rec.action_items.filter(Boolean).map((item, i) => (
              <li key={i} className="text-xs text-slate-400">→ {item}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Future ADD triggers */}
      {rec.future_add_triggers.length > 0 && rec.recommendation !== "ADD" && (
        <div className="mt-2 border-t border-slate-800 pt-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">ADD triggers</div>
          <ul className="mt-1 space-y-0.5">
            {rec.future_add_triggers.filter(Boolean).map((t, i) => (
              <li key={i} className="text-[11px] text-slate-500">• {t}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Risk rules */}
      {rec.risk_rules.length > 0 && rec.recommendation !== "HOLD" && (
        <div className="mt-2 border-t border-slate-800 pt-2">
          <ul className="space-y-0.5">
            {rec.risk_rules.slice(0, 3).map((rule, i) => (
              <li key={i} className="text-[10px] text-slate-500">• {rule}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default DcaPanel;
