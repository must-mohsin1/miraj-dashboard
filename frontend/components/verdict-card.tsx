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
    chip: "border-[#2A2620] text-[#A69D8C]",
    Icon: Ban,
  },
  WATCH: {
    chip: "border-[#D19A4A]/50 text-[#D19A4A]",
    Icon: Eye,
  },
  READY_LONG: {
    chip: "border-[#6CA98F]/50 text-[#6CA98F]",
    Icon: TrendingUp,
  },
  READY_SHORT: {
    chip: "border-[#C96A55]/50 text-[#C96A55]",
    Icon: TrendingDown,
  },
};

const BIAS_META: Record<ScanVerdictData["bias"], string> = {
  LONG: "border-[#6CA98F]/40 text-[#6CA98F]",
  SHORT: "border-[#C96A55]/40 text-[#C96A55]",
  NEUTRAL: "border-[#2A2620] text-[#8E8778]",
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
    <section className="border border-[#2A2620] bg-[#161411] p-5" aria-labelledby="verdict-heading">
      <div className="flex items-center justify-between">
        <p id="verdict-heading" className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          Verdict
        </p>
        {verdict.next_review && (
          <span className="inline-flex items-center gap-1 text-xs text-[#8E8778]">
            <Clock className="h-3 w-3" />
            Re-check: {verdict.next_review}
          </span>
        )}
      </div>
      <p className="mt-3 font-verdict text-4xl text-[#EDE7DB] sm:text-5xl">
        {sentenceCase(verdict.display)}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1.5 border px-3 py-1 text-sm font-semibold ${meta.chip}`}>
          <Icon className="h-4 w-4" />
          {verdict.display}
        </span>
        <span className={`inline-flex items-center gap-1 border px-2.5 py-0.5 text-xs font-semibold ${biasClass}`}>
          Bias: {verdict.bias}
        </span>
      </div>
      <p className="mt-4 max-w-[64ch] text-sm leading-relaxed text-[#8E8778]">
        {verdict.reasoning}
      </p>
      {verdict.blockers.length > 0 && (
        <div className="mt-4 border border-[#2A2620] p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#D19A4A]">
            Blockers
          </p>
          <ul className="space-y-1.5">
            {verdict.blockers.map((blocker, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-[#8E8778]">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#D19A4A]" />
                <span>{blocker}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          Eligibility gates
        </p>
        <ul className="space-y-2">
          {verdict.gates.map((gate) => (
            <li key={gate.id} className="flex items-start gap-2">
              {gate.passed ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#6CA98F]" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#C96A55]" />
              )}
              <div className="min-w-0">
                <span className="text-sm text-[#EDE7DB]">{gate.label}</span>
                <p className="text-xs text-[#8E8778]">{gate.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export default VerdictCard;
