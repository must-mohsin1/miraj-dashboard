import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export interface DecisionDeskSignal {
  pair: string;
  direction: string;
  state: string;
  missingGates: string[];
  updatedAt: string | null;
}

export interface DecisionDeskProps {
  marketRegime?: string | null;
  confirmedSetups?: string[];
  watchSummary?: string | null;
  lastUpdated?: string | null;
  realtimePairCount?: number;
  researchOnlyPairs?: string[];
  signals?: DecisionDeskSignal[];
}

function SignalList({ signals, emptyMessage }: { signals: DecisionDeskSignal[]; emptyMessage: string }) {
  if (signals.length === 0) {
    return <p>{emptyMessage}</p>;
  }

  return (
    <ul className="space-y-3">
      {signals.map((signal) => (
        <li key={`${signal.pair}-${signal.direction}-${signal.state}`} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="bg-slate-700 text-slate-200 hover:bg-slate-700">{signal.state}</Badge>
            <span className="font-medium text-slate-200">{`${signal.pair} — ${signal.direction}`}</span>
          </div>
          {signal.missingGates.length > 0 ? (
            <p className="text-xs text-slate-500">Missing: {signal.missingGates.join(", ")}</p>
          ) : null}
        </li>
      ))}
    </ul>
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
}: DecisionDeskProps) {
  const actionable = signals.filter((signal) => signal.state.toUpperCase() === "ACTIONABLE");
  const watchOrReady = signals.filter((signal) => ["WATCH", "READY"].includes(signal.state.toUpperCase()));
  const invalidatedOrStale = signals.filter((signal) =>
    ["INVALIDATED", "STALE"].includes(signal.state.toUpperCase())
  );
  return (
    <section className="grid gap-4 lg:grid-cols-3" aria-label="Decision Desk">
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Market Regime</h2>
        </CardHeader>
        <CardContent className="text-sm text-slate-400">
          {marketRegime ?? "Market regime unavailable."}
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Confirmed Setups</h2>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-slate-400">
          {confirmedSetups.length === 0 ? (
            "No confirmed setups at this time."
          ) : (
            <ul className="space-y-2">
              {confirmedSetups.map((setup) => (
                <li key={setup} className="flex items-start gap-2">
                  <Badge className="mt-0.5 bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/15">
                    Confirmed
                  </Badge>
                  <span>{setup}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Watch / Research-only</h2>
        </CardHeader>
        <CardContent className="text-sm text-slate-400">
          {watchSummary ?? "No watch or research-only items supplied."}
        </CardContent>
      </Card>

      {realtimePairCount !== undefined ? (
        <Card className="border-slate-800 bg-slate-900/60">
          <CardHeader className="pb-2">
            <h2 className="text-base font-semibold text-slate-100">Market Scope</h2>
          </CardHeader>
          <CardContent className="text-sm text-slate-400">
            {`${realtimePairCount} MEXC realtime ${realtimePairCount === 1 ? "pair" : "pairs"}`}
          </CardContent>
        </Card>
      ) : null}

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Actionable</h2>
        </CardHeader>
        <CardContent className="text-sm text-slate-400">
          <SignalList signals={actionable} emptyMessage="No actionable lifecycle records at this time." />
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Watch / Ready</h2>
        </CardHeader>
        <CardContent className="text-sm text-slate-400">
          <SignalList signals={watchOrReady} emptyMessage="No watch or ready lifecycle records at this time." />
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader className="pb-2">
          <h2 className="text-base font-semibold text-slate-100">Invalidated / Stale</h2>
        </CardHeader>
        <CardContent className="text-sm text-slate-400">
          <SignalList signals={invalidatedOrStale} emptyMessage="No invalidated or stale lifecycle records at this time." />
        </CardContent>
      </Card>

      {researchOnlyPairs.length > 0 ? (
        <Card className="border-slate-800 bg-slate-900/60 lg:col-span-3">
          <CardHeader className="pb-2">
            <h2 className="text-base font-semibold text-slate-100">Research-only pairs</h2>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2 text-sm text-slate-400">
            {researchOnlyPairs.map((pair) => (
              <Badge key={pair} className="bg-amber-500/15 text-amber-400 hover:bg-amber-500/15">
                {pair}
              </Badge>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <p className="lg:col-span-3 text-xs text-slate-500">
        Manual review and execution only. This desk is advisory and never places trades.
        {lastUpdated ? <span>{` Last updated: ${lastUpdated}`}</span> : null}
      </p>
    </section>
  );
}
