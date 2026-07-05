import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { getAccessToken } from "@/lib/auth";
import { serverFetch, ApiError } from "@/lib/api";
import type { ScanChangesTimelineResponse } from "@/lib/types";
import { ScoreProgressionChart } from "@/components/score-progression-chart";
import { SignalChangesPanel } from "@/components/signal-changes-panel";

export default async function ChangesPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  const decoded = decodeURIComponent(symbol);
  const token = await getAccessToken();

  let timeline: ScanChangesTimelineResponse | null = null;

  try {
    timeline = await serverFetch<ScanChangesTimelineResponse>(
      `/api/v1/scan/${decoded}/changes?limit=50`,
      token ?? undefined,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
  }

  const groups = timeline?.timeline ?? [];

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/analysis/${decoded}`}
          className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to {decoded}
        </Link>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-slate-100">
          Signal Changes — {decoded}
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Full progression history: {timeline?.total_scans ?? 0} scan{groups.length === 1 ? "" : "s"}
        </p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">
          Confluence Score Over Time
        </h3>
        <ScoreProgressionChart symbol={decoded} token={token} />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">
          Latest Changes
        </h3>
        <SignalChangesPanel symbol={decoded} token={token} variant="full" />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">
          Full Timeline
        </h3>
        {groups.length === 0 ? (
          <p className="text-sm text-slate-500">
            No scan history yet. Run a scan to start tracking signal changes.
          </p>
        ) : (
          <div className="space-y-4">
            {groups.map((group) => (
              <div
                key={group.scan_at}
                className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">
                    {new Date(group.scan_at).toLocaleString("en-US", {
                      year: "numeric", month: "short", day: "numeric",
                      hour: "2-digit", minute: "2-digit",
                    })}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    (group.score_after ?? 0) >= 20
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-700/50"
                      : (group.score_after ?? 0) >= 10
                        ? "bg-amber-500/10 text-amber-400 border border-amber-700/50"
                        : "bg-slate-500/10 text-slate-400 border border-slate-700/50"
                  }`}>
                    Score: {group.score_after ?? "—"}/30
                  </span>
                </div>
                {group.changes && group.changes.length > 0 && (
                  <ul className="space-y-1">
                    {group.changes.map((change, i) => (
                      <li key={i} className={`flex items-start gap-2 rounded px-2 py-1 text-xs ${
                        change.severity === "major"
                          ? "bg-red-500/5 text-red-300"
                          : change.severity === "minor"
                            ? "bg-amber-500/5 text-amber-300"
                            : "bg-blue-500/5 text-blue-300"
                      }`}>
                        <span className="font-medium uppercase tracking-wide opacity-60">
                          {change.severity}
                        </span>
                        <span className="flex-1">
                          <span className="font-medium">{change.field}</span>
                          {change.old_value && change.new_value
                            ? ": " + change.old_value + " → " + change.new_value
                            : change.new_value
                              ? ": " + change.new_value
                              : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {(!group.changes || group.changes.length === 0) && (
                  <p className="text-xs text-slate-600">No changes from previous scan</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
