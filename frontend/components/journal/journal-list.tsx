"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { TradeJournalEntry } from "@/lib/types";

/**
 * JournalList — Client Component.
 *
 * Renders a table of trading-journal entries with:
 *  - Columns: Date, Symbol, Tags (badges), PnL (green/red), Notes (truncated), Actions
 *  - A symbol filter input at the top (case-insensitive substring match)
 *  - A tag filter input at the top (matches any tag on an entry)
 *  - Clicking a row expands it to show the full notes + lessons + trade details
 *
 * The edit/delete action buttons call back to the parent which owns the
 * mutation + dialog state.
 */

interface JournalListProps {
  /** Journal entries to render (already fetched by the parent). */
  entries: TradeJournalEntry[];
  /** Called when the user clicks the edit (pencil) button on a row. */
  onEdit: (entry: TradeJournalEntry) => void;
  /** Called when the user clicks the delete (trash) button on a row. */
  onDelete: (entry: TradeJournalEntry) => void;
}

/** Parse an entry's comma-separated tags string into an array. */
function parseTags(raw: string | null): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/** Format an ISO timestamp as a compact date+time string. */
function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** Truncate a string to `len` chars, appending an ellipsis when truncated. */
function truncate(s: string, len: number): string {
  if (s.length <= len) return s;
  return s.slice(0, len).trimEnd() + "…";
}

/** Pick a deterministic tailwind colour for a tag badge. */
const TAG_COLOURS = [
  "border-emerald-700/50 bg-emerald-500/10 text-emerald-400",
  "border-sky-700/50 bg-sky-500/10 text-sky-400",
  "border-violet-700/50 bg-violet-500/10 text-violet-400",
  "border-amber-700/50 bg-amber-500/10 text-amber-400",
  "border-rose-700/50 bg-rose-500/10 text-rose-400",
  "border-cyan-700/50 bg-cyan-500/10 text-cyan-400",
  "border-indigo-700/50 bg-indigo-500/10 text-indigo-400",
];

function tagColour(tag: string): string {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = (hash * 31 + tag.charCodeAt(i)) | 0;
  }
  return TAG_COLOURS[Math.abs(hash) % TAG_COLOURS.length];
}

export function JournalList({ entries, onEdit, onDelete }: JournalListProps) {
  const [symbolFilter, setSymbolFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Apply both filters (case-insensitive).
  const filtered = useMemo(() => {
    const sym = symbolFilter.trim().toUpperCase();
    const tag = tagFilter.trim().toLowerCase();
    return entries.filter((e) => {
      if (sym && !e.symbol.toUpperCase().includes(sym)) return false;
      if (tag) {
        const tags = parseTags(e.tags);
        const matches = tags.some((t) => t.toLowerCase().includes(tag));
        if (!matches) return false;
      }
      return true;
    });
  }, [entries, symbolFilter, tagFilter]);

  // Unique sorted list of tags from all entries — used for the tag filter.
  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const e of entries) {
      for (const t of parseTags(e.tags)) set.add(t);
    }
    return Array.from(set).sort();
  }, [entries]);

  function toggleRow(id: number) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-8 text-center text-sm text-slate-400">
        No journal entries yet. Click <span className="text-emerald-400">Add Entry</span> to create your first one.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="text"
          placeholder="Filter by symbol…"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="h-9 w-40 border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
        />
        <Input
          type="text"
          placeholder="Filter by tag…"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          className="h-9 w-40 border-slate-700 bg-slate-950/50 text-slate-100 placeholder:text-slate-600"
        />
        {/* Quick tag chips — click to filter */}
        {allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            {allTags.slice(0, 8).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTagFilter(t)}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
                  tagFilter.toLowerCase() === t.toLowerCase()
                    ? "border-emerald-600 bg-emerald-500/20 text-emerald-300"
                    : "border-slate-700 bg-slate-900/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200",
                )}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {(symbolFilter || tagFilter) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSymbolFilter("");
              setTagFilter("");
            }}
            className="h-9 text-xs text-slate-400 hover:text-slate-200"
          >
            Clear
          </Button>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
        <Table>
          <TableHeader>
            <TableRow className="border-slate-800 hover:bg-transparent">
              <TableHead className="w-8 text-slate-500" />
              <TableHead className="text-slate-500">Date</TableHead>
              <TableHead className="text-slate-500">Symbol</TableHead>
              <TableHead className="text-slate-500">Tags</TableHead>
              <TableHead className="text-right text-slate-500">PnL</TableHead>
              <TableHead className="text-slate-500">Notes</TableHead>
              <TableHead className="w-20 text-right text-slate-500">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow className="border-slate-800/60">
                <TableCell colSpan={7} className="py-8 text-center text-sm text-slate-500">
                  No entries match your filters.
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((e) => {
                const tags = parseTags(e.tags);
                const pnlPositive = (e.pnl ?? 0) >= 0;
                const isExpanded = expandedId === e.id;
                return (
                  <TableRow
                    key={e.id}
                    className="border-slate-800/60 transition-colors last:border-0 hover:bg-slate-800/30 cursor-pointer"
                    onClick={() => toggleRow(e.id)}
                  >
                    {/* Expand chevron */}
                    <TableCell className="w-8 text-slate-500" onClick={(ev) => ev.stopPropagation()}>
                      <ChevronRight
                        className={cn(
                          "h-4 w-4 transition-transform",
                          isExpanded && "rotate-90",
                        )}
                      />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-slate-400 tabular-nums">
                      {formatTime(e.created_at)}
                    </TableCell>
                    <TableCell className="font-medium text-slate-100">
                      {e.symbol}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {tags.length === 0 ? (
                          <span className="text-xs text-slate-600">—</span>
                        ) : (
                          tags.map((t) => (
                            <Badge
                              key={t}
                              variant="outline"
                              className={tagColour(t)}
                            >
                              {t}
                            </Badge>
                          ))
                        )}
                      </div>
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-semibold tabular-nums",
                        e.pnl == null
                          ? "text-slate-500"
                          : pnlPositive
                            ? "text-emerald-400"
                            : "text-red-400",
                      )}
                    >
                      {e.pnl == null
                        ? "—"
                        : `${pnlPositive ? "+" : ""}${e.pnl.toFixed(2)}`}
                    </TableCell>
                    <TableCell className="max-w-xs text-slate-400">
                      {e.notes ? truncate(e.notes, 60) : <span className="text-slate-600">—</span>}
                    </TableCell>
                    <TableCell
                      className="text-right"
                      onClick={(ev) => ev.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                          onClick={() => onEdit(e)}
                          aria-label="Edit entry"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-red-400 hover:bg-red-500/10 hover:text-red-300"
                          onClick={() => onDelete(e)}
                          aria-label="Delete entry"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Expanded-row detail panels (rendered below the table for layout simplicity) */}
      {expandedId !== null && (
        <ExpandedDetail
          entry={filtered.find((e) => e.id === expandedId) ?? null}
        />
      )}

      <p className="text-xs text-slate-500">
        Showing {filtered.length} of {entries.length} entries
      </p>
    </div>
  );
}

