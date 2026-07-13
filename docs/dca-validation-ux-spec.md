# DCA Validation UX Spec

Status: implementation-ready UX slice
Scope: DCA Shadow-Mode Validation approval spec, UI content, and reviewer-observable states
Source approval spec: `/Users/mustcompanymohsin/.hermes/kanban/boards/miraj-dashboard/specs/dca-shadow-mode-validation-spec.md`

## Purpose

Add a read-only validation layer around Dynamic DCA so a portfolio user can inspect scan-history reconstruction, simulated metrics, and shadow-mode safety gates before trusting DCA recommendations. The UI must make three things obvious:

1. This is scan-to-scan reconstruction from stored scan history, not candle-level backtesting.
2. Metrics and fills are simulated under visible fee/slippage assumptions, not realized trading performance.
3. Shadow mode records what would have happened and why, without placing or queuing live orders.

## UX principles

- Evidence before action: show scan counts, date ranges, skipped data, and assumptions before headline performance metrics.
- Insufficient data is a normal state: sparse history should guide the user, not look broken.
- Reviewer-observable by default: every acceptance-relevant state must be visible in UI fixtures without server logs.
- Plain-language risk framing: avoid copy that implies profit prediction, live readiness, or financial advice.
- Accessible status semantics: do not rely on color alone; pair every badge with text and expose details in expandable regions.

## Information architecture

### Validation entry point (AC-E1)

Location: Portfolio DCA area, adjacent to the existing Dynamic DCA panel.

Entry control:
- Label: `Validate DCA history`
- Supporting copy: `Review scan-history reconstruction, simulated metrics, and shadow safety gates.`
- Visibility: authenticated users with portfolio access.
- Disabled state copy: `Sign in with portfolio access to validate DCA history.`
- Loading copy after activation: `Loading DCA validation from stored scan history…`

The entry point opens a dedicated validation view or panel titled `DCA validation`. It must not replace the existing DCA recommendation panel; it is a read-only validation companion.

### Validation view layout

1. Page header
   - Title: `DCA validation`
   - Method badge: `Scan-to-scan reconstruction`
   - Disclaimer: `These are reconstructed and shadow-mode results, not realized trading performance or financial advice.`
2. Summary card
3. Filters row
4. Per-symbol validation list
5. Reconstructed event inspection drawer/table
6. Shadow history and safety-gate details
7. Fixture/debug states visible in review builds or deterministic QA seed data

## Summary card (AC-E3)

The summary card appears above the symbol list and uses one primary card, not a row of generic equal-weight stat boxes. It should establish data quality before performance.

Required fields:
- `Eligible symbols`: count of symbols with enough usable scans to reconstruct metrics.
- `Usable scans`: total count across symbols.
- `Reconstructed recommendations`: total reconstructed ADD / HOLD / REDUCE / CLOSE events.
- `Latest validation`: timestamp of the most recent completed validation run, or `Not run yet`.
- `Blocked by safety gates`: count of shadow decisions with final outcome `would_block`.

Secondary fields:
- `Method`: `Scan-to-scan, not candle-level replay.`
- `Default assumptions`: `Fee 0.04% · slippage 0.05% per simulated entry/exit · split 70% in-sample / 30% out-of-sample.`
- `Data quality`: list of active warnings, including scan gaps over 48 hours, fewer than 30 reconstructed events, missing benchmark data, or materially worse out-of-sample metrics.

Empty state:
- Title: `No validation data yet`
- Body: `Run validation after stored scans are available. The system needs at least 2 usable scans for a symbol before it can reconstruct recommendations.`

Unavailable state:
- Title: `Validation unavailable`
- Body: `DCA validation could not load because {source_name} is missing.`
- Examples for `{source_name}`: `stored scan history`, `portfolio position context`, `mark price`, `trade plan`, `RSI values`.

## Per-symbol states (AC-E2, AC-E7)

Each symbol row/card must expose one of three mutually exclusive states.

### 1. Insufficient history

State badge: `Insufficient history`
Tone: neutral/informational, not error.

Required content:
- `Usable scans: {count}`
- `Required minimum: 2 usable scans`
- `First scan: {timestamp | —}`
- `Last scan: {timestamp | —}`
- `Why metrics are hidden: Win rate, Sharpe, drawdown, and profit factor need at least 2 usable scans.`

Copy:
- Title: `{symbol} needs more scan history`
- Body: `We found {count} usable scan(s). Metrics will appear after at least 2 usable scans with price, RSI, trade plan, and position context.`

