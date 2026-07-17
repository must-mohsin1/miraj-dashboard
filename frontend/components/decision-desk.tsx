import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export interface DecisionDeskProps {
  marketRegime?: string | null;
  confirmedSetups?: string[];
  watchSummary?: string | null;
  lastUpdated?: string | null;
}

export function DecisionDesk({
  marketRegime,
  confirmedSetups = [],
  watchSummary,
  lastUpdated,
}: DecisionDeskProps) {
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

      <p className="lg:col-span-3 text-xs text-slate-500">
        Manual review and execution only. This desk is advisory and never places trades.
        {lastUpdated ? <span>{` Last updated: ${lastUpdated}`}</span> : null}
      </p>
    </section>
  );
}
