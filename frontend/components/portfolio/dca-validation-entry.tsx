import Link from "next/link";
import { ClipboardCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";

interface DcaValidationEntryProps {
  exchange: string;
  compact?: boolean;
}

export function DcaValidationEntry({ exchange, compact = false }: DcaValidationEntryProps) {
  const href = `/portfolio/dca-validation?exchange=${encodeURIComponent(exchange)}`;

  if (compact) {
    return (
      <Link
        href={href}
        className="inline-flex items-center gap-1 rounded-md border border-cyan-700/60 bg-cyan-500/10 px-2 py-1 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        aria-label={`Open DCA shadow-mode validation for ${exchange}`}
        onClick={(event) => event.stopPropagation()}
      >
        <ClipboardCheck className="h-3.5 w-3.5" aria-hidden="true" />
        Validate
      </Link>
    );
  }

  return (
    <aside className="rounded-xl border border-cyan-800/60 bg-cyan-500/10 p-4 text-sm text-cyan-50" aria-labelledby="dca-validation-entry-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-cyan-700/70 bg-slate-950/50 text-cyan-300">
            <ClipboardCheck className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h2 id="dca-validation-entry-title" className="font-semibold text-cyan-100">
              Shadow-mode DCA validation
            </h2>
            <p className="mt-1 max-w-2xl text-cyan-100/80">
              Inspect reconstructed Dynamic DCA recommendations, simulated metrics, and safety-gate decisions without changing the current live recommendations.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge variant="outline" className="border-cyan-700 bg-cyan-500/10 text-cyan-200">Read-only</Badge>
              <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-200">Shadow mode</Badge>
            </div>
          </div>
        </div>
        <Link
          href={href}
          className="inline-flex min-h-10 items-center justify-center rounded-md border border-cyan-700 bg-slate-950/60 px-3 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-900/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          Open validation
        </Link>
      </div>
    </aside>
  );
}

export default DcaValidationEntry;
