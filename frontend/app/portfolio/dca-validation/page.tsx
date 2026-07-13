import { ClipboardCheck, ShieldAlert } from "lucide-react";
import type { InputHTMLAttributes } from "react";

import { DcaValidationEntry } from "@/components/portfolio/dca-validation-entry";
import { DcaShadowHistoryTable } from "@/components/portfolio/dca-shadow-history-table";
import { DcaValidationEvents } from "@/components/portfolio/dca-validation-events";
import { DcaValidationSummary } from "@/components/portfolio/dca-validation-summary";
import { DcaValidationSymbolTable } from "@/components/portfolio/dca-validation-symbol-table";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { fetchDcaValidation } from "@/lib/dca-validation-api";
import type { DcaShadowOutcome, DcaValidationFilters } from "@/lib/dca-validation-types";
import type { DcaValidationResponse } from "@/components/portfolio/dca-validation-summary";

export const dynamic = "force-dynamic";

const KNOWN_EXCHANGES = ["mexc", "binance", "bybit"];

interface PageProps {
  searchParams: Promise<{
    exchange?: string;
    symbol?: string;
    start_date?: string;
    end_date?: string;
    split_ratio?: string;
    shadow_outcome?: DcaShadowOutcome | "all";
  }>;
}

type ValidationPageResult =
  | { status: "auth-required"; validation: null; error?: undefined }
  | { status: "source-missing"; validation: null; error: string }
  | { status: "error"; validation: null; error: string }
  | { status: "loaded"; validation: DcaValidationResponse; error?: undefined };

export default async function DcaValidationPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const exchange = normalizeExchange(params.exchange);
  const token = await getAccessToken();
  const result = await loadValidation(exchange, token, params);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <ClipboardCheck className="h-5 w-5 text-cyan-300" aria-hidden="true" />
          <h1 className="text-2xl font-bold tracking-tight text-slate-100">DCA shadow-mode validation</h1>
          <Badge variant="outline" className="border-cyan-700 bg-cyan-500/10 text-cyan-300">{titleCase(exchange)}</Badge>
        </div>
        <p className="max-w-3xl text-sm text-slate-400">
          Validate Dynamic DCA recommendations using reconstructed scan history, simulated metric panels, and read-only shadow safety gates.
        </p>
      </header>

      <DcaValidationEntry exchange={exchange} />
      <ValidationFilters exchange={exchange} params={params} />
      <ValidationStatus result={result} />
    </div>
  );
}

async function loadValidation(exchange: string, token: string | null, params: Awaited<PageProps["searchParams"]>): Promise<ValidationPageResult> {
  if (!token) return { status: "auth-required", validation: null };

  try {
    const validation = (await fetchDcaValidation(exchange, token, buildValidationFilters(params))) as DcaValidationResponse;
    return { status: "loaded", validation };
  } catch (error) {
    if (isSourceMissing(error)) {
      return { status: "source-missing", validation: null, error: sourceMessage(error) };
    }
    return { status: "error", validation: null, error: error instanceof Error ? error.message : "Validation could not load." };
  }
}

function buildValidationFilters(params: Awaited<PageProps["searchParams"]>): DcaValidationFilters {
  const filters: DcaValidationFilters = { shadowLimit: 50 };
  const symbol = params.symbol?.trim().toUpperCase();
  if (symbol) filters.symbol = symbol;
  if (params.start_date) filters.startDate = params.start_date;
  if (params.end_date) filters.endDate = params.end_date;
  const splitRatio = parseNumberParam(params.split_ratio);
  if (splitRatio !== null) filters.splitRatio = splitRatio;
  if (params.shadow_outcome && params.shadow_outcome !== "all") filters.shadowOutcome = params.shadow_outcome;
  return filters;
}

function ValidationFilters({ exchange, params }: { exchange: string; params: Awaited<PageProps["searchParams"]> }) {
  return (
    <form action="/portfolio/dca-validation" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4" aria-label="DCA validation filters">
      <input type="hidden" name="exchange" value={exchange} />
      <div className="grid gap-3 md:grid-cols-5">
        <FilterField label="Symbol" name="symbol" defaultValue={params.symbol ?? ""} placeholder="BTCUSDT:USDT" />
        <FilterField label="Start date" name="start_date" type="date" defaultValue={params.start_date ?? ""} />
        <FilterField label="End date" name="end_date" type="date" defaultValue={params.end_date ?? ""} />
        <FilterField label="Split ratio" name="split_ratio" type="number" defaultValue={params.split_ratio ?? "0.7"} min="0.1" max="0.9" step="0.05" />
        <label className="text-xs font-medium text-slate-400">
          Shadow history
          <select
            name="shadow_outcome"
            defaultValue={params.shadow_outcome ?? "all"}
            className="mt-1 h-9 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
          >
            <option value="all">All outcomes</option>
            <option value="would_allow">Would allow</option>
            <option value="would_block">Would block</option>
            <option value="would_reduce">Would reduce</option>
            <option value="would_close">Would close</option>
            <option value="no_action">No action</option>
          </select>
        </label>
      </div>
      <button type="submit" className="mt-3 rounded-md border border-cyan-700 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
        Apply validation filters
      </button>
    </form>
  );
}

