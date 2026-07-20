import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export interface DecisionDeskSignal {
  pair: string;
  direction: string;
  state: string;
  missingGates: string[];
  analysis?: {
    entry: number;
    invalidation: number;
    targetOne: number;
    riskReward: number;
  } | null;
  updatedAt: string | null;
}

/** Durable outbox evidence for one lifecycle transition and channel. */
export interface DecisionDeskNotification {
  pair: string;
  direction: string;
  state: string;
  channelType: string;
  status: "configured" | "pending" | "sent" | "failed" | "cancelled" | "unavailable" | string;
  sentAt: string | null;
  lastError: string | null;
}

export interface DecisionDeskAccountPosition {
  symbol: string;
  side: string;
  size: number;
}

/** Authenticated exchange snapshot only; public prices never populate this object. */
export interface DecisionDeskAccountTruth {
  status: "fresh" | "stale" | "unavailable";
  asOf: string | null;
  positions: DecisionDeskAccountPosition[];
  reason: string | null;
}

export interface DecisionDeskProps {
  marketRegime?: string | null;
  confirmedSetups?: string[];
  watchSummary?: string | null;
  lastUpdated?: string | null;
  realtimePairCount?: number;
  researchOnlyPairs?: string[];
  signals?: DecisionDeskSignal[];
  notifications?: DecisionDeskNotification[];
  accountTruth?: DecisionDeskAccountTruth | null;
}

