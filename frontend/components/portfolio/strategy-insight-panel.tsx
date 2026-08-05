"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw, X } from "lucide-react";

import type {
  JournalListResponse,
  JournalSummaryResponse,
  StrategyInsightCard,
  TradeJournalEntry,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Phase 4 strategy loop: journal tag scorecards + evidence-based insight cards.
 * Click a tag or insight to load supporting journal entries (evidence trail).
 * Concentration / symbol evidence also deep-links into closed-position analytics.
 */

interface StrategyInsightPanelProps {
  token: string | null;
  exchange: string;
}

type EvidenceQuery = {
  tag?: string;
  symbol?: string;
  label: string;
};

/**
 * Build a portfolio deep-link that opens Analytics → Closed Positions,
 * optionally filtered by a symbols CSV (single symbol is fine).
 */
export function buildClosedPositionsHref(
  exchange: string,
  symbols?: string | null,
): string {
  const params = new URLSearchParams();
  params.set("exchange", exchange);
  params.set("tab", "analytics");
  params.set("analytics_tab", "closed-positions");
  const sym = (symbols ?? "").trim().toUpperCase();
  if (sym) params.set("symbols", sym);
  return `/portfolio?${params.toString()}`;
}

/** Normalize backend evidence_href with exchange when missing. */
function withExchange(href: string, exchange: string): string {
  if (href.includes("exchange=")) return href;
  return `${href}${href.includes("?") ? "&" : "?"}exchange=${exchange}`;
}

/**
 * Primary CTA href for an insight card.
 * Concentration / symbol-evidence insights prefer closed-positions analytics;
 * tag/journal insights keep journal links.
 */
export function insightPrimaryHref(
  insight: StrategyInsightCard,
  exchange: string,
): { href: string; label: string } {
  // Backend concentration insight already points at closed-positions.
  if (
    insight.evidence_href &&
    insight.evidence_href.startsWith("/portfolio") &&
    insight.evidence_href.includes("closed-positions")
  ) {
    return {
      href: withExchange(insight.evidence_href, exchange),
      label: "View closed positions",
    };
  }

  if (insight.evidence_symbol) {
    return {
      href: buildClosedPositionsHref(exchange, insight.evidence_symbol),
      label: "View closed positions",
    };
  }

  if (insight.evidence_href) {
    return {
      href: withExchange(insight.evidence_href, exchange),
      label: "Open journal",
    };
  }

  if (insight.evidence_tag) {
    const params = new URLSearchParams();
    params.set("exchange", exchange);
    params.set("tag", insight.evidence_tag);
    return { href: `/journal?${params.toString()}`, label: "Open journal" };
  }

  const params = new URLSearchParams();
  params.set("exchange", exchange);
  return { href: `/journal?${params.toString()}`, label: "Open journal" };
}

export function StrategyInsightPanel({ token, exchange }: StrategyInsightPanelProps) {
  const [data, setData] = useState<JournalSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [evidenceQuery, setEvidenceQuery] = useState<EvidenceQuery | null>(null);
  const [evidence, setEvidence] = useState<TradeJournalEntry[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

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

  useEffect(() => {
    if (!evidenceQuery || !token) {
      setEvidence([]);
      setEvidenceError(null);
      return;
    }
    let cancelled = false;
    setEvidenceLoading(true);
    setEvidenceError(null);
    const params = new URLSearchParams();
    if (evidenceQuery.tag) params.set("tag", evidenceQuery.tag);
    if (evidenceQuery.symbol) params.set("symbol", evidenceQuery.symbol);
    if (exchange) params.set("exchange", exchange);
    fetch(`/api/v1/journal?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json() as Promise<JournalListResponse>;
      })
      .then((json) => {
        if (!cancelled) setEvidence(json.entries ?? []);
      })
      .catch((err) => {
        if (!cancelled) {
          setEvidence([]);
          setEvidenceError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setEvidenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [evidenceQuery, token, exchange]);

  const tagRows = useMemo(() => {
    if (!data?.tags) return [];
    return Object.entries(data.tags)
      .map(([tag, stats]) => ({ tag, ...stats }))
      .sort((a, b) => b.total_pnl - a.total_pnl);
  }, [data]);

  function openTagEvidence(tag: string) {
    setEvidenceQuery({ tag, label: `Tag: ${tag}` });
  }

  function openInsightEvidence(insight: StrategyInsightCard) {
    if (insight.evidence_tag) {
      setEvidenceQuery({ tag: insight.evidence_tag, label: insight.title });
      return;
    }
    if (insight.evidence_symbol) {
      setEvidenceQuery({
        symbol: insight.evidence_symbol,
        label: insight.title,
      });
      return;
    }
    setEvidenceQuery({ label: insight.title });
  }

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
  const journalHref = (q: EvidenceQuery | null) => {
    const params = new URLSearchParams();
    params.set("exchange", exchange);
    if (q?.tag) params.set("tag", q.tag);
    if (q?.symbol) params.set("symbol", q.symbol);
    return `/journal?${params.toString()}`;
  };

  // Prefer evidence query symbol; else first row symbol when rows share one symbol.
  const evidenceSymbolForClosed = (() => {
    if (evidenceQuery?.symbol) return evidenceQuery.symbol;
    if (evidence.length === 0) return null;
    const symbols = new Set(
      evidence.map((e) => (e.symbol || "").toUpperCase()).filter(Boolean),
    );
    if (symbols.size === 1) return Array.from(symbols)[0];
    return null;
  })();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3 border border-[#2A2620] bg-[#161411] p-4">
        <div>
          <h3 className="text-sm font-medium text-[#EDE7DB]">Strategy &amp; journal loop</h3>
          <p className="mt-1 text-xs text-[#8E8778]">
            Click an insight or tag to open supporting journal rows. Descriptive only — not trade
            advice.
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
        {insights.map((insight) => {
          const primary = insightPrimaryHref(insight, exchange);
          const journalFallback = journalHref(
            insight.evidence_tag
              ? { tag: insight.evidence_tag, label: insight.title }
              : insight.evidence_symbol
                ? { symbol: insight.evidence_symbol, label: insight.title }
                : null,
          );
          return (
            <InsightCard
              key={insight.id}
              insight={insight}
              onOpenEvidence={() => openInsightEvidence(insight)}
              primaryHref={primary.href}
              primaryLabel={primary.label}
              journalHref={journalFallback}
              closedPositionsHref={
                insight.evidence_symbol
                  ? buildClosedPositionsHref(exchange, insight.evidence_symbol)
                  : null
              }
            />
          );
        })}
      </div>

      <div className="border border-[#2A2620] bg-[#161411] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-medium text-[#EDE7DB]">Tag scorecards</h4>
          <Link href={`/journal?exchange=${encodeURIComponent(exchange)}`} className="text-xs text-[#C2A36B] hover:underline">
            Open journal
          </Link>
        </div>
        {tagRows.length === 0 ? (
          <p className="text-sm text-[#8E8778]">
            No tags yet. New journal entries auto-link the newest matching closed position when
            possible.
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
                  <th className="py-2 font-medium">Evidence</th>
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
                    <td className="py-2">
                      <button
                        type="button"
                        onClick={() => openTagEvidence(row.tag)}
                        className="text-[#C2A36B] hover:underline"
                      >
                        View {row.trade_count}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {evidenceQuery && (
        <div className="border border-[#2A2620] bg-[#161411] p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h4 className="text-sm font-medium text-[#EDE7DB]">Evidence</h4>
              <p className="mt-0.5 text-xs text-[#8E8778]">{evidenceQuery.label}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                href={journalHref(evidenceQuery)}
                className="text-xs text-[#C2A36B] hover:underline"
              >
                Open in journal
              </Link>
              {evidenceSymbolForClosed && (
                <Link
                  href={buildClosedPositionsHref(exchange, evidenceSymbolForClosed)}
                  className="text-xs text-[#C2A36B] hover:underline"
                >
                  View closed positions
                </Link>
              )}
              <button
                type="button"
                onClick={() => setEvidenceQuery(null)}
                className="text-[#8E8778] hover:text-[#EDE7DB]"
                aria-label="Close evidence"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          {evidenceLoading ? (
            <div className="flex items-center gap-2 text-xs text-[#8E8778]">
              <Loader2 className="h-3 w-3 animate-spin" /> Loading evidence…
            </div>
          ) : evidenceError ? (
            <p className="text-xs text-[#C96A55]">{evidenceError}</p>
          ) : evidence.length === 0 ? (
            <p className="text-xs text-[#8E8778]">No journal rows match this evidence filter.</p>
          ) : (
            <ul className="max-h-56 space-y-2 overflow-y-auto text-xs">
              {evidence.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[#2A2620]/40 py-2"
                >
                  <span className="font-mono text-[#EDE7DB]">{entry.symbol}</span>
                  <span className="text-[#8E8778]">
                    {entry.tags || "untagged"}
                    {entry.position_id != null ? ` · pos #${entry.position_id}` : " · unlinked"}
                  </span>
                  <span
                    className={cn(
                      "font-mono tabular-nums",
                      (entry.pnl ?? 0) > 0
                        ? "text-[#6CA98F]"
                        : (entry.pnl ?? 0) < 0
                          ? "text-[#C96A55]"
                          : "text-[#8E8778]",
                    )}
                  >
                    {typeof entry.pnl === "number"
                      ? `${entry.pnl >= 0 ? "+" : ""}$${entry.pnl.toFixed(2)}`
                      : "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function InsightCard({
  insight,
  onOpenEvidence,
  primaryHref,
  primaryLabel,
  journalHref,
  closedPositionsHref,
}: {
  insight: StrategyInsightCard;
  onOpenEvidence: () => void;
  primaryHref: string;
  primaryLabel: string;
  journalHref: string;
  closedPositionsHref: string | null;
}) {
  const tone =
    insight.severity === "positive"
      ? "border-[#6CA98F]/40 text-[#6CA98F]"
      : insight.severity === "negative"
        ? "border-[#C96A55]/40 text-[#C96A55]"
        : insight.severity === "warning"
          ? "border-[#D19A4A]/40 text-[#D19A4A]"
          : "border-[#2A2620] text-[#8E8778]";

  const hasEvidence =
    Boolean(insight.evidence_tag) ||
    Boolean(insight.evidence_symbol) ||
    Boolean(insight.evidence_href);

  // Avoid duplicating the same destination as the primary CTA.
  const showJournalSecondary =
    primaryLabel !== "Open journal" || primaryHref !== journalHref;
  const showClosedSecondary =
    closedPositionsHref != null && primaryLabel !== "View closed positions";

  return (
    <div className={cn("border bg-[#161411] p-4", tone)}>
      <h4 className="text-sm font-medium text-[#EDE7DB]">{insight.title}</h4>
      <p className="mt-1 text-xs leading-relaxed text-[#8E8778]">{insight.body}</p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px]">
        {hasEvidence && (
          <button
            type="button"
            onClick={onOpenEvidence}
            className="text-[#C2A36B] hover:underline"
          >
            Show evidence
            {typeof insight.evidence_count === "number" ? ` (n=${insight.evidence_count})` : ""}
          </button>
        )}
        <Link href={primaryHref} className="text-[#C2A36B] hover:underline">
          {primaryLabel}
        </Link>
        {showJournalSecondary && primaryLabel === "View closed positions" && (
          <Link href={journalHref} className="text-[#8E8778] hover:text-[#C2A36B] hover:underline">
            Open journal
          </Link>
        )}
        {showClosedSecondary && closedPositionsHref && (
          <Link
            href={closedPositionsHref}
            className="text-[#8E8778] hover:text-[#C2A36B] hover:underline"
          >
            View closed positions
          </Link>
        )}
      </div>
    </div>
  );
}

export default StrategyInsightPanel;
