# Design System — Miraj Research & Decision Desk ("INK & OXIDE")

## Product Context
- **What this is:** A crypto trading decision system that prints one authored judgment per pair per scan — verdict-first, gate-checked, and honest about saying NO TRADE.
- **Who it's for:** Serious retail traders following the Miraj/SMC methodology who want discipline enforced, not signals sprayed.
- **Space/industry:** Crypto TA / trading terminals. Peers: TradingView, Coinglass, Hyperliquid, exchange UIs.
- **Project type:** Data-dense web dashboard (Next.js App Router), dark-first.
- **The memorable thing:** "It told me NO." Calm discipline as the luxury feel — quiet surfaces, one loud verdict.

## Aesthetic Direction
- **Direction:** INK & OXIDE — industrial-utilitarian with editorial gravity. A private desk that publishes a single judgment a day: warm ink room, newspaper front-page authority, terminal precision.
- **Decoration level:** minimal — hairline rules and tone only. No shadows, no gradients, no glow, no glassmorphism.
- **Mood:** Relief, then respect: "this thing is calmer than I am, and it isn't selling me anything." The absence of urgency IS the luxury signal.
- **Reference evidence (2026-07-20):** Hyperliquid (calm dark terminal, single accent), Linear (monochrome restraint as premium), Coinglass (the screaming anti-model), TradingView (category baseline).

## Typography — three voices, strictly cast
- **Verdicts/Mastheads (Display):** Fraunces (variable, optical sizing, weight ~550) — a printed-ruling voice. Used ONLY for verdict statements and page mastheads. Verdicts are sentence case and end with a full stop: "No trade today." **The period is the brand.**
- **Body/UI:** General Sans (Fontshare) — deliberately plain grotesk; it disappears so the verdict keeps the floor.
- **Data/Tables:** JetBrains Mono with `font-feature-settings: "tnum"` — slashed zero, true tabular figures. Every price, score, percentage, and timestamp; always right-aligned in tables.
- **Code:** JetBrains Mono.
- **Rule:** serif speaks verdicts, sans speaks interface, mono speaks numbers. Never two voices in one line.
- **Loading:** self-host via `next/font/local` (download once from Google Fonts / Fontshare); until then `next/font/google` for Fraunces + JetBrains Mono and Fontshare CDN for General Sans.
- **Scale:** 12 / 13.5 / 15 (base) / 17 / 24 / 40 / 64 / 96–128px (verdict, clamp by viewport). Line-height 1.55 body, 1.0–1.1 display.
- **Premium swap (optional, later):** Financier Display / Untitled Sans / Berkeley Mono drop in as pure token swaps if licensed.

## Color — a warm monochrome room; chroma = meaning
- **Approach:** restrained. The interface has no decorative color. Brass is the only non-semantic accent and may touch ONLY masthead rules, focus outlines, and selection.
- **Dark ("Ink edition", default):**
  - `--bg: #0F0E0C` (warm ink — never slate/blue)
  - `--surface: #161411`, `--surface-raised: #1D1A16`
  - `--border: #2A2620` (1px hairlines only)
  - `--text: #EDE7DB` (paper — never pure white), `--text-muted: #8E8778`
  - `--accent: #C2A36B` (brass)
- **Verdict states — one metals family, equal lightness (~L65). A long is not a reward; a NO is not a punishment:**
  - NO_TRADE `#A69D8C` (stone) · WATCH `#D19A4A` (ochre) · READY_LONG `#6CA98F` (verdigris) · READY_SHORT `#C96A55` (rust) · INVALIDATED/STALE `#7E7B8A` (ash — the palette's only cool hue; dead setups read drained)
  - Each state ships three tokens: `ink` (text/border), `wash` (10–12% fill), `line` (border). Candles/charts use verdigris/rust, desaturated.
- **Light ("Print edition"):** not an inversion — the print run. Paper `#F4EFE6`, surface `#EDE7DB`, ink text `#1B1914`, muted `#6E6757`, brass deepened `#8A6F3C`; state hues deepened ~12–15% lightness for WCAG ≥4.5:1.
- **Accessibility:** state color is never the only signal — pair with the chip label, ✓/✗ marks, or arrows. Maintain 4.5:1 contrast on all data text.

## Spacing
- **Base unit:** 4px.
- **Density:** two named modes. **Reading** (verdicts, reasoning, blockers): generous — 24–32px gutters, 64ch max measure. **Instrument** (gates, tables, per-TF evidence): compact — 24px rows, hairline rules between rows, no zebra striping.
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48) 3xl(64).

