import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Eye,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ScanVerdictData } from "@/lib/types";

/**
 * VerdictCard — Server Component.
 *
 * The page's headline: renders the typed scan verdict with the decision
 * state (NO TRADE / WATCH / READY LONG / READY SHORT), the directional
 * bias as a separate fact, the human reasoning, current blockers, and the
 * five hard eligibility gates with pass/fail detail. Entry levels belong
 * to the trade-plan card and only exist when the verdict is READY.
 */

const STATE_META: Record<
  ScanVerdictData["state"],
  { chip: string; Icon: typeof Ban }
> = {
  NO_TRADE: {
    chip: "bg-slate-500/10 text-slate-300 border-slate-600/60",
    Icon: Ban,
  },
  WATCH: {
    chip: "bg-amber-500/10 text-amber-400 border-amber-700/50",
    Icon: Eye,
  },
  READY_LONG: {
    chip: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
    Icon: TrendingUp,
  },
  READY_SHORT: {
    chip: "bg-red-500/10 text-red-400 border-red-700/50",
    Icon: TrendingDown,
  },
};

const BIAS_META: Record<ScanVerdictData["bias"], string> = {
  LONG: "bg-emerald-500/10 text-emerald-400 border-emerald-700/50",
  SHORT: "bg-red-500/10 text-red-400 border-red-700/50",
  NEUTRAL: "bg-slate-500/10 text-slate-400 border-slate-700/50",
};

interface VerdictCardProps {
  verdict: ScanVerdictData | null | undefined;
}

/** "NO TRADE TODAY" → "No trade today." — the verdict is an authored ruling. */
function sentenceCase(label: string): string {
  const t = label.trim();
  if (!t) return t;
  const sentence = t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
  return sentence.endsWith(".") ? sentence : `${sentence}.`;
}

export function VerdictCard({ verdict }: VerdictCardProps) {
  if (!verdict) return null;

  const meta = STATE_META[verdict.state] ?? STATE_META.NO_TRADE;
  const { Icon } = meta;
  const biasClass = BIAS_META[verdict.bias] ?? BIAS_META.NEUTRAL;

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium text-slate-400">
            Verdict
          </CardTitle>
          {verdict.next_review && (
            <span className="inline-flex items-center gap-1 text-xs text-slate-500">
              <Clock className="h-3 w-3" />
              Re-check: {verdict.next_review}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* The verdict voice: serif, sentence case, full stop (DESIGN.md) */}
        <p className="font-verdict text-4xl text-slate-100 sm:text-5xl">
          {sentenceCase(verdict.display)}
        </p>

        {/* State + bias — separate facts, separate chips */}
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-semibold ${meta.chip}`}
          >
            <Icon className="h-4 w-4" />
            {verdict.display}
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${biasClass}`}
          >
            Bias: {verdict.bias}
          </span>
        </div>

        {/* Why */}
        <p className="text-sm leading-relaxed text-slate-300">
          {verdict.reasoning}
        </p>

        {/* Blockers */}
        {verdict.blockers.length > 0 && (
          <div className="rounded-md border border-amber-800/40 bg-amber-500/5 p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-amber-400">
              Blockers
            </p>
            <ul className="space-y-1.5">
              {verdict.blockers.map((blocker, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-xs text-slate-400"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                  <span>{blocker}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Hard gates checklist */}
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            Eligibility gates
          </p>
          <ul className="space-y-2">
            {verdict.gates.map((gate) => (
              <li key={gate.id} className="flex items-start gap-2">
                {gate.passed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                )}
                <div className="min-w-0">
                  <span className="text-sm text-slate-300">{gate.label}</span>
                  <p className="text-xs text-slate-500">{gate.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

export default VerdictCard;
