import Link from "next/link";
import { Activity, Search, Settings } from "lucide-react";

import { DecisionDesk } from "@/components/decision-desk";
import { getAccessToken } from "@/lib/auth";
import { serverFetch } from "@/lib/api";
import type { DecisionDeskResponse } from "@/lib/decision-desk-types";

export const dynamic = "force-dynamic";

/**
 * A server-rendered view of the user's persisted advisory state. The endpoint
 * is read-only; missing data is shown as unavailable rather than inferred.
 */
export default async function NowPage() {
  const token = await getAccessToken();
  let desk: DecisionDeskResponse | null = null;

  if (token) {
    try {
      desk = await serverFetch<DecisionDeskResponse>("/api/v1/decision-desk/now", token);
    } catch {
      // A backend outage or an unavailable snapshot must never become a signal.
      desk = null;
    }
  }

  const pairs = desk?.watchlist ?? [];
  const signals = desk?.signals ?? [];
  const realtimePairCount = pairs.filter((pair) => pair.market_scope === "mexc_realtime").length;
  const researchOnlyPairs = pairs
    .filter((pair) => pair.market_scope === "research_only")
    .map((pair) => pair.pair);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-emerald-400" />
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Decision Desk</h1>
          </div>
          <p className="text-sm text-slate-400">
            Current market scope and persisted realtime lifecycle records for manual review.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/scanner"
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition-colors hover:border-emerald-600 hover:text-emerald-400"
          >
            <Search className="h-4 w-4" />
            Scanner
          </Link>
          <Link
            href="/settings"
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-2 text-sm font-medium text-slate-300 transition-colors hover:border-emerald-600 hover:text-emerald-400"
          >
            <Settings className="h-4 w-4" />
            Settings
          </Link>
        </div>
      </header>

      {desk ? (
        <DecisionDesk
          realtimePairCount={realtimePairCount}
          researchOnlyPairs={researchOnlyPairs}
          signals={signals.map((signal) => ({
            pair: signal.pair,
            direction: signal.direction,
            state: signal.state,
            missingGates: signal.missing_gates ?? [],
            analysis: signal.analysis ? {
              entry: signal.analysis.entry,
              invalidation: signal.analysis.invalidation,
              targetOne: signal.analysis.target_one,
              riskReward: signal.analysis.risk_reward,
            } : null,
            updatedAt: signal.updated_at ?? null,
          }))}
          notifications={desk.notification_outbox.map((notification) => ({
            pair: notification.pair,
            direction: notification.direction,
            state: notification.signal_state,
            channelType: notification.channel_type,
            status: notification.status,
            sentAt: notification.sent_at,
            lastError: notification.error,
          }))}
          accountTruth={(() => {
            const account = desk.account_reconciliation.find((item) => item.exchange.toLowerCase() === "mexc")
              ?? desk.account_reconciliation[0];
            return account ? {
              status: account.freshness,
              asOf: account.last_reconciled_at,
              positions: account.positions,
              reason: account.freshness === "unavailable" ? "No successful authenticated account reconciliation is cached." : null,
            } : null;
          })()}
          lastUpdated={desk.generated_at ?? null}
        />
      ) : (
        <section aria-label="Decision Desk unavailable" className="space-y-4">
          <p className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 text-sm text-slate-400">
            Decision Desk data is currently unavailable.
          </p>
          <DecisionDesk />
        </section>
      )}
    </div>
  );
}
