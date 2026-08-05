import {
  buildClosedPositionsHref,
  insightPrimaryHref,
} from "@/components/portfolio/strategy-insight-panel";
import type { StrategyInsightCard } from "@/lib/types";

describe("buildClosedPositionsHref", () => {
  it("builds portfolio analytics closed-positions deep link with symbol", () => {
    const href = buildClosedPositionsHref("mexc", "BTCUSDT");
    expect(href).toBe(
      "/portfolio?exchange=mexc&tab=analytics&analytics_tab=closed-positions&symbols=BTCUSDT",
    );
  });

  it("omits symbols when empty", () => {
    const href = buildClosedPositionsHref("binance", "  ");
    expect(href).toBe(
      "/portfolio?exchange=binance&tab=analytics&analytics_tab=closed-positions",
    );
  });

  it("uppercases symbols CSV", () => {
    expect(buildClosedPositionsHref("mexc", "btcusdt,ethusdt")).toContain(
      "symbols=BTCUSDT%2CETHUSDT",
    );
  });
});

describe("insightPrimaryHref", () => {
  it("uses closed positions for concentration evidence_symbol", () => {
    const insight: StrategyInsightCard = {
      id: "symbol_pnl_concentration",
      severity: "warning",
      title: "Concentration: BTCUSDT",
      body: "…",
      evidence_symbol: "BTCUSDT",
      evidence_href:
        "/portfolio?exchange=mexc&tab=analytics&analytics_tab=closed-positions&symbols=BTCUSDT",
    };
    const { href, label } = insightPrimaryHref(insight, "mexc");
    expect(label).toBe("View closed positions");
    expect(href).toContain("analytics_tab=closed-positions");
    expect(href).toContain("symbols=BTCUSDT");
  });

  it("falls back to closed positions when only evidence_symbol is set", () => {
    const insight: StrategyInsightCard = {
      id: "custom",
      severity: "info",
      title: "Sym",
      body: "…",
      evidence_symbol: "ETHUSDT",
    };
    const { href, label } = insightPrimaryHref(insight, "mexc");
    expect(label).toBe("View closed positions");
    expect(href).toBe(
      "/portfolio?exchange=mexc&tab=analytics&analytics_tab=closed-positions&symbols=ETHUSDT",
    );
  });

  it("keeps journal for tag insights", () => {
    const insight: StrategyInsightCard = {
      id: "best_tag",
      severity: "positive",
      title: "Best",
      body: "…",
      evidence_tag: "scalp",
      evidence_href: "/journal?tag=scalp",
    };
    const { href, label } = insightPrimaryHref(insight, "mexc");
    expect(label).toBe("Open journal");
    expect(href).toContain("/journal");
    expect(href).toContain("tag=scalp");
    expect(href).toContain("exchange=mexc");
  });
});
