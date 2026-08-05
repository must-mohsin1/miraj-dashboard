"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
import { StrategyInsightPanel } from "@/components/portfolio/strategy-insight-panel";
import { ClosedPositionBreakdowns } from "@/components/portfolio/closed-position-breakdowns";
import { ClosedPositionCalendar } from "@/components/portfolio/closed-position-calendar";
import {
  ClosedPositionFilters,
  DEFAULT_CLOSED_POSITION_FILTERS,
  type ClosedPositionFiltersValue,
} from "@/components/portfolio/closed-position-filters";
import {
  applyClosedPositionFiltersToSearchParams,
  closedPositionFiltersQueryFingerprint,
} from "@/components/portfolio/closed-position-url";
import { ClosedPositionBasisNote } from "@/components/portfolio/closed-position-basis-note";
import { ClosedPositionOverview } from "@/components/portfolio/closed-position-overview";
import { ClosedPositionPeriodChart } from "@/components/portfolio/closed-position-period-chart";
import { TradeExplorer } from "@/components/portfolio/trade-explorer";
import type {
  ClosedPositionAnalyticsResponse,
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
  /** Deep-link: which analytics sub-tab to open (e.g. `closed-positions`). */
  defaultAnalyticsTab?: string;
  /** Deep-link: seed closed-position symbols CSV filter. */
  initialSymbols?: string;
  /** Deep-link: full closed-position filter seed (wins over initialSymbols when set). */
  initialClosedFilters?: ClosedPositionFiltersValue;
}

const ANALYTICS_TAB_VALUES = new Set([
  "performance",
  "closed-positions",
  "calendar",
  "allocation",
  "attribution",
  "strategy",
  "health",
  "benchmark",
]);

type LoadingState = {
  performance: boolean;
  equity: boolean;
  daily: boolean;
  allocation: boolean;
  closed: boolean;
};

type ErrorState = {
  performance: string | null;
  equity: string | null;
  daily: string | null;
  allocation: string | null;
  closed: string | null;
};

function resolveAnalyticsTab(tab?: string): string {
  return tab && ANALYTICS_TAB_VALUES.has(tab) ? tab : "performance";
}

