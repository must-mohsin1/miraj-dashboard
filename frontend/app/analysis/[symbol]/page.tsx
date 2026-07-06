import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  ChevronRight,
  Clock,
  RefreshCw,
} from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverPost, ApiError } from "@/lib/api";
import type { ScanResult, TradePlanFlat } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { ScoreGauge } from "@/components/score-gauge";
import { TradePlan } from "@/components/trade-plan";
import { LiveCandlestickChart } from "@/components/live-candlestick-chart";
import { TradingGlossary } from "@/components/trading-glossary";
import { KillZoneClock } from "@/components/kill-zone-clock";
import { QqeSignalPanel } from "@/components/qqe-signal-panel";
import { StructurePanel } from "@/components/structure-panel";
import { PatternsPanel } from "@/components/patterns-panel";
import { BmsbStatus } from "@/components/bmsb-status";
import { SignalChangesPanel } from "@/components/signal-changes-panel";
import { MetricTrends } from "@/components/metric-trends";
import { ScoreProgressionChart } from "@/components/score-progression-chart";
import { MacroStrip } from "@/components/macro-strip";
import { ChartSkeleton } from "@/components/skeletons";

/**
 * Analysis detail page — async Server Component.
 *
 * Fetches a full scan result for `params.symbol` by calling
 * `POST /api/v1/scan/{symbol}` (path parameter, no request body) and renders:
 *
 *   - a circular score gauge (0–100) with a direction badge
 *   - the trade plan card (entry / ATR stop / T1–T3 with R:R ratios)
 *   - the candlestick chart (candles + volume + EMAs + OB/FVG zones)
 *   - the score breakdown (regime / location / confirmation / volume / risk)
 *
 * If the backend is unreachable or the symbol is invalid, the page renders an
 * error card with a back-link to `/analysis` instead of throwing a 500.
 */

