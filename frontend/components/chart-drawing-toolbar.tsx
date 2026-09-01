"use client";

export type ChartDrawingTool = "cursor" | "horizontal" | "trend" | "fib";

interface ChartDrawingToolbarProps {
  activeTool: ChartDrawingTool;
  onToolChange: (tool: ChartDrawingTool) => void;
  onClear: () => void;
  hasDrawings?: boolean;
}

const TOOLS: Array<{ tool: ChartDrawingTool; label: string; title: string }> = [
  { tool: "cursor", label: "Cursor", title: "Cursor" },
  { tool: "horizontal", label: "H Line", title: "Horizontal line (one click)" },
  { tool: "trend", label: "Trend", title: "Trend line (two clicks)" },
  { tool: "fib", label: "Fib", title: "Fibonacci retracement (two clicks)" },
];

export function ChartDrawingToolbar({
  activeTool,
  onToolChange,
  onClear,
  hasDrawings = false,
}: ChartDrawingToolbarProps) {
  return (
    <div
      className="mb-2 inline-flex flex-wrap items-center border border-[#2A2620] bg-[#161411] p-1"
      role="toolbar"
      aria-label="Chart drawing tools"
    >
      {TOOLS.map(({ tool, label, title }) => {
        const selected = activeTool === tool;
        return (
          <button
            key={tool}
            type="button"
            title={title}
            aria-pressed={selected}
            onClick={() => onToolChange(tool)}
            className={`border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide transition-colors ${
              selected
                ? "border-[#C2A36B] bg-[#2A2620] text-[#C2A36B]"
                : "border-transparent text-[#8E8778] hover:border-[#2A2620] hover:text-[#D8D1C4]"
            }`}
          >
            {label}
          </button>
        );
      })}
      <span className="mx-1 h-5 w-px bg-[#2A2620]" aria-hidden />
      <button
        type="button"
        title="Clear session drawings"
        onClick={onClear}
        className={`border border-transparent px-2 py-1 text-[11px] font-semibold uppercase tracking-wide transition-colors hover:border-[#2A2620] hover:text-[#D8D1C4] ${
          hasDrawings ? "text-[#C96A55]" : "text-[#5F5A50]"
        }`}
      >
        Clear
      </button>
    </div>
  );
}

export default ChartDrawingToolbar;
