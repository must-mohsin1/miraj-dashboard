import { render, screen } from "@testing-library/react";

import { VerdictCard } from "./verdict-card";
import type { ScanVerdictData } from "@/lib/types";

const baseGates: ScanVerdictData["gates"] = [
  { id: "regime", label: "Weekly BMSB regime", passed: false, detail: "regime=bear" },
  { id: "structure", label: "Multi-TF structure", passed: false, detail: "weekly=HH, daily=LH, 4h=LL" },
  { id: "momentum", label: "Multi-TF QQE momentum", passed: false, detail: "daily=RED, 4h=GREEN, 1h=RED" },
  { id: "zone", label: "Actionable entry zone", passed: false, detail: "no direction-matched 4H order block within 3% of price" },
  { id: "risk", label: "2R room", passed: false, detail: "n/a — no directional plan to assess" },
];

const noTradeVerdict: ScanVerdictData = {
  schema_version: 1,
  state: "NO_TRADE",
  display: "NO TRADE TODAY",
  bias: "SHORT",
  actionable: false,
  gates: baseGates,
  blockers: ["Multi-TF structure: weekly=HH, daily=LH, 4h=LL"],
  reasoning:
    "No coherent direction: regime=bear; structure weekly=HH, daily=LH, 4h=LL; QQE daily=RED, 4h=GREEN, 1h=RED. Bias leans SHORT without full confirmation — do not front-run it.",
  next_review: "next 4H candle close",
};

const readyLongVerdict: ScanVerdictData = {
  ...noTradeVerdict,
  state: "READY_LONG",
  display: "READY LONG",
  bias: "LONG",
  actionable: true,
  blockers: [],
  gates: baseGates.map((g) => ({ ...g, passed: true })),
  reasoning:
    "LONG setup confirmed: regime, structure, and momentum are aligned, a direction-matched zone is within pullback range, and the 2R target has room.",
};

describe("VerdictCard", () => {
  it("renders nothing when no verdict is supplied (old cached results)", () => {
    const { container } = render(<VerdictCard verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the NO TRADE state, bias, reasoning, blockers, and failed gates", () => {
    render(<VerdictCard verdict={noTradeVerdict} />);

    expect(screen.getByText("NO TRADE TODAY")).toBeInTheDocument();
    expect(screen.getByText("Bias: SHORT")).toBeInTheDocument();
    expect(screen.getByText(/do not front-run it/)).toBeInTheDocument();
    expect(screen.getByText("Blockers")).toBeInTheDocument();
    expect(
      screen.getByText("Multi-TF structure: weekly=HH, daily=LH, 4h=LL")
    ).toBeInTheDocument();
    expect(screen.getByText("Re-check: next 4H candle close")).toBeInTheDocument();
    // All five gates render with their details
    expect(screen.getByText("Weekly BMSB regime")).toBeInTheDocument();
    expect(
      screen.getByText("no direction-matched 4H order block within 3% of price")
    ).toBeInTheDocument();
  });

  it("shows READY LONG with no blockers section when all gates pass", () => {
    render(<VerdictCard verdict={readyLongVerdict} />);

    expect(screen.getByText("READY LONG")).toBeInTheDocument();
    expect(screen.getByText("Bias: LONG")).toBeInTheDocument();
    expect(screen.queryByText("Blockers")).not.toBeInTheDocument();
  });
});
