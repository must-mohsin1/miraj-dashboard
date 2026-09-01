import type {
  MacdData,
  OrderBlock,
  QqeSignals,
  ScanVerdictData,
  StructureByTF,
} from "@/lib/types";

export type SetupSide = "LONG" | "SHORT";

export interface SetupCandidate {
  side: SetupSide;
  zoneLow: number;
  zoneHigh: number;
  midpoint: number;
  invalidation: number;
  targetOne: number;
  distancePct: number;
  label: string;
}

function formatPrice(value: number): string {
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return value.toFixed(4);
}

function zoneMid(ob: OrderBlock): number | null {
  if (ob.price_low == null || ob.price_high == null) return null;
  return (ob.price_low + ob.price_high) / 2;
}

export function pickCandidates(
  orderBlocks: OrderBlock[] | null | undefined,
  price: number | null | undefined
): { long: SetupCandidate | null; short: SetupCandidate | null } {
  if (!orderBlocks || price == null || !Number.isFinite(price) || price === 0) {
    return { long: null, short: null };
  }

  let long: SetupCandidate | null = null;
  let short: SetupCandidate | null = null;

  for (const ob of orderBlocks) {
    if (ob.price_low == null || ob.price_high == null) continue;
    const mid = zoneMid(ob);
    if (mid == null) continue;
    const type = ob.type.toLowerCase();
    const width = Math.abs(ob.price_high - ob.price_low);
    const stop = Math.max(width, price * 0.005);

    if (type.includes("bull") && ob.price_high <= price) {
      const distancePct = ((price - ob.price_high) / price) * 100;
      const candidate: SetupCandidate = {
        side: "LONG",
        zoneLow: ob.price_low,
        zoneHigh: ob.price_high,
        midpoint: mid,
        invalidation: ob.price_low - stop * 0.1,
        targetOne: mid + 2 * stop,
        distancePct,
        label: distancePct <= 3 ? "In range" : `${distancePct.toFixed(1)}% below price`,
      };
      if (!long || distancePct < long.distancePct) long = candidate;
    }

    if (type.includes("bear") && ob.price_low >= price) {
      const distancePct = ((ob.price_low - price) / price) * 100;
      const candidate: SetupCandidate = {
        side: "SHORT",
        zoneLow: ob.price_low,
        zoneHigh: ob.price_high,
        midpoint: mid,
        invalidation: ob.price_high + stop * 0.1,
        targetOne: mid - 2 * stop,
        distancePct,
        label: distancePct <= 3 ? "In range" : `${distancePct.toFixed(1)}% above price`,
      };
      if (!short || distancePct < short.distancePct) short = candidate;
    }
  }

  return { long, short };
}

export function lastFinite(values: Array<number | null | undefined> | null | undefined): number | null {
  if (!values || values.length === 0) return null;
  for (let i = values.length - 1; i >= 0; i--) {
    const value = values[i];
    if (value != null && Number.isFinite(value)) return value;
  }
  return null;
}

export interface SetupIndicatorSnapshot {
  rsi: number | null;
  macdHist: number | null;
  qqe: QqeSignals | null | undefined;
  structure: StructureByTF | null | undefined;
}

function qqeText(qqe: QqeSignals | null | undefined, tf: "1h" | "4h" | "daily"): string {
  const trend = qqe?.[tf]?.trend;
  if (!trend || trend === "NEUTRAL") return "—";
  return trend === "GREEN" ? "up" : "down";
}

function structureText(structure: StructureByTF | null | undefined, tf: "1h" | "4h" | "daily"): string {
  const label = structure?.[tf]?.label;
  if (!label || label === "unknown" || label === "Insufficient data") return "—";
  return label;
}

