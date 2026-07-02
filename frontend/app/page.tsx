import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { MacroResponse } from "@/lib/types";
import { MacroCards } from "@/components/macro-cards";
import { QuickActions } from "@/components/quick-actions";

/**
 * Home page — async Server Component.
 *
 * Fetches the latest macro snapshot from `GET /api/v1/macro` using the
 * signed-in user's access token and renders the four headline cards plus
 * quick-action links to the Macro Dashboard and Scanner.
 *
 * The page degrades gracefully: if the user is unauthenticated (no token)
 * or the backend is unreachable, the cards render with placeholder em-dashes
 * instead of throwing, so the home page always loads.
 */
export default async function Home() {
  const token = await getAccessToken();

  let macro: MacroResponse | null = null;
  if (token) {
    try {
      macro = await serverFetch<MacroResponse>("/api/v1/macro", token);
    } catch {
      // Swallow transient backend errors — render placeholder cards.
      macro = null;
    }
  }

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
