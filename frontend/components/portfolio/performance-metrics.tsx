"use client";

import type { ReactNode } from "react";
import {
  TrendingUp,
  TrendingDown,
  Target,
  Activity,
  Award,
  AlertTriangle,
  Scale,
  Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { PerformanceMetrics } from "@/lib/types";

interface PerformanceMetricsProps {
  metrics: PerformanceMetrics | null;
}

export function PerformanceMetrics({ metrics }: PerformanceMetricsProps) {
  if (!metrics || metrics.total_trades === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No closed trades yet. Analytics will appear here once you have closed
        positions.
      </div>
    );
  }

  const pnlPositive = metrics.total_pnl >= 0;
  const realisedDrawdown = metrics.realised_pnl_drawdown_usd ?? metrics.max_drawdown;
  const realisedDrawdownPct = metrics.realised_pnl_drawdown_pct ?? metrics.max_drawdown_percent;
  const tradeQuality = metrics.trade_quality_score ?? metrics.sharpe_ratio;
  const ddNegative = realisedDrawdown > 0;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      <StatCard
        label="Win Rate"
        value={`${metrics.win_rate.toFixed(1)}%`}
        icon={<Target className="h-4 w-4" />}
        positive={metrics.win_rate >= 50}
        negative={metrics.win_rate < 50}
        footer={
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                metrics.win_rate >= 50 ? "bg-emerald-500" : "bg-red-500",
              )}
              style={{ width: `${Math.min(100, metrics.win_rate)}%` }}
            />
          </div>
        }
      />

      <StatCard
        label="Profit Factor"
        value={
          metrics.profit_factor === null
            ? "∞"
            : metrics.profit_factor.toFixed(2)
        }
        icon={<Scale className="h-4 w-4" />}
        positive={(metrics.profit_factor ?? Infinity) >= 1}
        negative={metrics.profit_factor !== null && metrics.profit_factor < 1}
        hint="Gross profit / loss"
      />

      <StatCard
        label="Trade Quality Score"
        value={tradeQuality === null ? "—" : tradeQuality.toFixed(2)}
        icon={<Activity className="h-4 w-4" />}
        positive={(tradeQuality ?? 0) > 0}
        negative={(tradeQuality ?? 0) < 0}
        hint="Per-trade PnL dispersion"
      />

      <StatCard
        label="Realised-PnL Drawdown"
        value={`-$${realisedDrawdown.toFixed(2)}`}
        icon={<AlertTriangle className="h-4 w-4" />}
        negative={ddNegative}
        hint={
          realisedDrawdownPct !== null
            ? `${realisedDrawdownPct.toFixed(1)}% of peak — Cumulative closed PnL`
            : "Cumulative closed PnL"
        }
      />

      <StatCard
        label="Total Trades"
        value={String(metrics.total_trades)}
        icon={<Zap className="h-4 w-4" />}
        hint={`${metrics.winning_trades}W / ${metrics.losing_trades}L`}
      />

      <StatCard
        label="Avg Win"
        value={`+$${metrics.average_win.toFixed(2)}`}
        icon={<TrendingUp className="h-4 w-4" />}
        positive={metrics.average_win > 0}
      />

      <StatCard
        label="Avg Loss"
        value={
          metrics.average_loss === 0
            ? "$0.00"
            : `-$${Math.abs(metrics.average_loss).toFixed(2)}`
        }
        icon={<TrendingDown className="h-4 w-4" />}
        negative={metrics.average_loss < 0}
      />

      <StatCard
        label="Best Trade"
        value={`+$${metrics.best_trade.toFixed(2)}`}
        icon={<Award className="h-4 w-4" />}
        positive={metrics.best_trade > 0}
      />

      <StatCard
        label="Worst Trade"
        value={
          metrics.worst_trade >= 0
            ? `$${metrics.worst_trade.toFixed(2)}`
            : `-$${Math.abs(metrics.worst_trade).toFixed(2)}`
        }
        icon={<TrendingDown className="h-4 w-4" />}
        negative={metrics.worst_trade < 0}
      />

      <StatCard
        label="Realised PnL"
        value={`${pnlPositive ? "+" : ""}$${metrics.total_pnl.toFixed(2)}`}
        icon={<Scale className="h-4 w-4" />}
        positive={pnlPositive}
        negative={!pnlPositive}
        hint={
          <>
            <span>{metrics.total_pnl_basis || "MEXC-reported closed-position PnL"}</span>
            <span>Account return unavailable — {readableReason(metrics.account_return_pct_reason || metrics.total_pnl_percent_reason)}</span>
          </>
        }
        className="col-span-2 sm:col-span-1 lg:col-span-1"
      />
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  icon?: ReactNode;
  positive?: boolean;
  negative?: boolean;
  hint?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

function StatCard({
  label,
  value,
  icon,
  positive,
  negative,
  hint,
  footer,
  className,
}: StatCardProps) {
  const valueColor = positive
    ? "text-emerald-400"
    : negative
      ? "text-red-400"
      : "text-slate-100";

  return (
    <div
      className={cn(
        "rounded-xl border border-slate-800 bg-slate-900/60 p-4",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
        {icon}
        {label}
      </div>
      <div className={cn("mt-1 text-xl font-bold tabular-nums", valueColor)}>
        {value}
      </div>
      {hint && (
        <div className="mt-0.5 flex flex-col gap-0.5 text-xs text-muted-foreground">{hint}</div>
      )}
      {footer}
    </div>
  );
}

function readableReason(reason?: string | null): string {
  if (!reason) return "reason unavailable";
  return reason.replaceAll("_", " ");
}

export default PerformanceMetrics;