/**
 * ExpandedDetail — renders the full notes, lessons, and trade metadata for
 * the currently-expanded row. Rendered as a separate card below the table so
 * the table layout stays simple.
 */
function ExpandedDetail({ entry }: { entry: TradeJournalEntry | null }) {
  if (!entry) return null;
  const pnlHas = entry.pnl != null;
  const pnlPositive = (entry.pnl ?? 0) >= 0;
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/80 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="font-semibold text-slate-100">{entry.symbol}</span>
        <span className="text-xs text-slate-500">
          {new Date(entry.created_at).toLocaleString()}
        </span>
      </div>

      {/* Trade metadata grid */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <DetailStat label="Entry" value={entry.entry_price != null ? entry.entry_price.toString() : "—"} />
        <DetailStat label="Exit" value={entry.exit_price != null ? entry.exit_price.toString() : "—"} />
        <DetailStat
          label="PnL"
          value={pnlHas ? `${pnlPositive ? "+" : ""}${entry.pnl!.toFixed(2)}` : "—"}
          valueClass={pnlHas ? (pnlPositive ? "text-emerald-400" : "text-red-400") : "text-slate-500"}
        />
        <DetailStat label="Exchange" value={entry.exchange ?? "—"} />
        <DetailStat label="Position ID" value={entry.position_id != null ? String(entry.position_id) : "—"} />
      </div>

      {/* Notes */}
      {entry.notes && (
        <div className="mb-3">
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
            Notes
          </h4>
          <p className="whitespace-pre-wrap text-sm text-slate-300">{entry.notes}</p>
        </div>
      )}

      {/* Lessons */}
      {entry.lessons && (
        <div className="mb-3">
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
            Lessons
          </h4>
          <p className="whitespace-pre-wrap text-sm text-slate-300">{entry.lessons}</p>
        </div>
      )}

      {/* Screenshots */}
      {entry.screenshots.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
            Screenshots ({entry.screenshots.length})
          </h4>
          <ul className="flex flex-col gap-1 text-xs text-slate-400">
            {entry.screenshots.map((s, i) => (
              <li key={`${s}-${i}`} className="truncate">
                📎 {s.split("/").pop() ?? s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!entry.notes && !entry.lessons && entry.screenshots.length === 0 && (
        <p className="text-sm text-slate-500">No additional details.</p>
      )}
    </div>
  );
}

function DetailStat({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/30 p-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cn("mt-0.5 text-sm font-medium tabular-nums text-slate-200", valueClass)}>
        {value}
      </div>
    </div>
  );
}

export default JournalList;