Do not display numeric values for win rate, Sharpe, drawdown, or profit factor in this state. Use `—` plus the reason tooltip: `Not enough usable scans.`

### 2. Reconstructing / unavailable

State badge: `Reconstructing` or `Unavailable`

Reconstructing copy:
- Title: `Reconstructing {symbol}`
- Body: `Validation is rebuilding recommendations from stored scan history. You can leave this page and refresh later.`
- Last completed fallback: `Showing last completed validation from {timestamp}.`

Unavailable copy:
- Title: `{symbol} validation unavailable`
- Body: `Validation cannot run because {source_name} is missing.`
- Action hint: `Run new scans or reconnect portfolio data, then retry validation.`

Source-specific missing-data labels (AC-E7):
- `Missing trade plan`
- `Missing RSI`
- `Missing mark price`
- `Malformed scan result`
- `Unsupported direction`
- `Missing position context`

### 3. Metrics available

State badge: `Metrics available`

Required symbol header:
- Symbol and direction, e.g. `SOLUSDT:USDT · LONG`
- Scan count
- First scan timestamp
- Last scan timestamp
- Maximum scan gap
- Method badge: `Scan-to-scan`

Required metrics groups:
- Performance: win rate, total return, gross profit, gross loss, profit factor.
- Risk: max drawdown absolute and percentage, Sharpe, Sortino.
- Behavior: average hold time, exposure percentage, reconstructed trades.
- DCA-specific: entry-level completion rate, average entry price versus planned entry zone, ADD signal follow-through rate, DCA SAFE flag accuracy, 3-entry completion rate.
- Walk-forward: in-sample range and metrics, out-of-sample range and metrics.
- Benchmark: buy-and-hold over the same scan window, or `Benchmark unavailable — {reason}`.

Metric unavailable copy:
- `Not enough samples — needs at least {n} {observation_type}.`
- `No gross losses — profit factor is not shown as a finite number.`
- `Benchmark unavailable — missing first or last usable mark price.`

## Reconstructed event inspection (AC-E4)

Users must be able to inspect at least the latest 50 reconstructed recommendation events per symbol without server logs.

Entry point from symbol card:
- Button label: `View reconstructed events`
- Accessible name: `View reconstructed recommendation events for {symbol}`

Event table columns:
- `Time`
- `Recommendation` (`ADD`, `HOLD`, `REDUCE`, `CLOSE`)
- `Confidence`
- `Reason`
- `Metric eligible` (`Yes`, `No`)
- `Skipped reason` when applicable

Expanded row details:
- `Source scan timestamp`
- `Position context used`
- `RSI`
- `Mark price`
- `Trade plan available` (`Yes` / `No`)
- `Assumed fill` (`Confirmed`, `Assumed`, `No fill`)
- `Fee/slippage assumptions`

Empty state:
- Title: `No reconstructed events for {symbol}`
- Body: `Stored scans were found, but none had enough usable DCA inputs to reconstruct a recommendation.`

Error state:
- Title: `Events could not load`
- Body: `Reconstructed events could not load because {source_name} is missing.`

## Blocked-gate explanation (AC-E5, AC-D8)

Every shadow ADD decision that becomes `would_block` must show the gate-by-gate reason in UI.

Entry points:
- Symbol row badge: `{n} blocked`
- Shadow history row button: `Why blocked?`
- Accessible name: `Show blocked safety gates for {symbol} at {timestamp}`

Blocked details panel title:
- `Why shadow ADD was blocked`

Required fields:
- `Original recommendation`: e.g. `ADD`
- `Shadow outcome`: e.g. `would_block`
- `Final reason`: human-readable final reason string
- `Blocked gates`: list of failed gates
- `Passed gates`: list of passed gates
- `Assumption set`: fee, slippage, fill model, split ratio, exposure cap, cooldown window, rate limits
- `Decision time`: timestamp

Default ADD gate labels:
- `DCA SAFE checklist passes`
- `Confluence score is at least 10`
- `User kill switch is off`
- `Symbol kill switch is off`
- `Global kill switch is off`
- `No more than 3 ADD decisions in the last hour`
- `No more than 10 ADD decisions today (UTC)`
- `Symbol is outside the 24-hour cooldown after CLOSE`
- `Simulated ADD size is at or below 10% of portfolio value`
- `Total DCA exposure stays under the configured cap`

