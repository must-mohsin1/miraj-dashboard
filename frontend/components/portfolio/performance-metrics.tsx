"use client";

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

/**
 * PerformanceMetrics — Client Component.
 *
 * Renders a grid of stat cards summarising trading performance:
 * Win Rate (with progress bar), Profit Factor, Sharpe Ratio, Max Drawdown,
 * Total Trades, Avg Win, Avg Loss, Best/Worst Trade.
 *
 * Positive values are highlighted in emerald, negative in red, matching the
 * dark-theme palette used throughout the portfolio dashboard.
 */

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
  const ddNegative = metrics.max_drawdown > 0; // drawdown is a positive number meaning a decline

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {/* Win Rate — with progress bar */}
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

      {/* Profit Factor */}
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

      {/* Sharpe Ratio */}
      <StatCard
        label="Sharpe Ratio"
        value={
          metrics.sharpe_ratio === null
            ? "—"
            : metrics.sharpe_ratio.toFixed(2)
        }
        icon={<Activity className="h-4 w-4" />}
        positive={(metrics.sharpe_ratio ?? 0) > 0}
        negative={(metrics.sharpe_ratio ?? 0) < 0}
        hint="Risk-adjusted"
      />

      {/* Max Drawdown */}
      <StatCard
        label="Max Drawdown"
        value={`-$${metrics.max_drawdown.toFixed(2)}`}
        icon={<AlertTriangle className="h-4 w-4" />}
        negative={ddNegative && metrics.max_drawdown > 0}
        hint={
          metrics.max_drawdown_percent !== null
            ? `${metrics.max_drawdown_percent.toFixed(1)}% of peak`
            : undefined
        }
      />

      {/* Total Trades */}
      <StatCard
        label="Total Trades"
        value={String(metrics.total_trades)}
        icon={<Zap className="h-4 w-4" />}
        hint={`${metrics.winning_trades}W / ${metrics.losing_trades}L`}
      />

      {/* Avg Win */}
      <StatCard
        label="Avg Win"
        value={`+$${metrics.average_win.toFixed(2)}`}
        icon={<TrendingUp className="h-4 w-4" />}
        positive={metrics.average_win > 0}
      />

      {/* Avg Loss */}
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

      {/* Best Trade */}
      <StatCard
        label="Best Trade"
        value={`+$${metrics.best_trade.toFixed(2)}`}
        icon={<Award className="h-4 w-4" />}
        positive={metrics.best_trade > 0}
      />

      {/* Worst Trade */}
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

      {/* Total PnL — spans 2 cols on small screens */}
      <StatCard
        label="Total PnL"
        value={`${pnlPositive ? "+" : ""}$${metrics.total_pnl.toFixed(2)}`}
        icon={<Scale className="h-4 w-4" />}
        positive={pnlPositive}
        negative={!pnlPositive}
        hint={`${metrics.total_pnl_percent >= 0 ? "+" : ""}${metrics.total_pnl_percent.toFixed(2)}%`}
        className="col-span-2 sm:col-span-1 lg:col-span-1"
      />
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  icon?: React.ReactNode;
  positive?: boolean;
  negative?: boolean;
  hint?: string;
  footer?: React.ReactNode;
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
        <div className="mt-0.5 text-xs text-slate-500">{hint}</div>
      )}
      {footer}
    </div>
  );
}

export default PerformanceMetrics;
