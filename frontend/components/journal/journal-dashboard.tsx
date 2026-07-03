"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, BookOpen, Loader2, Plus, Tag } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JournalEntryDialog } from "@/components/journal/journal-entry-dialog";
import { JournalList } from "@/components/journal/journal-list";
import { cn } from "@/lib/utils";
import type {
  JournalListResponse,
  JournalSummaryResponse,
  TradeJournalEntry,
} from "@/lib/types";

/**
 * JournalDashboard — Client Component.
 *
 * Combines the journal entry list, create/edit dialog, and tag-summary cards.
 *
 * Data flow:
 *  - Fetches entries from `GET /api/v1/journal` on mount + after any
 *    create/update/delete mutation.
 *  - Fetches tag aggregates from `GET /api/v1/analytics/{exchange}/journal-summary`
 *    on mount + after mutations.
 *  - The JWT token is fetched client-side via `/api/auth/session` (same
 *    pattern as the portfolio dashboard), because this component may be
 *    rendered without a server-passed token prop.
 *
 * Layout:
 *  - Header with title + "Add Entry" button
 *  - Tag summary cards grid (PnL + win rate per tag)
 *  - Journal list table with filters + expandable rows
 *  - The entry dialog (controlled; open state owned here)
 */

interface JournalDashboardProps {
  /** The signed-in user's JWT access token (or null when unauthenticated). */
  token?: string | null;
  /** Exchange slug for the analytics summary (default "mexc"). */
  exchange?: string;
}

export function JournalDashboard({
  token: tokenProp,
  exchange = "mexc",
}: JournalDashboardProps) {
  const [entries, setEntries] = useState<TradeJournalEntry[]>([]);
  const [summary, setSummary] = useState<JournalSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dialog state.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState<TradeJournalEntry | null>(null);

  /** Fetch the JWT token — use the prop if provided, otherwise hit the
   * Next.js auth session endpoint (client-side). */
  const getToken = useCallback(async (): Promise<string | null> => {
    if (tokenProp) return tokenProp;
    try {
      const res = await fetch("/api/auth/session");
      const data = await res.json();
      return data?.user?.accessToken ?? null;
    } catch {
      return null;
    }
  }, [tokenProp]);

  /** Fetch the journal entries list. */
  const fetchEntries = useCallback(async () => {
    const t = await getToken();
    const headers: HeadersInit = {};
    if (t) headers.Authorization = `Bearer ${t}`;

    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/journal", { headers });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(
          `Failed to load entries: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`,
        );
      }
      const data: JournalListResponse = await res.json();
      setEntries(data.entries ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  /** Fetch the tag summary from the analytics endpoint. */
  const fetchSummary = useCallback(async () => {
    const t = await getToken();
    const headers: HeadersInit = {};
    if (t) headers.Authorization = `Bearer ${t}`;

    setSummaryLoading(true);
    try {
      const res = await fetch(
        `/api/v1/analytics/${encodeURIComponent(exchange)}/journal-summary`,
        { headers },
      );
      if (!res.ok) return; // Non-fatal — summary cards just stay empty.
      const data: JournalSummaryResponse = await res.json();
      setSummary(data);
    } catch {
      // Non-fatal.
    } finally {
      setSummaryLoading(false);
    }
  }, [exchange, getToken]);

  /** Refresh both entries and summary (called after any mutation). */
  const refreshAll = useCallback(async () => {
    await Promise.all([fetchEntries(), fetchSummary()]);
  }, [fetchEntries, fetchSummary]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  // ── Handlers ────────────────────────────────────────────────────────────

  function handleAdd() {
    setEditingEntry(null);
    setDialogOpen(true);
  }

  function handleEdit(entry: TradeJournalEntry) {
    setEditingEntry(entry);
    setDialogOpen(true);
  }

  async function handleDelete(entry: TradeJournalEntry) {
    if (
      !window.confirm(
        `Delete journal entry for ${entry.symbol}? This cannot be undone.`,
      )
    ) {
      return;
    }
    const t = await getToken();
    const headers: HeadersInit = {};
    if (t) headers.Authorization = `Bearer ${t}`;
    try {
      const res = await fetch(`/api/v1/journal/${entry.id}`, {
        method: "DELETE",
        headers,
      });
      if (!res.ok && res.status !== 204) {
        let detail = "";
        try {
          detail = (await res.json())?.detail ?? "";
        } catch {
          /* no body */
        }
        throw new Error(
          `Delete failed: ${res.status} ${res.statusText}${detail ? ` — ${detail}` : ""}`,
        );
      }
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const tagEntries = summary
    ? Object.entries(summary.tags).sort((a, b) => b[1].total_pnl - a[1].total_pnl)
    : [];

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-emerald-400" />
          <h2 className="text-xl font-bold tracking-tight text-slate-100">
            Trading Journal
          </h2>
          <Badge
            variant="outline"
            className="border-slate-700 bg-slate-900/60 text-slate-400"
          >
            {entries.length} {entries.length === 1 ? "entry" : "entries"}
          </Badge>
        </div>
        <Button
          onClick={handleAdd}
          className="bg-emerald-600 text-white hover:bg-emerald-500"
        >
          <Plus className="h-4 w-4" />
          Add Entry
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-800/50 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {/* Tag summary cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {summaryLoading ? (
          <SummaryCardSkeleton />
        ) : tagEntries.length === 0 ? (
          <div className="col-span-full rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-center text-sm text-slate-500">
            <Tag className="mx-auto mb-1 h-4 w-4" />
            Tag analytics will appear here once you have tagged entries.
          </div>
        ) : (
          tagEntries.map(([tag, stat]) => {
            const pnlPositive = stat.total_pnl >= 0;
            return (
              <div
                key={tag}
                className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"
              >
                <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400">
                  <Tag className="h-3 w-3" />
                  {tag}
                </div>
                <div
                  className={cn(
                    "mt-1 text-xl font-bold tabular-nums",
                    pnlPositive ? "text-emerald-400" : "text-red-400",
                  )}
                >
                  {pnlPositive ? "+" : ""}
                  {stat.total_pnl.toFixed(2)}
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                  <span>{stat.trade_count} trades</span>
                  <span className="text-slate-700">•</span>
                  <span
                    className={cn(
                      stat.win_rate >= 50
                        ? "text-emerald-400/80"
                        : "text-red-400/80",
                    )}
                  >
                    {stat.win_rate.toFixed(0)}% win
                  </span>
                </div>
                {/* Win-rate progress bar */}
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      stat.win_rate >= 50 ? "bg-emerald-500" : "bg-red-500",
                    )}
                    style={{ width: `${Math.min(100, stat.win_rate)}%` }}
                  />
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Journal list */}
      {loading ? (
        <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading journal entries…
        </div>
      ) : (
        <JournalList
          entries={entries}
          onEdit={handleEdit}
          onDelete={handleDelete}
        />
      )}

      {/* Create / Edit dialog */}
      <JournalEntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        entry={editingEntry}
        token={tokenProp ?? null}
        exchange={exchange}
        onSaved={refreshAll}
      />
    </div>
  );
}

/** Skeleton placeholder shown while the tag-summary cards are loading. */
function SummaryCardSkeleton() {
  return (
    <div className="col-span-full grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="animate-pulse rounded-xl border border-slate-800 bg-slate-900/60 p-4"
        >
          <div className="h-3 w-16 rounded bg-slate-800" />
          <div className="mt-2 h-6 w-24 rounded bg-slate-800" />
          <div className="mt-2 h-2 w-full rounded bg-slate-800" />
        </div>
      ))}
    </div>
  );
}

export default JournalDashboard;