function FilterField({ label, name, ...props }: { label: string; name: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="text-xs font-medium text-slate-400">
      {label}
      <input
        name={name}
        className="mt-1 h-9 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400"
        {...props}
      />
    </label>
  );
}

function ValidationStatus({ result }: { result: ValidationPageResult }) {
  if (result.status === "auth-required") {
    return <FirstClassState title="Sign in required" tone="info" message="Connect and authenticate your portfolio before opening DCA validation." />;
  }
  if (result.status === "source-missing") {
    return <FirstClassState title="Source data missing" tone="warning" message={result.error} />;
  }
  if (result.status === "error") {
    return <FirstClassState title="Validation could not load" tone="danger" message={result.error} />;
  }

  return <ValidationPanels validation={result.validation} />;
}

function ValidationPanels({ validation }: { validation: DcaValidationResponse }) {
  const symbols = validation.reconstruction?.symbols ?? [];
  const metricSymbols = validation.metrics?.symbols ?? [];
  const symbolsWithInspectableEvents = symbols.filter((symbol) => symbol.events.length > 0 || symbol.skipped_scans.length > 0 || symbol.unavailable_source);

  return (
    <main className="space-y-5">
      <DcaValidationSummary validation={validation} />
      {validation.state === "insufficient_history" && (
        <FirstClassState title="Insufficient scan history" tone="info" message="Metrics are hidden until at least 2 usable scans with price, RSI, trade plan, and position context are available." compact />
      )}
      <DcaValidationSymbolTable symbols={symbols} metrics={metricSymbols} />
      {symbolsWithInspectableEvents.length === 0 ? (
        <DcaValidationEvents symbol={symbols[0]?.symbol ?? "selected symbols"} events={[]} skippedScans={[]} />
      ) : (
        symbolsWithInspectableEvents.map((symbol) => (
          <DcaValidationEvents
            key={symbol.symbol}
            symbol={symbol.symbol}
            events={symbol.events}
            skippedScans={symbol.skipped_scans}
            errorSource={symbol.unavailable_source}
          />
        ))
      )}
      <DcaShadowHistoryTable history={validation.shadow_history} />
    </main>
  );
}

function FirstClassState({ title, message, tone }: { title: string; message: string; tone: "info" | "warning" | "danger"; compact?: boolean }) {
  const classes = tone === "danger"
    ? "border-red-800/60 bg-red-500/10 text-red-100"
    : tone === "warning"
      ? "border-amber-800/60 bg-amber-500/10 text-amber-100"
      : "border-sky-800/60 bg-sky-500/10 text-sky-100";
  return (
    <section className={`rounded-xl border p-4 ${classes}`} aria-labelledby="first-class-state-title">
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <h2 id="first-class-state-title" className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm opacity-85">{message}</p>
        </div>
      </div>
    </section>
  );
}

function normalizeExchange(exchange: string | undefined) {
  const raw = (exchange ?? "mexc").toLowerCase();
  return KNOWN_EXCHANGES.includes(raw) ? raw : "mexc";
}

function titleCase(slug: string) {
  return slug.charAt(0).toUpperCase() + slug.slice(1);
}

function parseNumberParam(value: string | undefined) {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isSourceMissing(error: unknown) {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: unknown; error?: unknown } | undefined;
    const detail = String(body?.detail ?? body?.error ?? error.message).toLowerCase();
    return error.status === 404 || detail.includes("missing") || detail.includes("not found") || detail.includes("source");
  }
  return error instanceof Error && /missing|not found|source/i.test(error.message);
}

function sourceMessage(error: unknown) {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: unknown; error?: unknown } | undefined;
    return String(body?.detail ?? body?.error ?? "Stored scan history or portfolio source data is missing.");
  }
  return error instanceof Error ? error.message : "Stored scan history or portfolio source data is missing.";
}
