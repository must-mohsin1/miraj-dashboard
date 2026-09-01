import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  Clock,
  RefreshCw,
} from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverPost, ApiError } from "@/lib/api";
import type { ScanResult, TradePlanFlat } from "@/lib/types";
import { TradePlan } from "@/components/trade-plan";
import { VerdictCard } from "@/components/verdict-card";
import { SetupBoard } from "@/components/setup-board";
import { TfConfluenceMatrix } from "@/components/tf-confluence-matrix";
import { LiveCandlestickChart } from "@/components/live-candlestick-chart";
import { TradingGlossary } from "@/components/trading-glossary";
import { KillZoneClock } from "@/components/kill-zone-clock";
import { QqeSignalPanel } from "@/components/qqe-signal-panel";
import { StructurePanel } from "@/components/structure-panel";
import { PatternsPanel } from "@/components/patterns-panel";
import { BmsbStatus } from "@/components/bmsb-status";
import { SignalChangesPanel } from "@/components/signal-changes-panel";
import { DcaStrategyPanel } from "@/components/dca-strategy-panel";
import { ChartSkeleton } from "@/components/skeletons";

/**
 * Analysis detail page — async Server Component.
 *
 * Fetches a full scan result for `params.symbol` by calling
 * `POST /api/v1/scan/{symbol}` (path parameter, no request body) and renders:
 *
 *   - the verdict (NO TRADE stays NO TRADE)
 *   - long/short candidate cards with levels and indicator facts
 *   - the trade plan only when READY
 *   - the candlestick chart (timeframes, indicators, drawing tools)
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
      return { label: "LONG", className: "border-[#6CA98F]/50 text-[#6CA98F]", arrow: "▲" };
    case "SHORT":
      return { label: "SHORT", className: "border-[#C96A55]/50 text-[#C96A55]", arrow: "▼" };
    default:
      return { label: "NEUTRAL", className: "border-[#2A2620] text-[#8E8778]", arrow: "■" };
  }
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

  if (error) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <header className="flex flex-col gap-1">
          <Link
            href="/analysis"
            className="inline-flex items-center gap-1.5 text-sm text-[#8E8778] hover:text-[#EDE7DB]"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Analysis
          </Link>
          <h1 className="font-verdict text-4xl text-[#EDE7DB]">{symbol}</h1>
        </header>
        <div className="border border-[#2A2620] bg-[#161411] p-6">
          <AlertTriangle className="mb-3 h-6 w-6 text-[#C96A55]" />
          <h2 className="text-lg text-[#EDE7DB]">Analysis failed.</h2>
          <p className="mt-2 max-w-md text-sm text-[#8E8778]">{error}</p>
          {errorStatus && <p className="mt-2 font-mono text-xs text-[#8E8778]">HTTP {errorStatus}</p>}
          <Link
            href={`/analysis/${encodeURIComponent(symbol)}`}
            className="mt-4 inline-flex items-center gap-1.5 border border-[#2A2620] px-4 py-2 text-sm text-[#EDE7DB]"
          >
            <RefreshCw className="h-4 w-4" />
            Retry analysis
          </Link>
        </div>
      </div>
    );
  }

  if (!result) {
    notFound();
  }

  const flat = result.trade_plan_flat;
  const direction = result.verdict?.bias ?? flat?.direction;
  const candles = result.candles ?? [];
  const dirMeta = directionMeta(direction);
  const cachedAt = formatRelative(result.cached_at);
  const ready =
    result.verdict?.state === "READY_LONG" || result.verdict?.state === "READY_SHORT";
  const tradeTargets = flat
    ? [flat.target_1, flat.target_2, flat.target_3].filter(
        (t): t is number => t != null && !Number.isNaN(t)
      )
    : [];
  const scores = result.scores ?? {};
  const categoryMax: Record<string, number> = {
    regime: 6,
    location: 6,
    confirmation: 6,
    volume_retest: 5,
    risk: 5,
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <header className="flex flex-col gap-3">
        <Link
          href="/analysis"
          className="inline-flex items-center gap-1.5 text-sm text-[#8E8778] hover:text-[#EDE7DB]"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Analysis
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
              Analysis
            </p>
            <div className="mt-1 flex items-baseline gap-3">
              <h1 className="font-verdict text-4xl text-[#EDE7DB] sm:text-5xl">{result.symbol}</h1>
              <span className={`inline-flex items-center gap-1 border px-2.5 py-0.5 text-xs font-semibold ${dirMeta.className}`}>
                <span>{dirMeta.arrow}</span>
                {dirMeta.label}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-[#8E8778]">
            {cachedAt && (
              <span className="inline-flex items-center gap-1 border border-[#2A2620] px-2 py-1">
                <Clock className="h-3 w-3" />
                {cachedAt}
              </span>
            )}
            {result.stale && (
              <span className="inline-flex items-center gap-1 border border-[#D19A4A]/40 px-2 py-1 text-[#D19A4A]">
                <AlertTriangle className="h-3 w-3" />
                Cached
              </span>
            )}
          </div>
        </div>
        <hr className="rule-brass border-0" />
      </header>

      <VerdictCard verdict={result.verdict} />

      <SetupBoard
        orderBlocks={result.order_blocks}
        price={candles.length > 0 ? candles[candles.length - 1].close : null}
        verdict={result.verdict}
        rsi={result.rsi}
        macd={result.macd}
        qqe={result.qqe_signals}
        structure={result.structure}
      />
      <TfConfluenceMatrix structure={result.structure} qqe={result.qqe_signals} />

      {ready && flat?.entry != null && (
        <TradePlan tradePlan={flat as TradePlanFlat} />
      )}

      <KillZoneClock />

      <section className="border border-[#2A2620] bg-[#161411] p-4">
        <Suspense fallback={<ChartSkeleton />}>
          <LiveCandlestickChart
            candles={candles}
            emas={result.emas ?? null}
            orderBlocks={result.order_blocks ?? null}
            fvgs={result.fvgs ?? null}
            rsi={result.rsi ?? null}
            macd={result.macd ?? null}
            bb={result.bb ?? null}
            symbol={result.symbol}
            token={token}
            tradeLevels={
              ready
                ? {
                    entry: flat?.entry ?? null,
                    stopLoss: flat?.stop_loss ?? null,
                    targets: tradeTargets,
                  }
                : null
            }
          />
        </Suspense>
        <TradingGlossary />
      </section>

      <DcaStrategyPanel
        tradePlan={result.trade_plan}
        confluenceScore={result.confluence_score}
        qqeSignals={result.qqe_signals}
        indicators={result.indicators}
        bmsb={result.bmsb}
        direction={direction ?? null}
      />

      <div className="grid gap-4 md:grid-cols-2">
        <QqeSignalPanel signals={result.qqe_signals} />
        <StructurePanel structure={result.structure} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <PatternsPanel patterns={result.patterns} />
        <BmsbStatus bmsb={result.bmsb} />
      </div>

      <section className="border border-[#2A2620] bg-[#161411] p-4">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          Score breakdown
        </h3>
        <dl className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(["regime", "location", "confirmation", "volume_retest", "risk"] as const).map((cat) => {
            const val = scores[cat];
            const max = categoryMax[cat] ?? 6;
            const label = cat === "volume_retest" ? "Volume / retest" : cat;
            return (
              <div key={cat} className="flex items-baseline justify-between border-t border-[#2A2620] pt-2">
                <dt className="text-xs capitalize text-[#8E8778]">{label}</dt>
                <dd className="font-mono text-sm text-[#EDE7DB]">
                  {val != null ? `${val.toFixed(1)} / ${max}` : "—"}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>

      <section className="border border-[#2A2620] bg-[#161411] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
            Signal changes
          </h3>
          <Link
            href={`/analysis/${encodeURIComponent(result.symbol)}/changes`}
            className="inline-flex items-center gap-1 text-xs text-[#C2A36B]"
          >
            Full history
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
    </div>
  );
}
