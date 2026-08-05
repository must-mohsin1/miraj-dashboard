"use client";

import { useState } from "react";
import Link from "next/link";

import {
  CLOSED_POSITION_ANALYTICS_ERROR,
  CLOSED_POSITION_FEE_UNAVAILABLE,
  CLOSED_POSITION_HISTORY_PHASE2,
  CLOSED_POSITION_HISTORY_SCOPE,
  CLOSED_POSITION_HISTORY_UNKNOWN,
  CLOSED_POSITION_PNL_BASIS,
  formatCount,
  formatMinutes,
  formatPercent,
  formatUsdtMoney,
  pnlToneClass,
  readableReason,
} from "@/components/portfolio/closed-position-formatters";
import { type ClosedPositionBasis, type ClosedPositionHistory } from "@/components/portfolio/closed-position-basis-note";
import {
  buildTradeExplorerCsvFilename,
  tradeExplorerItemsToCsv,
} from "@/components/portfolio/trade-explorer-csv";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export type TradeExplorerSortField = "close_time" | "pnl" | "symbol" | "side" | "leverage" | "duration_minutes";

export type TradeExplorerItem = {
  id: number | string;
  symbol: string;
  side: string | null;
  size: number | null;
  size_unit?: string | null;
  contract_size?: number | null;
  entry_price?: number | null;
  exit_price?: number | null;
  pnl: number | null;
  pnl_basis?: string | null;
  currency_unit?: string | null;
  fee_status?: string | null;
  pnl_percent?: number | null;
  leverage?: number | null;
  open_time?: string | null;
  close_time?: string | null;
  duration_minutes?: number | null;
  close_reason?: string | null;
  unavailable_reasons?: string[] | Record<string, string | number | boolean | null> | null;
};

export type TradeExplorerResponse = {
  exchange?: string | null;
  filters_applied?: Record<string, unknown> | null;
  sort: string;
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
  basis?: ClosedPositionBasis | null;
  history?: ClosedPositionHistory | null;
  excluded_reasons?: Record<string, number> | null;
  items: TradeExplorerItem[];
};

export interface TradeExplorerProps {
  data: TradeExplorerResponse | null;
  loading?: boolean;
  error?: string | null;
  onPageChange?: (offset: number) => void;
  onPageSizeChange?: (limit: number) => void;
  /** Called when a sortable column header is activated. Receives sort token e.g. `-pnl`. */
  onSortChange?: (sort: string) => void;
}

const MAX_PAGE_SIZE = 200;
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const SORT_LABELS: Record<TradeExplorerSortField, string> = {
  close_time: "Close time",
  pnl: "PnL",
  symbol: "Symbol",
  side: "Side",
  leverage: "Leverage",
  duration_minutes: "Duration",
};

export function clampTradeExplorerPageSize(value: number): number {
  if (!Number.isFinite(value)) return 50;
  return Math.min(MAX_PAGE_SIZE, Math.max(1, Math.trunc(value)));
}