/** Format an ISO-8601 timestamp as a human-readable "time ago". */
function formatRelative(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Human label for the direction. */
function directionMeta(direction: string | undefined | null) {
  const d = (direction ?? "NEUTRAL").toUpperCase();
  switch (d) {
    case "LONG":
      return { label: "LONG", className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50", arrow: "▲" };
    case "SHORT":
      return { label: "SHORT", className: "bg-red-500/10 text-red-400 border-red-700/50", arrow: "▼" };
    default:
      return { label: "NEUTRAL", className: "bg-slate-500/10 text-slate-400 border-slate-700/50", arrow: "■" };
  }
}

/** Render a single category sub-score bar. */
function CategoryBar({
  label,
  value,
  max = 6,
  color,
}: {
  label: string;
  value: number | null | undefined;
  max?: number;
  color: string;
}) {
  const v = value ?? 0;
  const pct = Math.max(0, Math.min(100, (v / max) * 100));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="capitalize text-slate-400">{label}</span>
        <span className="font-medium text-slate-300">
          {value != null ? `${v.toFixed(1)} / ${max}` : "—"}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

/** Pick a colour for a category bar based on its fraction of max. */
function barColor(fraction: number): string {
  if (fraction < 0.34) return "#ef4444"; // red
  if (fraction < 0.5) return "#f97316"; // orange
  if (fraction < 0.67) return "#eab308"; // yellow
  return "#22c55e"; // green
}

interface PageProps {
  params: Promise<{ symbol: string }>;
}

export default async function AnalysisDetailPage({ params }: PageProps) {
  const { symbol: rawSymbol } = await params;
  const symbol = decodeURIComponent(rawSymbol).toUpperCase();
  const token = await getAccessToken();

  let result: ScanResult | null = null;
  let error: string | null = null;
  let errorStatus: number | null = null;

  if (!token) {
    error = "Not authenticated. Please sign in to run an analysis.";
  } else {
    try {
      // POST /api/v1/scan/{symbol} — path parameter, no request body.
      // The backend returns the full ScanResult (score, trade plan, candles...).
      result = await serverPost<ScanResult>(
        `/api/v1/scan/${encodeURIComponent(symbol)}`,
        token
      );
    } catch (e) {
      if (e instanceof ApiError) {
        errorStatus = e.status;
        if (e.status === 400) {
          error = `Invalid symbol: '${symbol}' is not a valid trading pair.`;
        } else if (e.status === 502) {
          error =
            "The analysis backend is unavailable. The upstream market data provider (Yahoo Finance) may be unreachable. Please retry in a moment.";
        } else {
          error = e.message;
        }
      } else {
        error = "An unexpected error occurred while fetching the analysis.";
      }
    }
  }

  // ── Error state ─────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <header className="flex flex-col gap-1">
          <Link
            href="/analysis"
            className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Analysis
          </Link>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-emerald-400" />
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">
              {symbol}
            </h1>
          </div>
        </header>

        <div className="rounded-xl border border-red-800/50 bg-red-500/5 p-8 text-center">
          <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-red-400" />
          <h2 className="text-lg font-semibold text-slate-100">
            Analysis failed
          </h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
            {error}
          </p>
          {errorStatus && (
            <p className="mt-2 text-xs text-slate-500">
              HTTP {errorStatus}
            </p>
          )}
          {symbol && (
            <Link
              href={`/analysis/${encodeURIComponent(symbol)}`}
              className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-slate-700"
            >
              <RefreshCw className="h-4 w-4" />
              Retry analysis
            </Link>
          )}
        </div>
      </div>
    );
  }

  if (!result) {
    notFound();
  }

  // ── Extract data for the chart and trade plan ───────────────────────
  const overall = result.overall_score ?? result.confluence_score;
  const flat = result.trade_plan_flat;
  const direction = flat?.direction;
  const candles = result.candles ?? [];
  const dirMeta = directionMeta(direction);
  const cachedAt = formatRelative(result.cached_at);

  // Extract trade levels for the chart overlay
  const tradeTargets = flat
    ? [flat.target_1, flat.target_2, flat.target_3].filter(
        (t): t is number => t != null && !Number.isNaN(t)
      )
    : [];

  // Category scores from `scores` (regime, location, confirmation, volume_retest, risk)
  const scores = result.scores ?? {};
  const categoryMax: Record<string, number> = {
    regime: 6,
    location: 6,
    confirmation: 6,
    volume_retest: 5,
    risk: 5,
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      {/* ── Macro context strip (BTC.D, USDT.D, F&G, DXY, L/S) ── */}
      <MacroStrip />

      {/* Header */}
      <header className="flex flex-col gap-3">
        <Link
          href="/analysis"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Analysis
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-emerald-400" />
              <h1 className="text-2xl font-bold tracking-tight text-slate-100">
                {result.symbol}
              </h1>
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${dirMeta.className}`}
              >
                <span>{dirMeta.arrow}</span>
                {dirMeta.label}
              </span>
            </div>
            <p className="text-sm text-slate-400">
              Full confluence analysis: macro → OHLCV → indicators → QQE → SMC →
              patterns → trade plan.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {cachedAt && (
              <Badge
                variant="outline"
                className="border-slate-700 bg-slate-900/60 text-slate-300"
              >
                <Clock className="h-3 w-3" />
                {cachedAt}
              </Badge>
            )}
            {result.stale && (
              <Badge
                variant="outline"
                className="border-amber-700/50 bg-amber-500/10 text-amber-400"
              >
                <AlertTriangle className="h-3 w-3" />
                Cached (stale)
              </Badge>
            )}
          </div>
        </div>
      </header>

      {/* ── Metric Trends (compact trend arrows on key metrics) ── */}
      <MetricTrends
        symbol={result.symbol}
        token={token}
        currentScore={result.confluence_score}
        currentQqe={result.qqe_signals ?? null}
        currentStructure={result.structure ?? null}
        currentDirection={direction ?? null}
      />

      {/* Top row: Score gauge + Trade plan */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Score gauge */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
          <h3 className="mb-4 text-sm font-medium text-slate-300">
            Confluence Score
          </h3>
          <div className="flex items-center justify-center">
            <ScoreGauge score={overall} size={200} label="Score" />
          </div>
          <div className="mt-4 text-center text-xs text-slate-500">
            Raw: {result.confluence_score?.toFixed(1)} / 30
          </div>
        </div>

        {/* Trade plan */}
        <div className="lg:col-span-2">
          <TradePlan tradePlan={flat as TradePlanFlat | null} />
        </div>
      </section>

      {/* ICT kill-zone clock (live, above the chart) */}
      <KillZoneClock />

      {/* Candlestick chart (with live price streaming) */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <Suspense fallback={<ChartSkeleton />}>
          <LiveCandlestickChart
            candles={candles}
            emas={result.emas ?? null}
            orderBlocks={result.order_blocks ?? null}
            fvgs={result.fvgs ?? null}
            symbol={result.symbol}
            token={token}
            tradeLevels={{
              entry: flat?.entry ?? null,
              stopLoss: flat?.stop_loss ?? null,
              targets: tradeTargets,
            }}
          />
        </Suspense>
        <TradingGlossary />
      </section>

      {/* QQE Signals + Structure + Patterns + BMSB */}
      <div className="grid gap-4 md:grid-cols-2">
        <QqeSignalPanel signals={result.qqe_signals} />
        <StructurePanel structure={result.structure} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <PatternsPanel patterns={result.patterns} />
        <BmsbStatus bmsb={result.bmsb} />
      </div>

      {/* Score breakdown */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <h3 className="mb-4 text-sm font-medium text-slate-300">
          Score Breakdown
        </h3>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {(["regime", "location", "confirmation", "volume_retest", "risk"] as const).map(
            (cat) => {
              const val = scores[cat];
              const max = categoryMax[cat] ?? 6;
              const frac = val != null ? val / max : 0;
              const label = cat === "volume_retest" ? "Volume / Retest" : cat;
              return (
                <CategoryBar
                  key={cat}
                  label={label}
                  value={val}
                  max={max}
                  color={barColor(frac)}
                />
              );
            }
          )}
        </div>
      </section>

      {/* ── Signal Changes (last 5 between the two most recent scans) ── */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-300">
            Signal Changes
          </h3>
          <Link
            href={`/analysis/${encodeURIComponent(result.symbol)}/changes`}
            className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
          >
            View Full History
            <ChevronRight className="h-3 w-3" />
          </Link>
        </div>
        <SignalChangesPanel
          symbol={result.symbol}
          token={token}
          limit={5}
          variant="compact"
        />
      </section>

      {/* ── Score Progression Chart ── */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6">
        <h3 className="mb-4 text-sm font-medium text-slate-300">
          Score Progression
        </h3>
        <ScoreProgressionChart symbol={result.symbol} token={token} />
        <p className="mt-3 text-xs text-slate-500">
          Confluence score (0–30) across recent scans. Green zone ≥ 20
          indicates a valid trade setup; red zone &lt; 10 indicates no trade.
        </p>
      </section>
    </div>
  );
}
