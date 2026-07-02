import { Settings, Bell, Palette, Eye } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type {
  AlertChannelListResponse,
  PairSettingsResponse,
} from "@/lib/types";
import { WatchlistTable } from "@/components/watchlist-table";
import { AlertPreferencesForm } from "@/components/settings/alert-preferences-form";
import { ThemeSettings } from "@/components/settings/theme-settings";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Settings page — async Server Component.
 *
 * Three sections:
 *  1. **Watchlist** — reuses the `WatchlistTable` component (the same one the
 *     Scanner page uses) for full CRUD + scan.
 *  2. **Alert Preferences** — lists alert channels and per-pair settings
 *     fetched from `GET /api/v1/settings/channels` and
 *     `GET /api/v1/settings/pairs`.
 *  3. **Theme** — UI appearance / dark mode toggle.
 *
 * Degrades gracefully: an unauthenticated user (no token) or a transient
 * backend failure renders the sections with empty data + a notice instead of
 * throwing, so the page always loads.
 */

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const token = await getAccessToken();

  // Fetch alert channels and per-pair settings in parallel.
  const [channelsResult, pairSettingsResult] = await Promise.allSettled([
    token
      ? serverFetch<AlertChannelListResponse>("/api/v1/settings/channels", token)
      : Promise.resolve(null),
    token
      ? serverFetch<PairSettingsResponse[]>("/api/v1/settings/pairs", token)
      : Promise.resolve(null),
  ]);

  const channels =
    channelsResult.status === "fulfilled" ? channelsResult.value : null;
  const pairSettings =
    pairSettingsResult.status === "fulfilled"
      ? pairSettingsResult.value
      : null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      {/* Header */}
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Settings className="h-5 w-5 text-emerald-400" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">
            Settings
          </h1>
        </div>
        <p className="text-sm text-slate-400">
          Manage your watchlist, alert preferences, and UI settings.
        </p>
      </header>

      {/* Watchlist */}
      <section aria-label="Watchlist management" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-100">Watchlist</h2>
        </div>
        <WatchlistTable token={token} />
      </section>

      {/* Alert Preferences */}
      <section aria-label="Alert preferences" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-100">
            Alert Preferences
          </h2>
        </div>
        <AlertPreferencesForm
          token={token}
          channels={channels?.channels ?? []}
          pairSettings={pairSettings ?? []}
          fetchError={
            channelsResult.status === "rejected" ||
            pairSettingsResult.status === "rejected"
          }
        />
      </section>

      {/* Theme */}
      <section aria-label="Theme settings" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Palette className="h-4 w-4 text-slate-400" />
          <h2 className="text-lg font-semibold text-slate-100">Theme</h2>
        </div>
        <Card className="border-slate-800 bg-slate-900/60">
          <CardHeader>
            <CardTitle className="text-slate-100">Appearance</CardTitle>
            <CardDescription className="text-slate-400">
              Choose how the dashboard looks.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ThemeSettings />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
