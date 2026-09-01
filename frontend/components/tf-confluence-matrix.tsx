import type { QqeSignals, StructureByTF } from "@/lib/types";

type Cell = { text: string; tone: "long" | "short" | "mixed" };

const COLS = [
  { key: "1h", label: "1H" },
  { key: "4h", label: "4H" },
  { key: "daily", label: "1D" },
  { key: "weekly", label: "1W" },
] as const;

function structureCell(structure: StructureByTF | null | undefined, tf: "1h" | "4h" | "daily" | "weekly"): Cell {
  const label = structure?.[tf]?.label;
  if (!label || label === "unknown" || label === "Insufficient data") {
    return { text: "—", tone: "mixed" };
  }
  if (label === "HH" || label === "HL") return { text: label, tone: "long" };
  if (label === "LH" || label === "LL") return { text: label, tone: "short" };
  return { text: label, tone: "mixed" };
}

function qqeCell(qqe: QqeSignals | null | undefined, tf: "1h" | "4h" | "daily"): Cell {
  const trend = qqe?.[tf]?.trend;
  if (!trend || trend === "NEUTRAL") return { text: "—", tone: "mixed" };
  if (trend === "GREEN") return { text: "QQE up", tone: "long" };
  return { text: "QQE down", tone: "short" };
}

const TONE: Record<Cell["tone"], string> = {
  long: "text-[#6CA98F]",
  short: "text-[#C96A55]",
  mixed: "text-[#8E8778]",
};

export function TfConfluenceMatrix({
  structure,
  qqe,
}: {
  structure: StructureByTF | null | undefined;
  qqe: QqeSignals | null | undefined;
}) {
  const rows = [
    {
      label: "Structure",
      cells: COLS.map((col) => structureCell(structure, col.key)),
    },
    {
      label: "QQE",
      cells: COLS.map((col) =>
        col.key === "weekly" ? { text: "—", tone: "mixed" as const } : qqeCell(qqe, col.key)
      ),
    },
  ];

  return (
    <section aria-label="Timeframe confluence" className="border border-[#2A2620] bg-[#161411] p-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8E8778]">
        Timeframe confluence
      </h2>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-left text-[#8E8778]">
            <th className="py-1 font-medium"> </th>
            {COLS.map((col) => (
              <th key={col.key} className="py-1 text-right font-medium">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-t border-[#2A2620]">
              <td className="py-2 text-[#8E8778]">{row.label}</td>
              {row.cells.map((cell, i) => (
                <td key={COLS[i].key} className={`py-2 text-right font-mono ${TONE[cell.tone]}`}>
                  {cell.text}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
