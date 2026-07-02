import type { MacroResponse } from "@/lib/types";
import { MacroCards } from "@/components/macro-cards";
import { QuickActions } from "@/components/quick-actions";

/**
 * HomeView — synchronous presentational component for the home page.
 *
 * Renders the welcome heading, the four macro indicator cards, and the
 * quick-action links. Extracted from the async `Home` Server Component so
 * the layout is unit-testable in jsdom (which cannot render async Server
 * Components directly).
 */
export function HomeView({ macro }: { macro: MacroResponse | null }) {
  const updatedAt = macro?.cached_at
    ? new Date(macro.cached_at).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      {/* Welcome heading */}
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-slate-100">
          Crypto Analysis Dashboard
        </h1>
        <p className="text-sm text-slate-400">
          Snapshot of the key macro forces driving crypto markets right now.
        </p>
        {updatedAt && (
          <p className="mt-1 text-xs text-slate-500">
            Updated {updatedAt}
            {macro?.stale ? " · showing cached data" : ""}
          </p>
        )}
      </header>

      {/* Macro cards */}
      <section aria-label="Macro indicators">
        <MacroCards data={macro?.data ?? null} />
      </section>

      {/* Quick actions */}
      <section aria-label="Quick actions">
        <h2 className="mb-3 text-lg font-semibold text-slate-200">
          Quick Actions
        </h2>
        <QuickActions />
      </section>
    </div>
  );
}

export default HomeView;
