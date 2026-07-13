"use client";

import { useMemo, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  formatDateTime,
  humanize,
  type DcaShadowHistoryItem,
  type DcaShadowOutcome,
} from "./dca-validation-summary";

interface DcaShadowHistoryTableProps {
  history: DcaShadowHistoryItem[];
}

const OUTCOME_OPTIONS: { value: "all" | DcaShadowOutcome; label: string }[] = [
  { value: "all", label: "All outcomes" },
  { value: "would_allow", label: "Would allow" },
  { value: "would_block", label: "Would block" },
  { value: "would_reduce", label: "Would reduce" },
  { value: "would_close", label: "Would close" },
  { value: "no_action", label: "No action" },
];

export function DcaShadowHistoryTable({ history }: DcaShadowHistoryTableProps) {
  const symbols = useMemo(() => Array.from(new Set(history.map((item) => item.symbol))).sort(), [history]);
  const [symbol, setSymbol] = useState("all");
  const [outcome, setOutcome] = useState<"all" | DcaShadowOutcome>("all");
  const [dateRange, setDateRange] = useState("30d");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const filtered = useMemo(
    () => history.filter((item) => matchesSymbol(item, symbol) && matchesOutcome(item, outcome) && matchesDateRange(item, dateRange)),
    [dateRange, history, outcome, symbol]
  );

  if (history.length === 0) {
    return (
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5" aria-labelledby="shadow-history-title">
        <h2 id="shadow-history-title" className="text-base font-semibold text-slate-100">Shadow history</h2>
        <p className="mt-2 text-sm text-slate-400">No shadow decisions yet. Shadow outcomes will appear here after validation records prospective DCA decisions.</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4" aria-labelledby="shadow-history-title">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 id="shadow-history-title" className="text-base font-semibold text-slate-100">Shadow history</h2>
          <p className="mt-1 text-sm text-slate-400">Filter non-live shadow decisions by symbol, outcome, and date range.</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="text-xs font-medium text-slate-400">
            Symbol
            <select value={symbol} onChange={(event) => setSymbol(event.target.value)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100">
              <option value="all">All symbols</option>
              {symbols.length === 0 && <option disabled>No symbols with shadow history</option>}
              {symbols.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-400">
            Outcome
            <select value={outcome} onChange={(event) => setOutcome(event.target.value as "all" | DcaShadowOutcome)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100">
              {OUTCOME_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-400">
            Date range
            <select value={dateRange} onChange={(event) => setDateRange(event.target.value)} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100">
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="custom">Custom range</option>
            </select>
          </label>
        </div>
      </div>
      {dateRange === "custom" && <p className="mt-2 text-sm text-amber-300">Choose an end date after the start date.</p>}

      {filtered.length === 0 ? (
        <p className="mt-5 rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">No shadow decisions match these filters. Try a different symbol, outcome, or date range.</p>
      ) : (
        <Table aria-label="Shadow history" className="mt-4">
          <TableHeader>
            <TableRow className="border-slate-800 hover:bg-transparent">
              <TableHead className="text-slate-500">Time</TableHead>
              <TableHead className="text-slate-500">Symbol</TableHead>
              <TableHead className="text-slate-500">Original recommendation</TableHead>
              <TableHead className="text-slate-500">Shadow outcome</TableHead>
              <TableHead className="text-slate-500">Blocked gates</TableHead>
              <TableHead className="text-slate-500">Assumptions</TableHead>
              <TableHead className="text-right text-slate-500">Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((item, index) => {
              const key = `${item.symbol}-${item.timestamp ?? "no-time"}-${index}`;
              const expanded = expandedKey === key;
              return (
                <TableRow key={key} className="border-slate-800/60 hover:bg-slate-800/30">
                  <TableCell className="whitespace-nowrap text-slate-400 tabular-nums">{formatDateTime(item.timestamp)}</TableCell>
                  <TableCell className="font-mono font-medium text-slate-100">{item.symbol}</TableCell>
                  <TableCell className="text-slate-300">{item.original_recommendation}</TableCell>
                  <TableCell><OutcomeBadge outcome={item.final_outcome} /></TableCell>
                  <TableCell className="text-slate-300">{item.blocked_gates.length > 0 ? `${item.blocked_gates.length} blocked: ${item.blocked_gates.map(humanize).join(", ")}` : "No blocked gates"}</TableCell>
                  <TableCell className="max-w-xs text-slate-400">{formatAssumptionSet(item.assumption_set)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="border-slate-700 bg-slate-950/50 text-slate-200 hover:bg-slate-800"
                      onClick={() => setExpandedKey(expanded ? null : key)}
                      aria-expanded={expanded}
                      aria-label={`Show blocked safety gates for ${item.symbol} at ${item.timestamp ?? "unknown time"}`}
                    >
                      Why blocked?
                    </Button>
                    {expanded && <BlockedDetails item={item} />}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function BlockedDetails({ item }: { item: DcaShadowHistoryItem }) {
  const failed = item.gate_breakdown.filter((gate) => !gate.passed);
  const passed = item.gate_breakdown.filter((gate) => gate.passed);
  return (
    <div className="mt-3 w-[min(32rem,80vw)] rounded-lg border border-slate-700 bg-slate-950 p-4 text-left shadow-xl">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-100"><ShieldAlert className="h-4 w-4 text-amber-300" aria-hidden="true" /> Why shadow ADD was blocked</h3>
      <dl className="mt-3 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
        <Detail label="Original recommendation" value={item.original_recommendation} />
        <Detail label="Shadow outcome" value={item.final_outcome} />
        <Detail label="Decision time" value={formatDateTime(item.timestamp)} />
        <Detail label="Assumption set" value={formatAssumptionSet(item.assumption_set)} />
      </dl>
      <p className="mt-3 rounded-md border border-amber-800/60 bg-amber-500/10 p-2 text-sm text-amber-100"><span className="font-medium">Final reason: </span>{item.final_reason}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <GateList title="Blocked gates" gates={failed} empty="No blocked gates recorded for this decision" />
        <GateList title="Passed gates" gates={passed} empty="No passed gates recorded" />
      </div>
      <p className="mt-3 text-xs text-slate-500">Safety gates block new shadow ADD outcomes only. REDUCE and CLOSE recommendations remain visible so urgent risk signals are not hidden.</p>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-200">{value}</dd>
    </div>
  );
}

function GateList({ title, gates, empty }: { title: string; gates: { name: string; reason: string }[]; empty: string }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      {gates.length === 0 ? (
        <p className="mt-1 text-sm text-slate-400">{empty}</p>
      ) : (
        <ul className="mt-1 space-y-1 text-sm text-slate-300">
          {gates.map((gate) => <li key={`${gate.name}-${gate.reason}`}>• {gate.reason || humanize(gate.name)}</li>)}
        </ul>
      )}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: DcaShadowOutcome }) {
  const blocked = outcome === "would_block";
  return (
    <Badge variant="outline" className={blocked ? "border-amber-700 bg-amber-500/10 text-amber-300" : "border-emerald-700 bg-emerald-500/10 text-emerald-300"}>
      {outcome}
    </Badge>
  );
}

function formatAssumptionSet(assumptions: DcaShadowHistoryItem["assumption_set"]) {
  const parts = [
    assumptions.fee_percent !== undefined ? `fee ${assumptions.fee_percent}%` : null,
    assumptions.slippage_percent !== undefined ? `slippage ${assumptions.slippage_percent}%` : null,
    assumptions.split_ratio !== undefined ? `split ${Math.round(Number(assumptions.split_ratio) * 100)}/${Math.round((1 - Number(assumptions.split_ratio)) * 100)}` : null,
    assumptions.min_confluence_score !== undefined ? `min confluence ${assumptions.min_confluence_score}` : null,
    assumptions.exposure_cap_pct !== undefined ? `exposure cap ${assumptions.exposure_cap_pct}%` : null,
    assumptions.mode ? String(assumptions.mode) : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "Default shadow assumptions";
}

function matchesSymbol(item: DcaShadowHistoryItem, symbol: string) {
  return symbol === "all" || item.symbol === symbol;
}

function matchesOutcome(item: DcaShadowHistoryItem, outcome: "all" | DcaShadowOutcome) {
  return outcome === "all" || item.final_outcome === outcome;
}

function matchesDateRange(item: DcaShadowHistoryItem, dateRange: string) {
  if (dateRange === "custom") return true;
  if (!item.timestamp) return false;
  const timestamp = new Date(item.timestamp).getTime();
  if (Number.isNaN(timestamp)) return false;
  const windowMs = dateRange === "24h" ? 24 * 60 * 60 * 1000 : dateRange === "7d" ? 7 * 24 * 60 * 60 * 1000 : 30 * 24 * 60 * 60 * 1000;
  return Date.now() - timestamp <= windowMs;
}

export default DcaShadowHistoryTable;
