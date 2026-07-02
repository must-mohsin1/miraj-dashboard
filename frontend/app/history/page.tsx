import Link from "next/link";
import { ChevronLeft, ChevronRight, Clock, History } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { ScanHistoryResponse } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/**
 * History page — async Server Component.
 *
 * Renders a paginated table of past analyses from `GET /api/v1/history`.
 * Page and per_page are controlled via URL query params (`?page=2&per_page=20`).
 * Each row links to `/analysis/{symbol}` for the detail view.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders an empty table with a notice instead of throwing.
 */

export const dynamic = "force-dynamic";

interface SearchParams {
  page?: string;
  per_page?: string;
}

interface PageProps {
  searchParams: Promise<SearchParams>;
}

const PER_PAGE_DEFAULT = 20;

export default async function HistoryPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, parseInt(params.page ?? "1", 10) || 1);
  const perPage = Math.min(
    100,
    Math.max(1, parseInt(params.per_page ?? String(PER_PAGE_DEFAULT), 10) || PER_PAGE_DEFAULT)
  );

  const token = await getAccessToken();

  let history: ScanHistoryResponse | null = null;
  if (token) {
    try {
      history = await serverFetch<ScanHistoryResponse>(
        `/api/v1/history?page=${page}&per_page=${perPage}`,
        token
      );
    } catch {
      history = null;
    }
  }

  const rows = history?.rows ?? [];
  const total = history?.total ?? 0;
  const currentPage = history?.page ?? page;
  const pages = history?.pages ?? 1;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      {/* Header */}
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <History className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Analysis History
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          {total > 0
            ? `${total} past ${total === 1 ? "analysis" : "analyses"} — page ${currentPage} of ${pages}.`
            : "Browse your past confluence analyses."}
        </p>
      </header>

      {/* Table */}
      {rows.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center">
          <History className="mx-auto mb-3 h-8 w-8 text-slate-600" />
          <p className="text-sm text-slate-400">
            No analyses yet. Run a scan from the{" "}
            <Link
              href="/scanner"
              className="text-emerald-400 hover:text-emerald-300"
            >
              Scanner
            </Link>{" "}
            or{" "}
            <Link
              href="/analysis"
              className="text-emerald-400 hover:text-emerald-300"
            >
              Analysis
            </Link>{" "}
            page.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
          <Table>
            <TableHeader>
              <TableRow className="border-slate-800 hover:bg-transparent">
                <TableHead className="text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    Date
                  </span>
                </TableHead>
                <TableHead className="text-slate-500">Symbol</TableHead>
                <TableHead className="text-slate-500">Score</TableHead>
                <TableHead className="text-slate-500">Direction</TableHead>
                <TableHead className="text-slate-500">Type</TableHead>
                <TableHead className="text-right text-slate-500">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const dirMeta = directionMeta(row.direction);
                return (
                  <TableRow
                    key={row.id}
                    className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30"
                  >
                    <TableCell className="text-slate-400">
                      {new Date(row.created_at).toLocaleString(undefined, {
                        dateStyle: "short",
                        timeStyle: "short",
                      })}
                    </TableCell>
                    <TableCell className="font-medium text-slate-100">
                      {row.symbol}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {row.score != null ? (
                        <span
                          className="font-semibold"
                          style={{ color: scoreColor(row.score) }}
                        >
                          {row.score.toFixed(1)}
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </TableCell>
                    <TableCell>
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
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {row.analysis_type}
                    </TableCell>
                    <TableCell className="text-right">
                      <Link
                        href={`/analysis/${encodeURIComponent(row.symbol)}`}
                        className="inline-flex items-center gap-1 text-sm text-emerald-400 hover:text-emerald-300"
                      >
                        View
                        <ChevronRight className="h-4 w-4" />
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <nav className="flex items-center justify-center gap-2" aria-label="Pagination">
          {currentPage > 1 ? (
            <Link
              href={`/history?page=${currentPage - 1}&per_page=${perPage}`}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Link>
          ) : (
            <span className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-1.5 text-sm text-slate-600">
              <ChevronLeft className="h-4 w-4" />
              Previous
            </span>
          )}
          <span className="px-2 text-sm text-slate-400">
            Page {currentPage} of {pages}
          </span>
          {currentPage < pages ? (
            <Link
              href={`/history?page=${currentPage + 1}&per_page=${perPage}`}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Link>
          ) : (
            <span className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-1.5 text-sm text-slate-600">
              Next
              <ChevronRight className="h-4 w-4" />
            </span>
          )}
        </nav>
      )}
    </div>
  );
}

/* ── Helpers (pure functions, duplicated from the analysis page which lives
 *    on a different server/client boundary — kept minimal) ─────────────── */

function scoreColor(score: number): string {
  if (score < 30) return "#ef4444";
  if (score < 50) return "#f97316";
  if (score < 70) return "#eab308";
  return "#22c55e";
}

function directionMeta(direction: string | null | undefined) {
  const d = (direction ?? "NEUTRAL").toUpperCase();
  switch (d) {
    case "LONG":
      return {
        className: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
        arrow: "▲" as const,
      };
    case "SHORT":
      return {
        className: "bg-red-500/10 text-red-400 border-red-700/50",
        arrow: "▼" as const,
      };
    default:
      return {
        className: "bg-slate-500/10 text-slate-400 border-slate-700/50",
        arrow: "■" as const,
      };
  }
}