Blocked gate copy examples:
- `Blocked: confluence score is 8.5, below the required 10.`
- `Blocked: symbol kill switch is on for SOLUSDT:USDT.`
- `Blocked: this symbol is still in the 24-hour cooldown after a CLOSE.`
- `Blocked: simulated ADD would exceed the configured exposure cap.`

REDUCE/CLOSE note:
- `Safety gates block new shadow ADD outcomes only. REDUCE and CLOSE recommendations remain visible so urgent risk signals are not hidden.`

## Shadow history filters (AC-D8, AC-D9)

Shadow history is visible in a table or timeline below the summary/symbol list.

Required columns:
- `Time`
- `Symbol`
- `Original recommendation`
- `Shadow outcome`
- `Blocked gates`
- `Assumptions`

Filters:
- Symbol filter label: `Symbol`
  - Placeholder: `All symbols`
  - Empty option: `No symbols with shadow history`
- Outcome filter label: `Outcome`
  - Options: `All outcomes`, `Would allow`, `Would block`, `Would reduce`, `Would close`, `No action`
- Date range filter label: `Date range`
  - Options: `Last 24 hours`, `Last 7 days`, `Last 30 days`, `Custom range`
  - Custom error: `Choose an end date after the start date.`

Empty states:
- No history: `No shadow decisions yet. Shadow outcomes will appear here after validation records prospective DCA decisions.`
- No filter results: `No shadow decisions match these filters. Try a different symbol, outcome, or date range.`

## Simulated-results disclaimer (AC-E6, AC-D10)

Required exact disclaimer text:

`These are reconstructed and shadow-mode results, not realized trading performance or financial advice.`

Placement:
- Page header under title.
- Summary card footer.
- Metrics details drawer before any PnL chart/table.
- Promotion eligibility card.

Promotion eligibility is report-only:
- Card title: `Promotion eligibility`
- Positive label: `Eligible for human review`
- Negative label: `Not eligible for human review`
- Required explanatory copy: `Live execution is out of scope for this release. Eligibility only means the shadow-mode record is ready for human review.`

Eligibility checklist (all required):
- `At least 20 shadow ADD signals`
- `Shadow win rate at least 60%`
- `Profit factor at least 1.3`
- `Max drawdown below 10%`
- `No more than 2 consecutive losses`

Not-actionable control rule:
- Do not render `Enable live trading`, `Promote`, or any order-placement call to action.
- If a disabled placeholder is required for future planning, label it `Live execution out of scope` and keep it non-interactive.

## Acceptance-criteria content map

| AC | UI surface | Required labels/copy | Empty/error/insufficient-data behavior |
| --- | --- | --- | --- |
| AC-E1 | Portfolio DCA area | `Validate DCA history`; `Review scan-history reconstruction, simulated metrics, and shadow safety gates.` | Disabled copy: `Sign in with portfolio access to validate DCA history.` |
| AC-E2 | Symbol cards | `Insufficient history`, `Reconstructing`, `Unavailable`, `Metrics available` | Insufficient history hides numeric metrics and explains scan requirements. |
| AC-E3 | Summary card | `Eligible symbols`, `Usable scans`, `Reconstructed recommendations`, `Latest validation`, `Blocked by safety gates` | `No validation data yet`; `Validation unavailable — {source_name} is missing.` |
| AC-E4 | Event inspection | `View reconstructed events`; table columns `Time`, `Recommendation`, `Confidence`, `Reason`, `Metric eligible`, `Skipped reason` | `No reconstructed events for {symbol}`; source-specific load error. |
| AC-E5 | Blocked details panel | `Why shadow ADD was blocked`; `Original recommendation`; `Shadow outcome`; `Final reason`; `Blocked gates` | `No blocked gates recorded for this decision` only when outcome is not `would_block`. |
| AC-E6 | Header, summary, metrics, eligibility | Exact disclaimer text: `These are reconstructed and shadow-mode results, not realized trading performance or financial advice.` | Disclaimer must display even when metrics are empty. |
| AC-E7 | Symbol unavailable state and summary error | Source labels: `Missing trade plan`, `Missing RSI`, `Missing mark price`, `Malformed scan result`, `Unsupported direction`, `Missing position context` | Never show a generic failure when source data is known. |
| AC-D8 | Shadow history | Columns `Time`, `Symbol`, `Original recommendation`, `Shadow outcome`, `Blocked gates`, `Assumptions` | No history and no-filter-results empty states are distinct. |
| AC-D9 | Shadow history filters | `Symbol`, `Outcome`, `Date range`; options `All symbols`, `All outcomes`, `Would allow`, `Would block`, `Would reduce`, `Would close`, `No action` | Date validation copy: `Choose an end date after the start date.` |
| AC-D10 | Promotion eligibility | `Eligible for human review`; `Not eligible for human review`; live execution out-of-scope copy | No live-trading action can appear; missing metrics show checklist item as unmet with reason. |