function CandidateCard({
  title,
  candidate,
  ready,
  missing,
  snapshot,
}: {
  title: "Long" | "Short";
  candidate: SetupCandidate | null;
  ready: boolean;
  missing: string[];
  snapshot: SetupIndicatorSnapshot;
}) {
  const tone = ready
    ? title === "Long"
      ? "text-[#6CA98F]"
      : "text-[#C96A55]"
    : "text-[#8E8778]";
  const rsi = snapshot.rsi;
  const macd = snapshot.macdHist;

  return (
    <article className="border border-[#2A2620] bg-[#161411] p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
          {title}
        </p>
        <p className={`font-mono text-xs ${tone}`}>
          {ready ? "READY" : "Candidate. Not READY."}
        </p>
      </div>
      {candidate ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-sm text-[#EDE7DB]">
          <dt className="text-[#8E8778]">Zone</dt>
          <dd className="text-right">
            {formatPrice(candidate.zoneLow)} – {formatPrice(candidate.zoneHigh)}
          </dd>
          <dt className="text-[#8E8778]">Invalidation</dt>
          <dd className="text-right">{formatPrice(candidate.invalidation)}</dd>
          <dt className="text-[#8E8778]">Projected target</dt>
          <dd className="text-right">{formatPrice(candidate.targetOne)}</dd>
          <dt className="text-[#8E8778]">Distance</dt>
          <dd className="text-right">{candidate.label}</dd>
        </dl>
      ) : (
        <p className="mt-3 text-sm text-[#8E8778]">No nearby {title.toLowerCase()} zone on this scan.</p>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-[#2A2620] pt-3 font-mono text-[11px] text-[#EDE7DB]">
        <dt className="text-[#8E8778]">RSI</dt>
        <dd className="text-right">{rsi == null ? "—" : rsi.toFixed(1)}</dd>
        <dt className="text-[#8E8778]">MACD hist</dt>
        <dd className="text-right">
          {macd == null ? "—" : `${macd > 0 ? "+" : ""}${macd.toFixed(4)}`}
        </dd>
        <dt className="text-[#8E8778]">QQE 1H / 4H / 1D</dt>
        <dd className="text-right">
          {qqeText(snapshot.qqe, "1h")} · {qqeText(snapshot.qqe, "4h")} · {qqeText(snapshot.qqe, "daily")}
        </dd>
        <dt className="text-[#8E8778]">Structure 1H / 4H / 1D</dt>
        <dd className="text-right">
          {structureText(snapshot.structure, "1h")} · {structureText(snapshot.structure, "4h")} · {structureText(snapshot.structure, "daily")}
        </dd>
      </dl>
      {missing.length > 0 && !ready && (
        <p className="mt-3 text-xs text-[#8E8778]">
          Still missing: {missing.join(" · ")}
        </p>
      )}
    </article>
  );
}

export function SetupBoard({
  orderBlocks,
  price,
  verdict,
  rsi,
  macd,
  qqe,
  structure,
}: {
  orderBlocks: OrderBlock[] | null | undefined;
  price: number | null | undefined;
  verdict: ScanVerdictData | null | undefined;
  rsi?: number[] | null;
  macd?: MacdData | null;
  qqe?: QqeSignals | null;
  structure?: StructureByTF | null;
}) {
  const { long, short } = pickCandidates(orderBlocks, price);
  const missing = (verdict?.gates ?? [])
    .filter((g) => !g.passed)
    .map((g) => g.label);
  const snapshot: SetupIndicatorSnapshot = {
    rsi: lastFinite(rsi),
    macdHist: lastFinite(macd?.histogram),
    qqe,
    structure,
  };

  return (
    <section aria-label="Setup board" className="grid gap-4 md:grid-cols-2">
      <CandidateCard
        title="Long"
        candidate={long}
        ready={verdict?.state === "READY_LONG"}
        missing={missing}
        snapshot={snapshot}
      />
      <CandidateCard
        title="Short"
        candidate={short}
        ready={verdict?.state === "READY_SHORT"}
        missing={missing}
        snapshot={snapshot}
      />
    </section>
  );
}
