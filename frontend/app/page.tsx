import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { MacroResponse } from "@/lib/types";
import { MacroCards } from "@/components/macro-cards";
import { QuickActions } from "@/components/quick-actions";
import { HomeView } from "@/components/home-view";

/**
 * Home page — async Server Component.
 *
 * Fetches the latest macro snapshot from `GET /api/v1/macro` using the
 * signed-in user's access token, then delegates rendering to the
 * synchronous {@link HomeView} presentational component.
 *
 * Splitting the async data fetch from the synchronous view keeps the page
 * testable in jsdom (which cannot render async Server Components directly).
 * The page degrades gracefully: if the user is unauthenticated (no token)
 * or the backend is unreachable, the cards render with placeholder
 * em-dashes instead of throwing, so the home page always loads.
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

  return <HomeView macro={macro} />;
}