## Reviewer-observable fixture states (AC-G5)

Review fixtures must be deterministic and visible through UI state, screenshots, or frontend tests. They must not require server logs.

### Fixture 1: insufficient history

Fixture name: `dcaValidationInsufficientHistory`

Data shape:
- Symbol: `BTCUSDT:USDT`
- Usable scans: `1`
- Required minimum: `2`
- State: `insufficient_history`

Expected visible assertions:
- Badge `Insufficient history` appears.
- Copy includes `BTCUSDT:USDT needs more scan history`.
- Copy includes `We found 1 usable scan(s).`
- Win rate, Sharpe, drawdown, and profit factor display `—`, not `0`, `NaN`, or `Infinity`.
- Tooltip/reason includes `Not enough usable scans.`
- Disclaimer is still visible.

### Fixture 2: metrics available

Fixture name: `dcaValidationMetricsAvailable`

Data shape:
- Symbol: `SOLUSDT:USDT`
- Usable scans: `42`
- Reconstructed recommendations: `18`
- State: `metrics_available`
- Includes in-sample and out-of-sample ranges.
- Includes default assumption set: fee `0.04%`, slippage `0.05%`, split `70/30`.

Expected visible assertions:
- Badge `Metrics available` appears.
- Summary shows `Eligible symbols`, `Usable scans`, `Reconstructed recommendations`, `Latest validation`, and `Blocked by safety gates`.
- Symbol card shows scan count, first scan, last scan, and max scan gap.
- Walk-forward section shows both period date ranges.
- Benchmark row either shows buy-and-hold value or `Benchmark unavailable — {reason}`.
- Metrics with null reasons render explanatory copy, not fake numeric values.

### Fixture 3: shadow blocked reason

Fixture name: `dcaValidationShadowBlockedReason`

Data shape:
- Symbol: `ETHUSDT:USDT`
- Original recommendation: `ADD`
- Shadow outcome: `would_block`
- Failed gates: `Confluence score is at least 10`, `Total DCA exposure stays under the configured cap`
- Passed gates include kill switches and rate limits.

Expected visible assertions:
- Shadow history row shows `ADD` and `would_block`.
- Row includes blocked gate count.
- `Why blocked?` opens details without server logs.
- Details panel shows `Why shadow ADD was blocked`.
- Details panel shows final reason in plain language.
- Details panel separates `Blocked gates` from `Passed gates`.
- Assumption set is visible at decision time.

### Fixture 4: disclaimer display

Fixture name: `dcaValidationDisclaimerDisplay`

Data shape:
- Any validation state, including empty or insufficient data.

Expected visible assertions:
- Exact disclaimer appears in the page header.
- Exact disclaimer appears in the summary card footer.
- Exact disclaimer appears before metrics/PnL details when metrics are available.
- Promotion eligibility card includes `Live execution is out of scope for this release.`
- No live execution CTA appears.

## Accessibility requirements

- Use headings in order: page title `h1`, major sections `h2`, card titles `h3` where applicable.
- Use real buttons for expandable details (`View reconstructed events`, `Why blocked?`) with visible focus rings.
- Tables must have column headers and accessible names, e.g. `Shadow history` and `Reconstructed events for {symbol}`.
- Status badges must include text; color is supplemental only.
- Loading/reconstructing updates should use polite live-region behavior if content changes asynchronously.
- Numeric metric values should use tabular numerals but retain text labels for screen readers.
- Error messages must identify the missing source and be associated with the affected symbol/section.
- Respect reduced motion; expanding drawers may animate opacity/height only when motion is allowed.

## Implementation notes for frontend handoff

- Treat validation responses as read-only; no live order, queue, signing, or exchange action is available from this UI.
- Keep existing Dynamic DCA recommendation behavior available if validation data is unavailable.
- Use current dark card language from the portfolio DCA and DCA Strategy panels, but prioritize hierarchy: summary first, symbol evidence second, metrics/details third.
- Prefer compact badges for state, but use full sentences for risk/disclaimer copy.
- Null metrics must render as unavailable with reasons; never coerce to `0`, `NaN`, or finite placeholders.
