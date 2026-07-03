import { Skeleton } from "@/components/ui/skeleton";

/**
 * Reusable loading skeletons used inside <Suspense> boundaries across the
 * dashboard. Each skeleton mirrors the rough shape/size of the real
 * component it stands in for, so the layout doesn't shift on load.
 *
 * All skeletons use the shared `Skeleton` primitive from shadcn/ui
 * (an `animate-pulse rounded-md bg-primary/10` div).
 */

/* ── CardSkeleton ──────────────────────────────────────────────────────────
 * For macro cards and portfolio stat cards: a grid of card-shaped blocks
 * with a title line, a big value line, and a subtitle line.
 */
export function CardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-slate-800 bg-slate-900/60 p-6"
        >
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-4 h-8 w-20" />
          <Skeleton className="mt-3 h-3 w-32" />
        </div>
      ))}
    </div>
  );
}

/* ── TableSkeleton ─────────────────────────────────────────────────────────
 * For the scanner/watchlist table: a header row + N body rows of bars.
 */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-4 flex items-center justify-between gap-4">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-9 w-40" />
      </div>
      <div className="space-y-3">
        {/* header */}
        <div className="flex items-center gap-4 border-b border-slate-800 pb-2">
          {[3, 2, 2, 2, 1].map((w, c) => (
            <Skeleton key={c} className={`h-4 w-${w}/12`} />
          ))}
        </div>
        {/* body */}
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            {[3, 2, 2, 2, 1].map((w, c) => (
              <Skeleton key={c} className={`h-5 w-${w}/12`} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── ChartSkeleton ────────────────────────────────────────────────────────
 * For the analysis/chart area: a card-like block with axes and a faux
 * candle area, plus a legend row.
 */
export function ChartSkeleton() {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <div className="mb-3 flex items-center justify-between">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-5 w-20" />
      </div>
      {/* faux chart canvas */}
      <Skeleton className="h-[300px] w-full sm:h-[500px]" />
      {/* legend */}
      <div className="mt-3 flex flex-wrap items-center gap-4">
        {[1, 2, 3].map((c) => (
          <Skeleton key={c} className="h-3 w-16" />
        ))}
      </div>
    </div>
  );
}

/* ── TabsSkeleton ─────────────────────────────────────────────────────────
 * For the portfolio tabs (Balances · Positions · Trades): a tab bar plus
 * a table-like body.
 */
export function TabsSkeleton() {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {/* tab bar */}
      <div className="mb-4 flex items-center gap-2 border-b border-slate-800 pb-3">
        {[1, 2, 3].map((c) => (
          <Skeleton key={c} className="h-8 w-24" />
        ))}
        <div className="ml-auto flex items-center gap-2">
          <Skeleton className="h-9 w-28" />
          <Skeleton className="h-9 w-28" />
        </div>
      </div>
      {/* stat row */}
      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-slate-800 p-3">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-6 w-20" />
          </div>
        ))}
      </div>
      {/* faux table */}
      <div className="space-y-3">
        <div className="flex items-center gap-4 border-b border-slate-800 pb-2">
          {[3, 2, 2, 1].map((w, c) => (
            <Skeleton key={c} className={`h-4 w-${w}/12`} />
          ))}
        </div>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            {[3, 2, 2, 1].map((w, c) => (
              <Skeleton key={c} className={`h-5 w-${w}/12`} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