export function TradeExplorer({
  data,
  loading = false,
  error = null,
  onPageChange,
  onPageSizeChange,
  onSortChange,
}: TradeExplorerProps) {
  const [selected, setSelected] = useState<TradeExplorerItem | null>(null);

  if (loading) {
    return (
      <section className="border border-border bg-card p-6 text-sm text-muted-foreground" aria-busy="true">
        Loading Trade Explorer…
      </section>
    );
  }

  if (error) {
    return (
      <section className="border border-destructive bg-destructive/10 p-4 text-sm text-destructive" role="alert">
        {CLOSED_POSITION_ANALYTICS_ERROR}
      </section>
    );
  }

  const safeData = data || emptyTradeExplorer();
  const limit = clampTradeExplorerPageSize(safeData.limit);
  const offset = Math.max(0, safeData.offset || 0);
  const total = Math.max(0, safeData.total || 0);
  const currentStart = total === 0 ? 0 : Math.min(offset + 1, total);
  const currentEnd = Math.min(offset + limit, total);
  const previousOffset = Math.max(0, offset - limit);
  const nextOffset = offset + limit;
  const sort = parseSort(safeData.sort);
  const pnlBasis = safeData.basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS;
  const currency = safeData.basis?.currency_unit || "USDT";
  const sizeUnit = safeData.basis?.size_unit || "contracts";
  const canExport = safeData.items.length > 0;

  function handleExportCsv() {
    if (!canExport) return;
    const csv = tradeExplorerItemsToCsv(safeData.items);
    const filename = buildTradeExplorerCsvFilename(safeData.exchange);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function handleSortField(field: TradeExplorerSortField) {
    if (!onSortChange) return;
    const active = sort.field === field;
    const nextDescending = active ? sort.direction === "ascending" : true;
    onSortChange(nextDescending ? `-${field}` : field);
  }

  return (
    <section className="grid min-w-0 gap-4" aria-labelledby="trade-explorer-heading">
      <div className="flex flex-col gap-3 border border-border bg-card p-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 id="trade-explorer-heading" className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Trade Explorer
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Server-paginated closed positions. Showing <span className="font-mono tabular-nums text-foreground">{formatCount(currentStart)}–{formatCount(currentEnd)}</span> of <span className="font-mono tabular-nums text-foreground">{formatCount(total)}</span>; limit <span className="font-mono tabular-nums text-foreground">{formatCount(limit)}</span>, offset <span className="font-mono tabular-nums text-foreground">{formatCount(offset)}</span>, has_more <span className="font-mono tabular-nums text-foreground">{safeData.has_more ? "true" : "false"}</span>.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">Page size cap: <span className="font-mono tabular-nums text-foreground">200</span> max{limit >= MAX_PAGE_SIZE ? " — cap reached" : ""}. Sort: <span className="font-mono tabular-nums text-foreground">{sort.label} {sort.directionLabel}</span>. {pnlBasis}; values displayed in {currency}.</p>
          <p className="mt-1 text-xs text-muted-foreground">Click a row for trade detail. CSV export covers this page only (not full history).</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <button
            type="button"
            className="border border-border bg-background px-3 py-2 text-sm text-foreground transition-colors hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            onClick={handleExportCsv}
            disabled={!canExport}
            aria-label="Export current Trade Explorer page as CSV"
          >
            Export CSV (this page)
          </button>
          <label className="grid gap-1 text-xs uppercase tracking-[0.12em] text-muted-foreground">
            Page size
            <select
              className="border border-border bg-background px-3 py-2 font-mono text-sm text-foreground tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              value={limit}
              onChange={(event) => onPageSizeChange?.(clampTradeExplorerPageSize(Number(event.target.value)))}
              aria-label="Trade Explorer page size"
            >
              {PAGE_SIZE_OPTIONS.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              className="border border-border bg-background px-3 py-2 text-sm text-foreground transition-colors hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => onPageChange?.(previousOffset)}
              disabled={offset === 0}
              aria-label="Go to previous Trade Explorer page"
            >
              Previous
            </button>
            <button
              type="button"
              className="border border-border bg-background px-3 py-2 text-sm text-foreground transition-colors hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => onPageChange?.(nextOffset)}
              disabled={!safeData.has_more}
              aria-label="Go to next Trade Explorer page"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      <TradeExplorerHistory history={safeData.history} basis={safeData.basis} excludedReasons={safeData.excluded_reasons} />

      {safeData.items.length === 0 ? (
        <div className="border border-border bg-card p-6 text-sm text-muted-foreground">
          No stored closed positions match these filters. {CLOSED_POSITION_HISTORY_SCOPE}; {CLOSED_POSITION_HISTORY_UNKNOWN}; {CLOSED_POSITION_HISTORY_PHASE2}.
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:hidden">
            {safeData.items.map((item) => (
              <TradeExplorerCard
                key={item.id}
                item={item}
                pnlBasis={pnlBasis}
                sizeUnit={item.size_unit || sizeUnit}
                onOpen={() => setSelected(item)}
              />
            ))}
          </div>
          <div
            className="hidden min-w-0 overflow-x-auto border border-border bg-card focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent sm:block"
            role="region"
            aria-label="Scrollable Trade Explorer closed positions table"
            tabIndex={0}
          >
            <table className="w-full min-w-[1180px] border-collapse text-sm">
              <caption className="sr-only">Server-paginated Trade Explorer rows with deterministic sort indicators, PnL basis, fee status, and unavailable reasons. Activate a row to open trade detail.</caption>
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-[0.12em] text-muted-foreground">
                  <SortableHead field="close_time" sort={sort} edge="left" onSort={onSortChange ? handleSortField : undefined} />
                  <SortableHead field="symbol" sort={sort} onSort={onSortChange ? handleSortField : undefined} />
                  <SortableHead field="side" sort={sort} onSort={onSortChange ? handleSortField : undefined} />
                  <th scope="col" className="px-3 py-2 text-right font-medium">Size</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Contract size</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Entry</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Exit</th>
                  <SortableHead field="pnl" sort={sort} align="right" onSort={onSortChange ? handleSortField : undefined} />
                  <th scope="col" className="px-3 py-2 text-left font-medium">Basis / fees</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">PnL %</th>
                  <SortableHead field="leverage" sort={sort} align="right" onSort={onSortChange ? handleSortField : undefined} />
                  <SortableHead field="duration_minutes" sort={sort} align="right" onSort={onSortChange ? handleSortField : undefined} />
                  <th scope="col" className="py-2 pl-3 text-left font-medium">Reason / unavailable</th>
                </tr>
              </thead>
              <tbody>
                {safeData.items.map((item) => (
                  <TradeExplorerRow
                    key={item.id}
                    item={item}
                    pnlBasis={pnlBasis}
                    sizeUnit={item.size_unit || sizeUnit}
                    onOpen={() => setSelected(item)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <TradeDetailDrawer
        item={selected}
        open={selected != null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        pnlBasis={pnlBasis}
        sizeUnit={selected?.size_unit || sizeUnit}
        exchange={safeData.exchange}
      />
    </section>
  );
}

function TradeExplorerHistory({ history, basis, excludedReasons }: { history?: ClosedPositionHistory | null; basis?: ClosedPositionBasis | null; excludedReasons?: Record<string, number> | null }) {
  const excluded = Object.entries(excludedReasons || {}).filter(([, count]) => count > 0);
  return (
    <aside className="grid gap-3 border border-border bg-card p-4 text-sm text-muted-foreground md:grid-cols-3" aria-label="Trade Explorer basis and history">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">Basis</h3>
        <p className="mt-1 leading-relaxed"><span className="text-foreground">{basis?.pnl_basis || CLOSED_POSITION_PNL_BASIS}</span>; source <span className="font-mono tabular-nums text-foreground">{basis?.pnl_source || "PositionHistory.pnl"}</span>; size unit <span className="font-mono tabular-nums text-foreground">{basis?.size_unit || "contracts"}</span>.</p>
        <p className="mt-2 text-amber-400">{CLOSED_POSITION_FEE_UNAVAILABLE}</p>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">Stored history</h3>
        <p className="mt-1">{CLOSED_POSITION_HISTORY_SCOPE}: <span className="font-mono tabular-nums text-foreground">{formatCount(history?.row_count)}</span> rows.</p>
        <p>{CLOSED_POSITION_HISTORY_UNKNOWN}. {CLOSED_POSITION_HISTORY_PHASE2}.</p>
        <p className="text-xs">Reason: {readableReason(history?.reason || "full_history_sync_not_implemented_phase2")}</p>
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">Excluded rows</h3>
        {excluded.length === 0 ? <p className="mt-1">No unavailable duration/leverage rows were excluded by current range filters.</p> : (
          <ul className="mt-1 grid gap-1">
            {excluded.map(([reason, count]) => <li key={reason}><span className="font-mono tabular-nums text-foreground">{formatCount(count)}</span> rows excluded for {readableReason(reason)}</li>)}
          </ul>
        )}
      </div>
    </aside>
  );
}

function SortableHead({
  field,
  sort,
  align = "left",
  edge = "middle",
  onSort,
}: {
  field: TradeExplorerSortField;
  sort: ParsedSort;
  align?: "left" | "right";
  edge?: "left" | "middle";
  onSort?: (field: TradeExplorerSortField) => void;
}) {
  const active = sort.field === field;
  const indicator = active ? (sort.direction === "ascending" ? "↑" : "↓") : "↕";
  const ariaSort = active ? sort.direction : "none";
  const padding = edge === "left" ? "py-2 pr-3" : "px-3 py-2";
  const alignment = align === "right" ? "text-right" : "text-left";
  if (!onSort) {
    return (
      <th scope="col" aria-sort={ariaSort} className={`${padding} ${alignment} font-medium`}>
        {SORT_LABELS[field]} <span aria-hidden="true">{indicator}</span><span className="sr-only">, {active ? sort.directionLabel : "not sorted"}</span>
      </th>
    );
  }
  return (
    <th scope="col" aria-sort={ariaSort} className={`${padding} ${alignment} font-medium`}>
      <button
        type="button"
        className="inline-flex items-center gap-1 text-inherit hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        onClick={() => onSort(field)}
        aria-label={`Sort by ${SORT_LABELS[field]}${active ? `, currently ${sort.directionLabel}` : ""}`}
      >
        {SORT_LABELS[field]} <span aria-hidden="true">{indicator}</span>
        <span className="sr-only">, {active ? sort.directionLabel : "not sorted"}</span>
      </button>
    </th>
  );
}

function TradeExplorerRow({
  item,
  pnlBasis,
  sizeUnit,
  onOpen,
}: {
  item: TradeExplorerItem;
  pnlBasis: string;
  sizeUnit: string;
  onOpen: () => void;
}) {
  const pnlState = pnlStateLabel(item.pnl);
  return (
    <tr
      className="cursor-pointer border-b border-border last:border-b-0 hover:bg-muted/40"
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`Open trade detail for ${item.symbol || "position"} ID ${item.id}`}
    >
      <th scope="row" className="py-3 pr-3 text-left align-top font-mono text-xs tabular-nums text-foreground">
        <div>{formatTime(item.close_time)}</div>
        <div className="mt-1 text-muted-foreground">ID {item.id}</div>
        <div className="mt-1 text-muted-foreground">Open {formatTime(item.open_time)}</div>
      </th>
      <td className="px-3 py-3 align-top font-mono text-foreground tabular-nums">{item.symbol || "—"}</td>
      <td className="px-3 py-3 align-top text-foreground">{readableSide(item.side)}</td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{formatNumber(item.size)} <span className="text-muted-foreground">{sizeUnit}</span></td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{formatNumber(item.contract_size)}</td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{formatNumber(item.entry_price)}</td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{formatNumber(item.exit_price)}</td>
      <td className={`px-3 py-3 text-right align-top font-mono font-semibold tabular-nums ${pnlToneClass(item.pnl)}`}>
        <span className="mr-1 text-xs font-normal text-muted-foreground">{pnlState}</span>{formatUsdtMoney(item.pnl, { signed: true, dollarStyle: true })}
      </td>
      <td className="px-3 py-3 align-top text-xs text-muted-foreground"><span className="text-foreground">{item.pnl_basis || pnlBasis}</span><br />{readableReason(item.fee_status || "fee_net_pnl_unavailable_phase2_ledger_required")}</td>
      <td className={`px-3 py-3 text-right align-top font-mono tabular-nums ${pnlToneClass(item.pnl_percent)}`}>{pnlState} {formatPercent(item.pnl_percent)}</td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{item.leverage == null ? "—" : `${formatNumber(item.leverage)}x`}</td>
      <td className="px-3 py-3 text-right align-top font-mono tabular-nums text-foreground">{formatMinutes(item.duration_minutes)}</td>
      <td className="py-3 pl-3 align-top text-muted-foreground"><span className="text-foreground">{readableReason(item.close_reason) || "Closed"}</span><UnavailableReasons reasons={item.unavailable_reasons} /></td>
    </tr>
  );
}

function TradeExplorerCard({
  item,
  pnlBasis,
  sizeUnit,
  onOpen,
}: {
  item: TradeExplorerItem;
  pnlBasis: string;
  sizeUnit: string;
  onOpen: () => void;
}) {
  const pnlState = pnlStateLabel(item.pnl);
  return (
    <article className="min-w-0 border border-border bg-card p-4" aria-label={`Trade Explorer row ${item.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-mono text-sm font-semibold tabular-nums text-foreground">{item.symbol || "—"}</h3>
          <p className="mt-1 text-xs text-muted-foreground">ID <span className="font-mono tabular-nums text-foreground">{item.id}</span> · {readableSide(item.side)}</p>
        </div>
        <p className={`text-right font-mono text-sm font-semibold tabular-nums ${pnlToneClass(item.pnl)}`}><span className="block text-xs font-normal text-muted-foreground">{pnlState}</span>{formatUsdtMoney(item.pnl, { signed: true, dollarStyle: true })}</p>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <Detail label="Size" value={`${formatNumber(item.size)} ${sizeUnit}`} />
        <Detail label="Contract size" value={formatNumber(item.contract_size)} />
        <Detail label="Entry" value={formatNumber(item.entry_price)} />
        <Detail label="Exit" value={formatNumber(item.exit_price)} />
        <Detail label="PnL %" value={`${pnlState} ${formatPercent(item.pnl_percent)}`} />
        <Detail label="Leverage" value={item.leverage == null ? "—" : `${formatNumber(item.leverage)}x`} />
        <Detail label="Open time" value={formatTime(item.open_time)} />
        <Detail label="Close time" value={formatTime(item.close_time)} />
        <Detail label="Duration" value={formatMinutes(item.duration_minutes)} />
        <Detail label="Close reason" value={readableReason(item.close_reason)} />
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground"><span className="text-foreground">{item.pnl_basis || pnlBasis}</span>; {readableReason(item.fee_status || "fee_net_pnl_unavailable_phase2_ledger_required")}; currency USDT.</p>
      <UnavailableReasons reasons={item.unavailable_reasons} />
      <button
        type="button"
        className="mt-3 w-full border border-border bg-background px-3 py-2 text-sm text-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        onClick={onOpen}
        aria-label={`Open trade detail for ${item.symbol || "position"} ID ${item.id}`}
      >
        View trade detail
      </button>
    </article>
  );
}

function TradeDetailDrawer({
  item,
  open,
  onOpenChange,
  pnlBasis,
  sizeUnit,
  exchange,
}: {
  item: TradeExplorerItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pnlBasis: string;
  sizeUnit: string;
  exchange?: string | null;
}) {
  const symbol = item?.symbol || "";
  const journalHref = symbol
    ? `/journal?symbol=${encodeURIComponent(symbol)}${exchange ? `&exchange=${encodeURIComponent(exchange)}` : ""}`
    : "/journal";
  const pnlState = pnlStateLabel(item?.pnl);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" aria-describedby="trade-detail-description">
        <SheetHeader>
          <SheetTitle className="font-mono tabular-nums">
            {item?.symbol || "Trade detail"}
          </SheetTitle>
          <SheetDescription id="trade-detail-description">
            Closed-position detail from stored history. Fee-net PnL stays unavailable until ledger coverage allows it.
          </SheetDescription>
        </SheetHeader>
        {item ? (
          <div className="mt-6 grid gap-4 text-sm">
            <p className="text-xs text-muted-foreground">
              ID <span className="font-mono tabular-nums text-foreground">{item.id}</span>
              {" · "}
              {readableSide(item.side)}
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
              <Detail label="PnL" value={`${pnlState} ${formatUsdtMoney(item.pnl, { signed: true, dollarStyle: true })}`} />
              <Detail label="PnL %" value={`${pnlState} ${formatPercent(item.pnl_percent)}`} />
              <Detail label="Size" value={`${formatNumber(item.size)} ${item.size_unit || sizeUnit}`} />
              <Detail label="Contract size" value={formatNumber(item.contract_size)} />
              <Detail label="Entry" value={formatNumber(item.entry_price)} />
              <Detail label="Exit" value={formatNumber(item.exit_price)} />
              <Detail label="Leverage" value={item.leverage == null ? "—" : `${formatNumber(item.leverage)}x`} />
              <Detail label="Duration" value={formatMinutes(item.duration_minutes)} />
              <Detail label="Open time" value={formatTime(item.open_time)} />
              <Detail label="Close time" value={formatTime(item.close_time)} />
              <Detail label="Close reason" value={readableReason(item.close_reason) || "Closed"} />
              <Detail label="Currency" value={item.currency_unit || "USDT"} />
            </dl>
            <div className="border border-border bg-card p-3 text-xs leading-relaxed text-muted-foreground">
              <p>
                <span className="text-foreground">{item.pnl_basis || pnlBasis}</span>
                {"; "}
                {readableReason(item.fee_status || "fee_net_pnl_unavailable_phase2_ledger_required")}.
              </p>
              <UnavailableReasons reasons={item.unavailable_reasons} />
            </div>
            <div className="grid gap-2">
              <Link
                href={journalHref}
                className="border border-border bg-background px-3 py-2 text-center text-sm text-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                Open journal{symbol ? ` for ${symbol}` : ""}
              </Link>
              <p className="text-xs text-muted-foreground">
                Orders, fills, and funding are not on this payload; use Trade Attribution / capital flow for linked streams when available.
              </p>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{label}</dt>
      <dd className="break-words font-mono tabular-nums text-foreground">{value || "—"}</dd>
    </div>
  );
}

function UnavailableReasons({ reasons }: { reasons?: TradeExplorerItem["unavailable_reasons"] }) {
  const entries = normalizeUnavailableReasons(reasons);
  if (entries.length === 0) return <p className="mt-1 text-xs text-muted-foreground">Unavailable reasons: none reported.</p>;
  return (
    <ul className="mt-1 grid gap-1 text-xs text-muted-foreground" aria-label="Unavailable reasons">
      {entries.map((reason) => <li key={reason}>Unavailable: {readableReason(reason)}</li>)}
    </ul>
  );
}

type ParsedSort = {
  field: TradeExplorerSortField;
  direction: "ascending" | "descending";
  label: string;
  directionLabel: string;
};

function parseSort(value: string | null | undefined): ParsedSort {
  const raw = value || "-close_time";
  const descending = raw.startsWith("-");
  const field = raw.replace(/^-/, "") as TradeExplorerSortField;
  const safeField = field in SORT_LABELS ? field : "close_time";
  return {
    field: safeField,
    direction: descending ? "descending" : "ascending",
    label: SORT_LABELS[safeField],
    directionLabel: descending ? "descending" : "ascending",
  };
}

function normalizeUnavailableReasons(reasons: TradeExplorerItem["unavailable_reasons"]): string[] {
  if (!reasons) return [];
  if (Array.isArray(reasons)) return reasons.filter(Boolean);
  return Object.entries(reasons)
    .filter(([, value]) => Boolean(value))
    .map(([key]) => key);
}

function pnlStateLabel(value: number | null | undefined): string {
  if (value == null || value === 0) return "Flat";
  return value > 0 ? "Profit" : "Loss";
}

function readableSide(side: string | null | undefined): string {
  if (!side) return "Unknown side";
  const lower = side.toLowerCase();
  if (lower === "buy" || lower === "long") return "Long";
  if (lower === "sell" || lower === "short") return "Short";
  return side;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  if (Math.abs(value) < 0.0001) return value.toExponential(2);
  return parseFloat(value.toFixed(8)).toString();
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function emptyTradeExplorer(): TradeExplorerResponse {
  return {
    sort: "-close_time",
    limit: 50,
    offset: 0,
    total: 0,
    has_more: false,
    items: [],
  };
}

export default TradeExplorer;