export function AnalyticsDashboard({
  token,
  exchange,
  defaultAnalyticsTab,
  initialSymbols,
  initialClosedFilters,
}: AnalyticsDashboardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [metrics, setMetrics] = useState<PerformanceMetricsType | null>(null);
  const [equity, setEquity] = useState<EquityCurveResponse | null>(null);
  const [equityResolution, setEquityResolution] = useState<"day" | "week" | "raw">("day");
  const [daily, setDaily] = useState<DailyPnlResponse | null>(null);
  const [allocation, setAllocation] = useState<AllocationResponse | null>(null);
  const [closedAnalytics, setClosedAnalytics] = useState<ClosedPositionAnalyticsResponse | null>(null);
  const [closedFilters, setClosedFilters] = useState<ClosedPositionFiltersValue>(() => {
    if (initialClosedFilters) {
      return { ...DEFAULT_CLOSED_POSITION_FILTERS, ...initialClosedFilters };
    }
    const symbols = String(initialSymbols ?? "").trim().toUpperCase();
    if (!symbols) return { ...DEFAULT_CLOSED_POSITION_FILTERS };
    return { ...DEFAULT_CLOSED_POSITION_FILTERS, symbols };
  });

  // Controlled analytics sub-tab — reacts when deep-link props change.
  const [analyticsTab, setAnalyticsTab] = useState(() =>
    resolveAnalyticsTab(defaultAnalyticsTab),
  );

  useEffect(() => {
    if (defaultAnalyticsTab && ANALYTICS_TAB_VALUES.has(defaultAnalyticsTab)) {
      setAnalyticsTab(defaultAnalyticsTab);
    }
  }, [defaultAnalyticsTab]);

  // Seed / re-seed when deep-link filter props change (e.g. Strategy → closed positions).
  useEffect(() => {
    if (initialClosedFilters) {
      const merged = { ...DEFAULT_CLOSED_POSITION_FILTERS, ...initialClosedFilters };
      setClosedFilters((prev) => {
        const nextFp = closedPositionFiltersQueryFingerprint(merged);
        const prevFp = closedPositionFiltersQueryFingerprint(prev);
        return nextFp === prevFp ? prev : merged;
      });
      return;
    }
    const symbols = String(initialSymbols ?? "").trim().toUpperCase();
    if (!symbols) return;
    setClosedFilters((prev) =>
      prev.symbols === symbols ? prev : { ...prev, symbols, offset: 0 },
    );
  }, [initialSymbols, initialClosedFilters]);

  // Mirror closed-position filters into the portfolio URL for shareable deep links.
  useEffect(() => {
    if (analyticsTab !== "closed-positions") return;
    if (!pathname) return;

    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("tab", "analytics");
    params.set("analytics_tab", "closed-positions");
    if (exchange) params.set("exchange", exchange);
    applyClosedPositionFiltersToSearchParams(params, closedFilters);

    const nextQuery = params.toString();
    const currentQuery = searchParams?.toString() ?? "";
    if (nextQuery === currentQuery) return;
    router.replace(`${pathname}?${nextQuery}`, { scroll: false });
  }, [analyticsTab, closedFilters, exchange, pathname, router, searchParams]);

  const [loading, setLoading] = useState<LoadingState>({
    performance: true,
    equity: true,
    daily: true,
    allocation: true,
    closed: true,
  });
  const [errors, setErrors] = useState<ErrorState>({
    performance: null,
    equity: null,
    daily: null,
    allocation: null,
    closed: null,
  });

  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const closedPositionQuery = useMemo(
    () => buildClosedPositionQuery(closedFilters),
    [closedFilters],
  );

  // Fetch all analytics data on mount / exchange change.
  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      setLoading({
        performance: true,
        equity: true,
        daily: true,
        allocation: true,
        closed: true,
      });
      setErrors({
        performance: null,
        equity: null,
        daily: null,
        allocation: null,
        closed: null,
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

      // Equity curve (resolution: day | week | raw)
      setLoading((s) => ({ ...s, equity: true }));
      fetch(
        `${base}/equity-curve?resolution=${encodeURIComponent(equityResolution)}`,
        { headers },
      )
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

      // Phase 1 closed-position analytics: one shared server-side filter query
      fetch(`${base}/closed-position-analytics?${closedPositionQuery}`, { headers })
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((data: ClosedPositionAnalyticsResponse) => {
          if (!cancelled) {
            setClosedAnalytics(data);
            setLoading((s) => ({ ...s, closed: false }));
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setErrors((e) => ({
              ...e,
              closed: String(err) || "Failed to load",
            }));
            setLoading((s) => ({ ...s, closed: false }));
          }
        });
    }

    fetchAll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token, closedPositionQuery, equityResolution]);

  return (
    <Tabs value={analyticsTab} onValueChange={setAnalyticsTab} className="w-full">
      <TabsList>
        <TabsTrigger value="performance">Performance</TabsTrigger>
        <TabsTrigger value="closed-positions">Closed Positions</TabsTrigger>
        <TabsTrigger value="calendar">P&amp;L Calendar</TabsTrigger>
        <TabsTrigger value="allocation">Allocation</TabsTrigger>
        <TabsTrigger value="attribution">Trade Attribution</TabsTrigger>
        <TabsTrigger value="strategy">Strategy</TabsTrigger>
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
              markers={equity?.markers ?? []}
              basis={equity?.basis ?? null}
              settlementAsset={equity?.settlement_asset ?? null}
              unavailableReason={equity?.unavailable_reason ?? null}
              asOf={equity?.as_of ?? null}
              resolution={equityResolution}
              pointCountRaw={equity?.point_count_raw ?? null}
              pointCountReturned={equity?.point_count_returned ?? null}
              onResolutionChange={setEquityResolution}
            />
          )}
        </div>
      </TabsContent>

      {/* ── Phase 1: Closed-position intelligence ── */}
      <TabsContent value="closed-positions">
        <div className="grid gap-6">
          <ClosedPositionBasisNote
            basis={closedAnalytics?.basis ?? null}
            history={closedAnalytics?.history ?? null}
          />
          <ClosedPositionFilters
            value={closedFilters}
            onChange={setClosedFilters}
            disabled={loading.closed}
          />
          <ClosedPositionOverview
            overview={closedAnalytics?.overview ?? null}
            basis={closedAnalytics?.basis ?? null}
            history={closedAnalytics?.history ?? null}
            unavailable={closedAnalytics?.unavailable ?? null}
            loading={loading.closed}
            error={errors.closed}
          />
          <ClosedPositionPeriodChart
            items={closedAnalytics?.periods.items ?? []}
            totals={closedAnalytics?.periods.totals ?? { trade_count: 0, total_pnl: null }}
            period={closedAnalytics?.periods.period ?? closedFilters.period}
            filtersApplied={closedAnalytics?.filters_applied ?? null}
            basis={closedAnalytics?.basis ?? null}
            history={closedAnalytics?.history ?? null}
            loading={loading.closed}
            error={errors.closed}
          />
          <ClosedPositionCalendar
            days={closedAnalytics?.calendar_days ?? []}
            totals={closedAnalytics?.periods.totals ?? { trade_count: 0, total_pnl: null }}
            filtersApplied={closedAnalytics?.filters_applied ?? null}
            basis={closedAnalytics?.basis ?? null}
            history={closedAnalytics?.history ?? null}
            loading={loading.closed}
            error={errors.closed}
          />
          <ClosedPositionBreakdowns
            breakdowns={closedAnalytics?.breakdowns ?? {}}
            concentration={closedAnalytics?.concentration ?? null}
            excludedReasons={closedAnalytics?.excluded_reasons ?? null}
            basis={closedAnalytics?.basis ?? null}
            history={closedAnalytics?.history ?? null}
            loading={loading.closed}
            error={errors.closed}
          />
          <TradeExplorer
            data={closedAnalytics?.explorer ?? null}
            loading={loading.closed}
            error={errors.closed}
            token={token}
            exchange={exchange}
            onPageChange={(offset) => setClosedFilters((filters) => ({ ...filters, offset }))}
            onPageSizeChange={(limit) => setClosedFilters((filters) => ({ ...filters, limit, offset: 0 }))}
            onSortChange={(sort) =>
              setClosedFilters((filters) => ({
                ...filters,
                sort: sort as ClosedPositionFiltersValue["sort"],
                offset: 0,
              }))
            }
          />
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

      {/* ── Tab 5: Strategy / journal loop (Phase 4) ── */}
      <TabsContent value="strategy">
        <StrategyInsightPanel token={token} exchange={exchange} />
      </TabsContent>

      {/* ── Tab 6: Health Score ── */}
      <TabsContent value="health">
        <HealthScorePanel token={token} exchange={exchange} />
      </TabsContent>

      {/* ── Tab 7: Benchmark ── */}
      <TabsContent value="benchmark">
        <BenchmarkComparison token={token} exchange={exchange} />
      </TabsContent>
    </Tabs>
  );
}

function buildClosedPositionQuery(filters: ClosedPositionFiltersValue): string {
  const params = new URLSearchParams();
  params.set("timezone", filters.timezone || "UTC");
  params.set("period", filters.period);
  params.set("limit", String(filters.limit));
  params.set("offset", String(filters.offset));
  params.set("sort", filters.sort);

  for (const key of [
    "from",
    "to",
    "symbols",
    "side",
    "leverage_min",
    "leverage_max",
    "duration_min_minutes",
    "duration_max_minutes",
    "close_reason",
    "pnl_min",
    "pnl_max",
  ] as const) {
    const value = filters[key];
    if (typeof value === "string" && value.trim()) {
      params.set(key, value.trim());
    }
  }

  return params.toString();
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