## Layout
- **Approach:** grid-disciplined; newspaper front page for the Decision Desk. Hard left alignment. **Nothing is ever centered.**
- **Decision Desk (`/now`, becomes home):** masthead line (date · regime · session) under a 1px brass rule → monumental serif verdict (96–128px) → 2–3 reason lines at reading measure → ranked candidate column (numbered rows: symbol, state chip, one blocker line, mono price) + Instruments right rail → discipline ledger (consecutive days stood down, est. drawdown avoided). Asymmetric 8/4 grid; whitespace concentrated above the fold.
- **Analysis page:** the verdict card dominates by isolation — it owns the page's only generous whitespace and its only serif. Order: verdict → why → blockers → gates → trade plan (only when READY) → chart → per-TF evidence → what changed.
- **Grid:** 12-col desktop / 4-col mobile; max content width 1080px for reading surfaces, full-bleed allowed for charts/tables.
- **Border radius:** 0 everywhere. The desk has square corners like a broadsheet column. Exception: none.
- **Elevation:** tone + hairline only. No drop shadows.

## Motion — the desk does not raise its voice
- **Approach:** minimal-functional. Three rules:
  1. **Nothing moves on load.** The page arrives already printed.
  2. **Verdict changes are the only ceremony:** 500ms crossfade. No spring, no bounce, ever.
  3. **Invalidation drains:** on INVALIDATED/STALE, desaturate over 600ms and stamp the timestamp — ink drying.
- Everything else ≤150ms opacity/position. **Live data never flashes:** numbers update silently on a slow cadence with an "as of HH:MM" stamp (replaces the green/red tick flash in portfolio — a deliberate product behavior change).
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out). **Duration:** micro(50–100ms) short(150ms) ceremony(500ms) drain(600ms).

## Anti-slop guardrails (banned outright)
Purple→cyan gradients or any "AI glow"; neon casino bloom; glassmorphism blur; the default Tailwind slate-900/indigo look (the current UI — it dies first); 3-column icon feature grids; centered heroes and blob art; rockets, moons, bulls, 3D coins; candlestick wallpaper; full-saturation red/green P&L; fear/greed speedometer gauges; skeleton shimmer; sparkline confetti; marquee tickers; drop-shadow card stacks; emoji in verdicts; exclamation marks in system copy.

## Deliberate risks (the product's face — do not sand these off)
1. **Warm ink + brass in an all-cool category** — instantly not-another-dashboard.
2. **Serif verdicts with a full stop** — an authored, accountable ruling; serif appears nowhere else.
3. **Equal-loudness verdict states** — the palette refuses to gamify direction.
4. **Kill tick urgency** — slow cadence + as-of stamps; the refusal day is the flagship screen users should want to screenshot.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07-20 | Initial system created (INK & OXIDE) | /design-consultation: category research (Hyperliquid/Linear/Coinglass/TradingView) + outside-voice synthesis; user approved direction, free font stack, and ship |
| 2026-07-20 | Free font casting (Fraunces/General Sans/JetBrains Mono) | $0, self-hostable; premium Klim/Berkeley faces swap in later via tokens if licensed |
| 2026-07-20 | Radius 0, print-edition light mode, silent live numbers | Agent defaults flagged and approved at ship gate |
