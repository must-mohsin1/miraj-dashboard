import Link from "next/link";
import { redirect } from "next/navigation";
import { BarChart3, ChevronRight, Clock } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { ScanHistoryResponse } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { AnalysisSearchForm } from "@/components/analysis-search-form";

/**
 * Analysis landing page — async Server Component.
 *
 * Renders a symbol search form (client component for interactivity) plus the
 * user's recent analyses from `GET /api/v1/history`. When the URL carries a
 * `?symbol=BTC-USD` query param, the page server-redirects to the full
 * analysis detail route `/analysis/{symbol}` which runs the scan.
 *
 * This mirrors the Streamlit analysis page behaviour: query-param symbol
 * auto-loads, and a form lets the user pick a new pair.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders an empty history list with a notice instead of
 * throwing.
 */

export const dynamic = "force-dynamic";

interface SearchParams {
  symbol?: string;
}

interface PageProps {
  searchParams: Promise<SearchParams>;
}

export default async function AnalysisPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const querySymbol = params.symbol?.trim();

  // If a symbol is provided via ?symbol=..., redirect to the detail page
  // which runs the scan server-side.
  if (querySymbol) {
    redirect(`/analysis/${encodeURIComponent(querySymbol.toUpperCase())}`);
  }

  const token = await getAccessToken();

  // Fetch recent analyses (first page) for the table
  let history: ScanHistoryResponse | null = null;
  if (token) {
    try {
      history = await serverFetch<ScanHistoryResponse>(
        "/api/v1/history?per_page=10",
        token
      );
    } catch {
      // Swallow transient backend errors — render an empty table
      history = null;
    }
  }

  const rows = history?.rows ?? [];

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      {/* Header */}
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Analysis
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Run a full confluence analysis on any trading pair, or review recent
          saved analyses.
        </p>
      </header>

      {/* Symbol search form */}
      <section aria-label="Run analysis">
        <AnalysisSearchForm token={token} />
      </section>

      {/* Recent analyses */}
      <section aria-label="Recent analyses">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">
            Recent Analyses
          </h2>
          {history && history.total > rows.length && (
            <Link
              href="/history"
              className="text-sm text-emerald-400 hover:text-emerald-300"
            >
              View all ({history.total}) →
            </Link>
          )}
        </div>

        {rows.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center">
            <BarChart3 className="mx-auto mb-3 h-8 w-8 text-slate-600" />
            <p className="text-sm text-slate-400">
              No analyses yet. Enter a symbol above and click{" "}
              <span className="font-medium text-slate-200">Analyze</span> to run
              your first scan.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                  <th className="px-4 py-3 font-medium">Symbol</th>
                  <th className="px-4 py-3 font-medium">Score</th>
                  <th className="px-4 py-3 font-medium">Direction</th>
                  <th className="hidden px-4 py-3 font-medium sm:table-cell">
                    Type
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      Date
                    </span>
                  </th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const dirMeta = directionMetaRow(row.direction);
                  return (
                    <tr
                      key={row.id}
                      className="border-b border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
                    >
                      <td className="px-4 py-3">
                        <Link
                          href={`/analysis/${encodeURIComponent(row.symbol)}`}
                          className="font-medium text-slate-100 hover:text-emerald-400"
                        >
                          {row.symbol}
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        {row.score != null ? (
                          <span
                            className="font-semibold"
                            style={{ color: scoreColorRow(row.score) }}
                          >
                            {row.score.toFixed(1)}
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {row.direction ? (
                          <Badge
                            variant="outline"
                            className={dirMeta.className}
                          >
                            {dirMeta.arrow} {row.direction}
                          </Badge>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                      <td className="hidden px-4 py-3 text-slate-400 sm:table-cell">
                        {row.analysis_type}
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {new Date(row.created_at).toLocaleString(undefined, {
                          dateStyle: "short",
                          timeStyle: "short",
                        })}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/analysis/${encodeURIComponent(row.symbol)}`}
                          className="inline-flex items-center text-slate-500 hover:text-emerald-400"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* ── Helpers (duplicated minimally from the detail page to avoid a client/
 *    server boundary — these are small pure functions) ───────────────────── */

function scoreColorRow(score: number): string {
  if (score < 30) return "#ef4444";
  if (score < 50) return "#f97316";
  if (score < 70) return "#eab308";
  return "#22c55e";
}

function directionMetaRow(direction: string | null | undefined) {
  const d = (direction ?? "NEUTRAL").toUpperCase();
  switch (d) {
    case "LONG":
      return {
        label: "LONG",
        className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
        arrow: "▲" as const,
      };
    case "SHORT":
      return {
        label: "SHORT",
        className: "bg-red-500/10 text-red-400 border-red-700/50",
        arrow: "▼" as const,
      };
    default:
      return {
        label: "NEUTRAL",
        className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
        arrow: "■" as const,
      };
  }
}