function SignalList({ signals, emptyMessage }: { signals: DecisionDeskSignal[]; emptyMessage: string }) {
  if (signals.length === 0) return <p>{emptyMessage}</p>;

  return (
    <ul className="space-y-3">
      {signals.map((signal) => (
        <li key={`${signal.pair}-${signal.direction}-${signal.state}`} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="bg-slate-700 text-slate-200 hover:bg-slate-700">{signal.state}</Badge>
            <span className="font-medium text-slate-200">{`${signal.pair} — ${signal.direction}`}</span>
          </div>
          {signal.analysis ? (
            <p className="text-xs text-emerald-300">
              Entry {signal.analysis.entry} · Invalidation {signal.analysis.invalidation} · Target 1 {signal.analysis.targetOne} · R:R {signal.analysis.riskReward.toFixed(2)}
            </p>
          ) : null}
          {signal.missingGates.length > 0 ? (
            <p className="text-xs text-slate-500">Missing: {signal.missingGates.join(", ")}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function evidenceLabel(notification: DecisionDeskNotification) {
  if (notification.status === "sent" && notification.sentAt && !notification.lastError) return "Sent";
  if (notification.status === "failed" || notification.lastError) return "Failed";
  return notification.status.charAt(0).toUpperCase() + notification.status.slice(1);
}

function NotificationEvidence({ notifications }: { notifications: DecisionDeskNotification[] }) {
  if (notifications.length === 0) {
    return <p>No notification lifecycle evidence is available for this snapshot.</p>;
  }

  return (
    <ul className="space-y-3">
      {notifications.map((notification, index) => (
        <li
          key={`${notification.pair}-${notification.direction}-${notification.channelType}-${notification.state}-${index}`}
          className="space-y-1"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="bg-slate-700 text-slate-200 hover:bg-slate-700">{evidenceLabel(notification)}</Badge>
            <span className="font-medium text-slate-200">
              {`${notification.pair} — ${notification.direction} — ${notification.channelType}`}
            </span>
          </div>
          <p className="text-xs text-slate-500">Lifecycle: {notification.state}</p>
          {notification.sentAt ? <p className="text-xs text-slate-500">Sent at: {notification.sentAt}</p> : null}
          {notification.lastError ? <p className="text-xs text-amber-400">Error: {notification.lastError}</p> : null}
        </li>
      ))}
    </ul>
  );
}

function AccountTruth({ accountTruth }: { accountTruth: DecisionDeskAccountTruth | null | undefined }) {
  const status = accountTruth?.status ?? "unavailable";
  const positions = accountTruth?.positions ?? [];

  return (
    <Card className="border-slate-800 bg-slate-900/60 lg:col-span-3">
      <CardHeader className="pb-2">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Account truth</h2>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-slate-400">
        <p className={status === "fresh" ? "text-emerald-400" : "text-amber-400"}>
          Account truth {status}.
        </p>
        {accountTruth?.asOf ? <p>Account snapshot: {accountTruth.asOf}</p> : null}
        {accountTruth?.reason ? <p>{accountTruth.reason}</p> : null}
        {status === "unavailable" && !accountTruth?.reason ? (
          <p>Authenticated account data is unavailable; no account state is inferred from market data.</p>
        ) : null}
        {positions.length > 0 ? (
          <ul className="space-y-2">
            {positions.map((position) => (
              <li key={`${position.symbol}-${position.side}`} className="flex flex-wrap items-center gap-2">
                <span className="text-slate-200">{`${position.symbol} — ${position.side} (${position.size})`}</span>
                <Link
                  href={`/journal?exchange=mexc&symbol=${encodeURIComponent(position.symbol)}`}
                  aria-label={`Journal ${position.symbol} position`}
                  className="text-xs font-medium text-emerald-400 hover:text-emerald-300"
                >
                  Journal this position
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="text-xs text-slate-500">Journal links prefill a manual entry only; they never submit orders or change exchange state.</p>
      </CardContent>
    </Card>
  );
}

export function DecisionDesk({
  marketRegime,
  confirmedSetups = [],
  watchSummary,
  lastUpdated,
  realtimePairCount,
  researchOnlyPairs = [],
  signals = [],
  notifications = [],
  accountTruth,
}: DecisionDeskProps) {
  const actionable = signals.filter((signal) => signal.state.toUpperCase() === "ACTIONABLE");
  const watchOrReady = signals.filter((signal) => ["WATCH", "READY"].includes(signal.state.toUpperCase()));
  const invalidatedOrStale = signals.filter((signal) => ["INVALIDATED", "STALE"].includes(signal.state.toUpperCase()));

  // Front-page verdict (INK & OXIDE): honest by construction. "No trade
  // today." is only printed when a real snapshot backs it; with no data at
  // all the desk says so instead of inferring calm.
  const dataAvailable = Boolean(
    lastUpdated || marketRegime || signals.length > 0 || confirmedSetups.length > 0
  );
  const verdictText = !dataAvailable
    ? "Desk unavailable."
    : actionable.length > 0
      ? `Ready: ${actionable.length} ${actionable.length === 1 ? "setup" : "setups"}.`
      : "No trade today.";
  const verdictReason = !dataAvailable
    ? "No persisted advisory snapshot is available. Nothing is inferred from market data."
    : actionable.length > 0
      ? "Confirmed records have cleared every gate. Review the evidence below before any manual execution."
      : "No lifecycle record has cleared every gate. The desk stands down; candidates and evidence follow below.";
  const deskDate = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <section className="space-y-8" aria-label="Decision Desk">
      {/* ── Masthead + monumental verdict — the front page ── */}
      <header>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pb-2.5 text-[13px] text-slate-500">
          <span className="font-mono text-slate-300">{deskDate}</span>
          {lastUpdated ? (
            <>
              <span aria-hidden>·</span>
              <span>
                as of <span className="font-mono">{lastUpdated}</span>
              </span>
            </>
          ) : null}
        </div>
        <hr className="rule-brass border-0" />
        <p className="font-verdict pb-3 pt-7 text-6xl text-slate-100 sm:text-7xl lg:text-8xl">
          {verdictText}
        </p>
        <p className="max-w-[64ch] text-base text-slate-500">{verdictReason}</p>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Market Regime</h2></CardHeader><CardContent className="text-sm text-slate-400">{marketRegime ?? "Market regime unavailable."}</CardContent></Card>
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Confirmed Setups</h2></CardHeader><CardContent className="space-y-2 text-sm text-slate-400">{confirmedSetups.length === 0 ? "No confirmed setups at this time." : <ul className="space-y-2">{confirmedSetups.map((setup) => <li key={setup} className="flex items-start gap-2"><Badge className="mt-0.5 bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/15">Confirmed</Badge><span>{setup}</span></li>)}</ul>}</CardContent></Card>
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Watch / Research-only</h2></CardHeader><CardContent className="text-sm text-slate-400">{watchSummary ?? "No watch or research-only items supplied."}</CardContent></Card>
      {realtimePairCount !== undefined ? <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Market Scope</h2></CardHeader><CardContent className="text-sm text-slate-400">{`${realtimePairCount} MEXC realtime ${realtimePairCount === 1 ? "pair" : "pairs"}`}</CardContent></Card> : null}
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Actionable</h2></CardHeader><CardContent className="text-sm text-slate-400"><SignalList signals={actionable} emptyMessage="No actionable lifecycle records at this time." /></CardContent></Card>
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Watch / Ready</h2></CardHeader><CardContent className="text-sm text-slate-400"><SignalList signals={watchOrReady} emptyMessage="No watch or ready lifecycle records at this time." /></CardContent></Card>
      <Card className="border-slate-800 bg-slate-900/60"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Invalidated / Stale</h2></CardHeader><CardContent className="text-sm text-slate-400"><SignalList signals={invalidatedOrStale} emptyMessage="No invalidated or stale lifecycle records at this time." /></CardContent></Card>
      <Card className="border-slate-800 bg-slate-900/60 lg:col-span-3"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Notification evidence</h2></CardHeader><CardContent className="text-sm text-slate-400"><NotificationEvidence notifications={notifications} /></CardContent></Card>
      <AccountTruth accountTruth={accountTruth} />
      {researchOnlyPairs.length > 0 ? <Card className="border-slate-800 bg-slate-900/60 lg:col-span-3"><CardHeader className="pb-2"><h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Research-only pairs</h2></CardHeader><CardContent className="flex flex-wrap gap-2 text-sm text-slate-400">{researchOnlyPairs.map((pair) => <Badge key={pair} className="bg-amber-500/15 text-amber-400 hover:bg-amber-500/15">{pair}</Badge>)}</CardContent></Card> : null}
      </div>
      <p className="text-xs text-slate-500">Manual review and execution only. This desk is advisory and never places trades.{lastUpdated ? <span>{` Last updated: ${lastUpdated}`}</span> : null}</p>
    </section>
  );
}
