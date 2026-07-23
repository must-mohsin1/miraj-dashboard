"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PerformanceMetrics } from "@/components/portfolio/performance-metrics";
import { EquityCurve } from "@/components/portfolio/equity-curve";
import { PnlHeatmap } from "@/components/portfolio/pnl-heatmap";
import { AllocationPie } from "@/components/portfolio/allocation-pie";
import { TradeAttributionTable } from "@/components/portfolio/trade-attribution-table";
import { ScanAccuracyChart } from "@/components/portfolio/scan-accuracy-chart";
import { HealthScorePanel } from "@/components/portfolio/health-score-panel";
import { BenchmarkComparison } from "@/components/portfolio/benchmark-comparison";
import type {
  PerformanceMetrics as PerformanceMetricsType,
  EquityCurveResponse,
  DailyPnlResponse,
  AllocationResponse,
} from "@/lib/types";

/**
 * AnalyticsDashboard — Client Component.
 *
 * Combines all analytics components in a tabbed view:
 *  - Tab 1: Performance (metrics cards + equity curve)
 *  - Tab 2: P&L Calendar (heatmap)
 *  - Tab 3: Allocation (pie + per-asset table)
 *  - Tab 4: Trade Attribution (per-trade P&L breakdown)
 *  - Tab 5: Health Score (grade + metric bars + recommendations)
 *  - Tab 6: Benchmark (portfolio vs BTC buy-and-hold comparison)
 *
 * Fetches data from the analytics endpoints on mount and on exchange change.
 * The Health Score and Benchmark tabs fetch internally (self-refreshing).
 */

interface AnalyticsDashboardProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token: string | null;
  /** Exchange slug (e.g. "mexc", "binance", "bybit"). */
  exchange: string;
}

type LoadingState = {
  performance: boolean;
  equity: boolean;
  daily: boolean;
  allocation: boolean;
};

type ErrorState = {
  performance: string | null;
  equity: string | null;
  daily: string | null;
  allocation: string | null;
};

