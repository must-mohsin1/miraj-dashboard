"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";

import type { JournalSummaryResponse, StrategyInsightCard } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Phase 4 strategy loop: journal tag scorecards + evidence-based insight cards.
 * Descriptive only — no execution advice.
 */

interface StrategyInsightPanelProps {
  token: string | null;
  exchange: string;
}

export function StrategyInsightPanel({ token, exchange }: StrategyInsightPanelProps) {
  const [data, setData] = useState<JournalSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function fetchData() {
    if (!token) {
      setLoading(false);
      setError("Sign in to load strategy insights.");
      return;
    }
    setRefreshing(true);
    try {
      const res = await fetch(
        `/api/v1/analytics/${encodeURIComponent(exchange)}/journal-summary`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const json: JournalSummaryResponse = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    void fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange, token]);

  const tagRows = useMemo(() => {
    if (!data?.tags) return [];
    return Object.entries(data.tags)
      .map(([tag, stats]) => ({ tag, ...stats }))
      .sort((a, b) => b.total_pnl - a.total_pnl);
  }, [data]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 border border-[#2A2620] bg-[#161411] p-8 text-sm text-[#8E8778]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading strategy insights…
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[#2A2620] bg-[#161411] p-6 text-sm text-[#C96A55]">
        Strategy insights unavailable — {error}
      </div>
    );
  }

  const insights = data?.insights ?? [];
  const linked = data?.linked_to_position ?? 0;
  const total = data?.total_entries ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3 border border-[#2A2620] bg-[#161411] p-4">
        <div>
          <h3 className="text-sm font-medium text-[#EDE7DB]">Strategy &amp; journal loop</h3>
          <p className="mt-1 text-xs text-[#8E8778]">
            Tag scorecards and evidence-based insights from journal entries on{" "}
            <span className="font-mono text-[#EDE7DB]">{exchange}</span>. Descriptive only —
            not trade advice.
          </p>
          <p className="mt-2 font-mono text-xs tabular-nums text-[#8E8778]">
            {total} entries · {linked} linked to closed positions
          </p>
        </div>
        <button
          type="button"
          onClick={() => void fetchData()}
          disabled={refreshing}
          className="inline-flex items-center gap-1 border border-[#2A2620] px-2 py-1 text-xs text-[#8E8778] hover:text-[#EDE7DB]"
        >
          <RefreshCw className={cn("h-3 w-3", refreshing && "animate-spin")} />
          Refresh
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {insights.map((insight) => (
          <InsightCard key={insight.id} insight={insight} />
        ))}
      </div>

      <div className="border border-[#2A2620] bg-[#161411] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-medium text-[#EDE7DB]">Tag scorecards</h4>
          <Link href="/journal" className="text-xs text-[#C2A36B] hover:underline">
            Open journal
          </Link>
        </div>
        {tagRows.length === 0 ? (
          <p className="text-sm text-[#8E8778]">
            No tags yet. Link closed positions and add strategy tags in the journal.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[#8E8778]">
                <tr className="border-b border-[#2A2620]">
                  <th className="py-2 pr-3 font-medium">Tag</th>
                  <th className="py-2 pr-3 font-medium">Trades</th>
                  <th className="py-2 pr-3 font-medium">Win rate</th>
                  <th className="py-2 pr-3 font-medium">Total PnL</th>
                  <th className="py-2 font-medium">Avg PnL</th>
                </tr>
              </thead>
              <tbody>
                {tagRows.map((row) => (
                  <tr key={row.tag} className="border-b border-[#2A2620]/30">
                    <td className="py-2 pr-3 font-mono text-[#EDE7DB]">{row.tag}</td>
                    <td className="py-2 pr-3 font-mono tabular-nums text-[#EDE7DB]">
                      {row.trade_count}
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums text-[#EDE7DB]">
                      {row.win_rate.toFixed(1)}%
                    </td>
                    <td
                      className={cn(
                        "py-2 pr-3 font-mono tabular-nums",
                        row.total_pnl > 0
                          ? "text-[#6CA98F]"
                          : row.total_pnl < 0
                            ? "text-[#C96A55]"
                            : "text-[#EDE7DB]",
                      )}
                    >
                      {row.total_pnl >= 0 ? "+" : ""}
                      ${row.total_pnl.toFixed(2)}
                    </td>
                    <td className="py-2 font-mono tabular-nums text-[#8E8778]">
                      {typeof row.avg_pnl === "number"
                        ? `${row.avg_pnl >= 0 ? "+" : ""}$${row.avg_pnl.toFixed(2)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function InsightCard({ insight }: { insight: StrategyInsightCard }) {
  const tone =
    insight.severity === "positive"
      ? "border-[#6CA98F]/40 text-[#6CA98F]"
      : insight.severity === "negative"
        ? "border-[#C96A55]/40 text-[#C96A55]"
        : insight.severity === "warning"
          ? "border-[#D19A4A]/40 text-[#D19A4A]"
          : "border-[#2A2620] text-[#8E8778]";

  return (
    <div className={cn("border bg-[#161411] p-4", tone)}>
      <h4 className="text-sm font-medium text-[#EDE7DB]">{insight.title}</h4>
      <p className="mt-1 text-xs leading-relaxed text-[#8E8778]">{insight.body}</p>
      {insight.evidence_tag && (
        <p className="mt-2 font-mono text-[11px] text-[#C2A36B]">
          Evidence: tag “{insight.evidence_tag}”
          {typeof insight.evidence_count === "number" ? ` · n=${insight.evidence_count}` : ""}
        </p>
      )}
    </div>
  );
}

export default StrategyInsightPanel;