export function AnalyticsDashboard({ token, exchange }: AnalyticsDashboardProps) {
  const [metrics, setMetrics] = useState<PerformanceMetricsType | null>(null);
  const [equity, setEquity] = useState<EquityCurveResponse | null>(null);
  const [daily, setDaily] = useState<DailyPnlResponse | null>(null);
  const [allocation, setAllocation] = useState<AllocationResponse | null>(null);

  const [loading, setLoading] = useState<LoadingState>({
    performance: true,
    equity: true,
    daily: true,
    allocation: true,
  });
  const [errors, setErrors] = useState<ErrorState>({
    performance: null,
    equity: null,
    daily: null,
    allocation: null,
  });

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  // Fetch all analytics data on mount / exchange change.
  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      setLoading({
        performance: true,
        equity: true,
        daily: true,
        allocation: true,
      });
      setErrors({
        performance: null,
        equity: null,
        daily: null,
        allocation: null,
      });

      const base = `/api/v1/analytics/${exchange}`;

      // Performance metrics
      fetch(`${base}/performance`, { headers })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((data: PerformanceMetricsType) => {
          if (!cancelled) {
            setMetrics(data);
            setLoading((s) => ({ ...s, performance: false }));
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setErrors((e) => ({
              ...e,
              performance: String(err) || "Failed to load",
            }));
            setLoading((s) => ({ ...s, performance: false }));
          }
        });

      // Equity curve
      fetch(`${base}/equity-curve`, { headers })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((data: EquityCurveResponse) => {
          if (!cancelled) {
            setEquity(data);
            setLoading((s) => ({ ...s, equity: false }));
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setErrors((e) => ({
              ...e,
              equity: String(err) || "Failed to load",
            }));
            setLoading((s) => ({ ...s, equity: false }));
          }
        });

      // Daily PnL
      fetch(`${base}/daily-pnl`, { headers })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((data: DailyPnlResponse) => {
          if (!cancelled) {
            setDaily(data);
            setLoading((s) => ({ ...s, daily: false }));
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setErrors((e) => ({
              ...e,
              daily: String(err) || "Failed to load",
            }));
            setLoading((s) => ({ ...s, daily: false }));
          }
        });

      // Allocation
      fetch(`${base}/allocation`, { headers })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((data: AllocationResponse) => {
          if (!cancelled) {
            setAllocation(data);
            setLoading((s) => ({ ...s, allocation: false }));
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setErrors((e) => ({
              ...e,
              allocation: String(err) || "Failed to load",
            }));
            setLoading((s) => ({ ...s, allocation: false }));
          }
        });
    }

    fetchAll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  const anyLoading =
    loading.performance || loading.equity || loading.daily || loading.allocation;

  return (
    <Tabs defaultValue="performance" className="w-full">
      <TabsList>
        <TabsTrigger value="performance">Performance</TabsTrigger>
        <TabsTrigger value="calendar">P&amp;L Calendar</TabsTrigger>
        <TabsTrigger value="allocation">Allocation</TabsTrigger>
        <TabsTrigger value="attribution">Trade Attribution</TabsTrigger>
        <TabsTrigger value="health">Health Score</TabsTrigger>
        <TabsTrigger value="benchmark">Benchmark</TabsTrigger>
      </TabsList>

      {/* ── Tab 1: Performance ── */}
      <TabsContent value="performance">
        <div className="flex flex-col gap-4">
          {errors.performance ? (
            <ErrorBanner message={errors.performance} />
          ) : loading.performance ? (
            <LoadingState label="Loading metrics…" />
          ) : (
            <PerformanceMetrics metrics={metrics} />
          )}

          {errors.equity ? (
            <ErrorBanner message={errors.equity} />
          ) : loading.equity ? (
            <LoadingState label="Loading equity curve…" />
          ) : (
            <EquityCurve
              points={equity?.points ?? []}
              basis={equity?.basis ?? null}
              unavailableReason={equity?.unavailable_reason ?? null}
            />
          )}
        </div>
      </TabsContent>

      {/* ── Tab 2: P&L Calendar ── */}
      <TabsContent value="calendar">
        <div className="flex flex-col gap-4">
          {errors.daily ? (
            <ErrorBanner message={errors.daily} />
          ) : loading.daily ? (
            <LoadingState label="Loading daily P&L…" />
          ) : (
            <PnlHeatmap days={daily?.days ?? []} timezone={daily?.timezone ?? "UTC"} />
          )}

          {/* Daily PnL summary table */}
          {daily && daily.days.length > 0 && (
            <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
              <div className="border-b border-slate-800 px-4 py-3">
                <h3 className="text-sm font-medium text-slate-300">
                  Daily P&amp;L Breakdown
                </h3>
              </div>
              <div className="max-h-64 overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-slate-800 hover:bg-transparent">
                      <TableHead className="text-slate-500">Date</TableHead>
                      <TableHead className="text-right text-slate-500">PnL</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...daily.days].reverse().map((d) => (
                      <TableRow
                        key={d.date}
                        className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
                      >
                        <TableCell className="text-slate-300 tabular-nums">
                          {d.date}
                        </TableCell>
                        <TableCell
                          className={`text-right font-semibold tabular-nums ${
                            d.pnl >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {d.pnl >= 0 ? "+" : ""}
                          {d.pnl.toFixed(2)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </div>
      </TabsContent>

      {/* ── Tab 3: Allocation ── */}
      <TabsContent value="allocation">
        <div className="flex flex-col gap-4">
          {errors.allocation ? (
            <ErrorBanner message={errors.allocation} />
          ) : loading.allocation ? (
            <LoadingState label="Loading allocation…" />
          ) : allocation && allocation.items.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <AllocationPie accountType={allocation.account_type} items={allocation.items} />
              <AllocationTable items={allocation.items} />
            </div>
          ) : (
            <AllocationPie items={[]} />
          )}
        </div>
      </TabsContent>

      {/* ── Tab 4: Trade Attribution ── */}
      <TabsContent value="attribution">
        <div className="flex flex-col gap-4">
          <TradeAttributionTable token={token} exchange={exchange} />
          <ScanAccuracyChart token={token} exchange={exchange} />
        </div>
      </TabsContent>

      {/* ── Tab 5: Health Score ── */}
      <TabsContent value="health">
        <HealthScorePanel token={token} exchange={exchange} />
      </TabsContent>

      {/* ── Tab 6: Benchmark ── */}
      <TabsContent value="benchmark">
        <BenchmarkComparison token={token} exchange={exchange} />
      </TabsContent>
    </Tabs>
  );
}

/** Per-asset allocation table (detailed breakdown beside the pie). */
function AllocationTable({
  items,
}: {
  items: NonNullable<AllocationResponse["items"]>;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="border-b border-slate-800 px-4 py-3">
        <h3 className="text-sm font-medium text-slate-300">Per-Asset Breakdown</h3>
      </div>
      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-500">Asset</TableHead>
            <TableHead className="text-right text-slate-500">USD Value</TableHead>
            <TableHead className="text-right text-slate-500">%</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow
              key={item.asset}
              className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
            >
              <TableCell className="font-medium text-slate-100">
                {item.asset}
              </TableCell>
              <TableCell className="text-right font-semibold text-emerald-400 tabular-nums">
                ${item.usd_value.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </TableCell>
              <TableCell className="text-right text-slate-400 tabular-nums">
                {item.percentage.toFixed(2)}%
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-sm text-slate-400">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
      {message}
    </div>
  );
}

export default AnalyticsDashboard;
