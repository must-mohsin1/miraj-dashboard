# Dynamic DCA — Implementation Profile

**Created:** 2026-07-08
**Status:** PLANNED (not yet implemented)
**Scope:** Position-aware Dollar Cost Averaging engine for the Miraj Dashboard

---

## 1. PROBLEM STATEMENT

The Miraj Dashboard has a static DCA system in the backend (`mirai_core/trade_plan.py`) that generates generic strings like "Don't enter full position at once" and "Split into 3 entries based on RSI levels." These are thrown away by `_build_flat_trade_plan()` and never rendered in the frontend.

The existing position alerts system (`position_alert_service.py`) warns when QQE/structure conflicts with a position, but provides no actionable DCA guidance — no entry levels, no "should I add or reduce?", no adaptive ladder.

**What's missing:**
- No DCA suggestions per open position
- No RSI three-entry system (20/20/60) displayed anywhere
- No zone-based DCA triggers (OTE/demand zone)
- No budget enforcement (max position size tracking)
- No adaptive ladder (adjusts to user's actual entry RSI)
- No profit-taking recommendations at TP1/TP2
- No "what would trigger an ADD" guidance
- No DCA data in Obsidian exports

---

## 2. DESIGN PRINCIPLES

1. **Zone-first, RSI-second** — OTE/demand zone is the primary DCA trigger. RSI is confirmation, not the sole trigger. (Miraj teaches RSI three-entry for 1-min scalping only; swing trades use zone-based DCA.)

2. **Adaptive ladder** — The entry ladder adjusts to the user's actual entry price/RSI, not a fixed 30/24/16 assumption.

3. **Budget enforcement** — Once max position size (0.5-1% portfolio) is deployed, no more ADD. Only HOLD/REDUCE/CLOSE.

4. **Hard exits override everything** — Liquidation proximity, confluence flip, BMSB regime check block all ADD signals.

5. **Actionable output** — Not "consider reducing" but "close 6 of 12 contracts at ~$77.57, move stop to $74.91."

6. **Reuse existing infrastructure** — Same scan-fetching pattern as `position_alert_service.py`. Same endpoint pattern as `position-alerts`. Same component pattern as `position-alerts-panel.tsx`.

---

## 3. DECISION TREE

```
FOR EACH OPEN POSITION:

  FETCH scan for position symbol (cached 15min, else run_scan)

  STEP 1: HARD EXITS (override everything)
  ├─ liq_distance < 2%?                        → CLOSE (CRITICAL)
  ├─ scan_direction opposite + 3+ conflicts?   → CLOSE (CRITICAL)
  └─ BMSB below + is_long?                     → REDUCE (HIGH)

  STEP 2: PROFIT-TAKING
  ├─ pnl_pct >= 100%?                          → REDUCE (HIGH)
  ├─ price >= TP1?                             → REDUCE (HIGH)
  └─ price >= TP2?                             → REDUCE (HIGH)

  STEP 3: QQE CONFLICTS
  ├─ Daily + 4H QQE both against?             → REDUCE (HIGH)
  └─ Only 4H QQE against?                     → HOLD (MEDIUM)

  STEP 4: DCA DISABLED CONDITIONS
  ├─ BB squeezing on any TF?                  → HOLD (MEDIUM)
  ├─ No QQE aligned on any TF?                → HOLD (MEDIUM)
  ├─ Confluence < 10?                          → HOLD (MEDIUM)
  └─ Confirmed opposite pattern?              → HOLD (HIGH)

  STEP 5: ZONE-BASED ADD
  ├─ price in OTE + QQE aligned + RSI oversold → ADD (HIGH)
  ├─ price in OTE + QQE aligned               → ADD (MEDIUM)
  └─ RSI oversold but NOT in OTE             → HOLD (MEDIUM)

  STEP 6: DEFAULT
  └─ None of the above                        → HOLD (LOW)

  COMPUTE:
  - Adaptive RSI entry ladder (based on actual entry)
  - Next entry (first "pending" in ladder)
  - Future ADD triggers (what needs to change)
  - Action items (concrete steps)
  - Risk rules
```

---

## 4. ADAPTIVE RSI LADDER

The static Miraj system (20%@RSI30, 20%@RSI24, 60%@RSI16-18) assumes the user starts at RSI 30. Real entries don't follow this. The adaptive ladder adjusts:

### Entry at RSI 45 (above all triggers, e.g. breakout/FOMO entry):
```
Entry 1: "Price returns to OTE zone $X-$Y"  20%  PENDING  (zone-based)
Entry 2: "RSI hits 30"                       20%  PENDING  (RSI-based)
Entry 3: "RSI hits 16"                       60%  PENDING  (RSI-based)
→ Trigger type: zone for Entry 1, RSI for 2-3
→ If price bounces at RSI 28 in the OTE zone:
  "ADD 20% — price in OTE zone + RSI approaching Entry 2 trigger"
  (skips Entry 1's exact RSI, uses zone proximity instead)
```

### Entry at RSI 18 (already at deepest oversold):
```
Entry 1: RSI 30   20%  FILLED (entered below)
Entry 2: RSI 24   20%  FILLED (entered below)
Entry 3: RSI 16   60%  FILLED (entered at 18)
→ Total deployed: 100%
→ Recommendation: HOLD — full position deployed
→ If price drops below stop → CLOSE, no more averaging
```

### Entry at RSI 32 (just above Entry 1):
```
Entry 1: RSI 30   20%  FILLED (price dropped to 30)
Entry 2: RSI 24   20%  PENDING ← NEXT
Entry 3: RSI 16   60%  PENDING
→ Deployed: 20%, remaining: 80%
→ Next: deploy 20% when RSI hits 24
→ If price bounces at RSI 26 without hitting 24:
  "HOLD — RSI bounced at 26, didn't reach Entry 2 trigger.
   If price is still in OTE zone, consider adding — zone is valid."
```

### RSI never hits 24 or 16:
```
→ Price bounces at RSI 28 and rallies
→ Entry 1 (20%) is filled, Entries 2+3 never trigger
→ System evaluates: is price still in the OTE zone?
  - YES + QQE aligned → ADD the remaining 80% (zone overrides RSI)
  - NO → HOLD, don't chase the rally
→ Records: "Entry 2 skipped — RSI bounced at 28, price left OTE zone"
```

---

## 5. BUDGET ENFORCEMENT

```
Position budget = 0.5-1% of portfolio value
Max contracts = budget / (entry_price * contract_size)

Track:
  initial_entry_price: first fill price
  avg_entry_price: weighted average across all fills
  total_deployed_pct: 0-100% of budget
  remaining_pct: 100% - deployed_pct

When deployed_pct >= 100%:
  → No more ADD recommendations
  → Only HOLD / REDUCE / CLOSE
  → "Full position deployed. Manage with stop loss."
```

---

## 6. FILES TO CREATE/MODIFY

| # | File | Action | Est. Lines | Description |
|---|------|--------|-----------|-------------|
| 1 | `backend/services/dca_service.py` | CREATE | ~350 | Core DCA engine: scan fetching, evaluation, adaptive ladder |
| 2 | `backend/routes/portfolio.py` | MODIFY | +130 | Pydantic schemas + GET `/{exchange}/dca` endpoint |
| 3 | `frontend/components/portfolio/dca-panel.tsx` | CREATE | ~320 | Client component: fetch DCA API, render cards |
| 4 | `frontend/components/portfolio/portfolio-dashboard.tsx` | MODIFY | +5 | Import + render `<DcaPanel>` above Tabs |
| 5 | `frontend/lib/types.ts` | MODIFY | +35 | TypeScript interfaces for DCA response |
| 6 | `mirai_core/trade_plan.py` | MODIFY | +20 | Expose `tp1_price`/`tp2_price` as top-level fields |
| 7 | `backend/services/analysis_service.py` | MODIFY | +15 | Add TP levels to `_build_flat_trade_plan()` |
| 8 | `backend/obsidian.py` | MODIFY | +20 | Export DCA + RSI entries + risk rules to markdown |

---

## 7. FILE SPECS

### 7.1 `backend/services/dca_service.py` (CREATE)

Pattern: follows `position_alert_service.py` exactly.

```python
"""Dynamic DCA service — position-aware Dollar Cost Averaging engine."""

from __future__ import annotations
import asyncio, logging
from typing import Any, Dict, List, Optional

from backend.services.analysis_service import get_cached_or_none, run_scan
from backend.services.position_alert_service import normalize_to_scan_symbol

logger = logging.getLogger(__name__)

# ── Miraj constants ──
RSI_ENTRY_THRESHOLDS_LONG = (30, 24, 16)
RSI_ENTRY_THRESHOLDS_SHORT = (80, 92, 95)
RSI_ENTRY_ALLOCATIONS = (0.20, 0.20, 0.60)
SCORE_TRADE_THRESHOLD = 10


# ── Data extraction helpers ──

def _current_rsi(scan, timeframe="daily") -> Optional[float]:
    """Extract RSI value from scan indicators for a given timeframe."""

def _rsi_all_tf(scan) -> Dict[str, float]:
    """Return {daily, 4h, 1h, 15m} RSI values."""

def _qqe_trends(scan) -> Dict[str, str]:
    """Return {daily, 4h, 1h} → 'GREEN'/'RED'/'NEUTRAL'."""

def _structure_labels(scan) -> Dict[str, str]:
    """Return {weekly, daily, 4h, 1h, 15m} → 'HH'/'HL'/'LH'/'LL'/''."""

def _bb_squeeze_any(scan) -> bool:
    """Check if Bollinger Bands are squeezing on any timeframe."""

def _ote_zone(scan) -> Optional[tuple[float, float]]:
    """Extract OTE zone (low, high) from the scan's trade plan."""

def _confluence_score(scan) -> float:
    """Return confluence score (0-30)."""

def _scan_direction(scan) -> Optional[str]:
    """Infer directional bias from trade_plan."""

def _bmsb_status(scan) -> Dict[str, Any]:
    """Return {sma_20w, ema_21w, current_price, status, regime}."""

def _chart_patterns(scan) -> List[Dict[str, Any]]:
    """Return [{name, direction, confirmed}] for detected patterns."""

def _trade_plan_tp_levels(scan) -> List[float]:
    """Return [tp1, tp2] price levels from trade plan."""


# ── Adaptive RSI entry ladder ──

def compute_adaptive_entries(
    direction: str,          # LONG or SHORT
    rsi_current: Optional[float],
    rsi_at_entry: Optional[float],
    entry_price: float,
    ote_zone: Optional[tuple[float, float]],
    position_budget_pct: float,   # already deployed (0-1)
) -> List[Dict[str, Any]]:
    """
    Compute DCA entry levels ADAPTED to the user's actual entry.

    - If user entered at RSI 45 → ladder shifts to zone-based for Entry 1
    - If user entered at RSI 18 → all entries FILLED, no more DCA
    - RSI levels become secondary to OTE zone proximity

    Returns list of:
        {entry, trigger, position_size_pct, cumulative_pct,
         status, trigger_type, rsi_target, level_price}
    """


# ── Core evaluation ──

def evaluate_dca(position: Dict[str, Any], scan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Decision tree for a single position vs scan.

    Position must have: symbol, side, size, entry_price, mark_price,
    pnl, pnl_percent, leverage, liquidation_price, margin.

    Returns:
        recommendation: ADD / HOLD / REDUCE / CLOSE
        reason: str
        confidence: LOW / MEDIUM / HIGH / CRITICAL
        rsi_current: float | None
        rsi_entries: list[dict]  (adaptive ladder)
        next_entry: dict | None
        dca_zone: dict | None
        tp_levels: list[float]
        risk_rules: list[str]
        future_add_triggers: list[str]
        action_items: list[str]
    """
    # STEP 1: Hard exits
    #   1a. liq_distance < 2% → CLOSE (CRITICAL)
    #   1b. scan_direction opposite + 3+ conflicts → CLOSE (CRITICAL)
    #   1c. BMSB below + is_long → REDUCE (HIGH)

    # STEP 2: Profit-taking
    #   2a. pnl_pct >= 100% → REDUCE (HIGH)
    #   2b. price >= TP1 → REDUCE (HIGH), take 50%
    #   2c. price >= TP2 → REDUCE (HIGH), take remaining

    # STEP 3: QQE conflicts
    #   3a. Daily + 4H both against → REDUCE (HIGH)
    #   3b. Only 4H against → HOLD (MEDIUM)

    # STEP 4: DCA disabled
    #   4a. BB squeezing → HOLD (MEDIUM)
    #   4b. No QQE aligned → HOLD (MEDIUM)
    #   4c. Confluence < 10 → HOLD (MEDIUM)
    #   4d. Confirmed opposite pattern → HOLD (HIGH)

    # STEP 5: Zone-based ADD
    #   5a. price in OTE + QQE aligned + RSI oversold → ADD (HIGH)
    #   5b. price in OTE + QQE aligned → ADD (MEDIUM)
    #   5c. RSI oversold but NOT in OTE → HOLD (MEDIUM)

    # STEP 6: Default → HOLD (LOW)

    # STEP 7: Compute adaptive ladder
    # STEP 8: Compute future ADD triggers
    # STEP 9: Build action items


# ── Batch computation ──

async def compute_dca_recommendations(
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compute DCA for all open positions.
    Reuses position_alert_service pattern:
    - Normalize symbols (BTC/USDT:USDT → BTC-USD)
    - Fetch scans concurrently (Semaphore(3))
    - Evaluate each position
    """
```

### 7.2 `backend/routes/portfolio.py` (MODIFY)

Add after `position-alerts` endpoint (~line 854):

```python
# ── Pydantic schemas ──

class DcaEntryLevel(BaseModel):
    entry: str
    trigger: str
    position_size_pct: str
    cumulative_pct: str
    status: str              # filled / pending
    trigger_type: str        # rsi / zone
    rsi_target: int
    level_price: Optional[float] = None

class DcaZone(BaseModel):
    low: float
    high: float
    label: str

class DcaRecommendation(BaseModel):
    symbol: str
    position_side: str
    entry_price: float
    mark_price: float
    pnl: float
    pnl_percent: float
    leverage: float
    recommendation: str     # ADD / HOLD / REDUCE / CLOSE
    reason: str
    confidence: str         # LOW / MEDIUM / HIGH / CRITICAL
    rsi_current: Optional[float] = None
    rsi_entries: List[DcaEntryLevel] = []
    next_entry: Optional[DcaEntryLevel] = None
    dca_zone: Optional[DcaZone] = None
    tp_levels: List[float] = []
    risk_rules: List[str] = []
    future_add_triggers: List[str] = []
    action_items: List[str] = []

class DcaResponse(BaseModel):
    exchange: str
    total_positions: int
    add_count: int
    reduce_count: int
    close_count: int
    hold_count: int
    positions: List[DcaRecommendation]


# ── Endpoint ──

@router.get(
    "/{exchange}/dca",
    response_model=DcaResponse,
    responses={
        404: {"model": PortfolioErrorResponse},
        501: {"model": PortfolioErrorResponse},
    },
)
async def get_dca_recommendations(
    exchange: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DcaResponse:
    """Dynamic DCA recommendations for open positions.

    For every open position, fetches the latest Miraj pair analysis
    and computes: ADD / HOLD / REDUCE / CLOSE with adaptive RSI
    three-entry ladder, OTE zone, TP levels, action items.
    """
    exchange_slug = _require_supported_exchange(exchange)
    positions = await _load_positions(session, current_user.id, exchange_slug)
    if not positions:
        return DcaResponse(
            exchange=exchange_slug, total_positions=0,
            add_count=0, reduce_count=0, close_count=0, hold_count=0,
            positions=[],
        )
    position_dicts = [_serialise_position(p) for p in positions]
    from backend.services.dca_service import compute_dca_recommendations
    dca_items = await compute_dca_recommendations(position_dicts)
    add_count = sum(1 for i in dca_items if i["recommendation"] == "ADD")
    reduce_count = sum(1 for i in dca_items if i["recommendation"] == "REDUCE")
    close_count = sum(1 for i in dca_items if i["recommendation"] == "CLOSE")
    hold_count = sum(1 for i in dca_items if i["recommendation"] == "HOLD")
    return DcaResponse(
        exchange=exchange_slug,
        total_positions=len(dca_items),
        add_count=add_count,
        reduce_count=reduce_count,
        close_count=close_count,
        hold_count=hold_count,
        positions=[DcaRecommendation(**item) for item in dca_items],
    )
```

### 7.3 `frontend/components/portfolio/dca-panel.tsx` (CREATE)

Pattern: follows `position-alerts-panel.tsx`.

```
Component: DcaPanel (client component)
Fetches: GET /api/v1/portfolio/{exchange}/dca (every 5 min)
Props: { token, exchange }

Render states:
  - loading: "Computing DCA recommendations from pair analysis…"
  - error: "Failed to load DCA recommendations: {error}"
  - no positions: null (don't render)
  - data: collapsible panel with cards

Panel header:
  📊 Dynamic DCA   [2 ADD] [1 REDUCE] [0 CLOSE] [0 HOLD]   ↻ Show/Hide
  Miraj three-entry system + pair analysis

Cards sorted by urgency: CLOSE → REDUCE → ADD → HOLD

Each DcaCard renders:
  Row 1: Symbol | Side badge (LONG/SHORT) | Leverage | Recommendation badge
  Row 2: Entry | Mark | PnL + PnL%
  Row 3: Reason text (full explanation)
  Row 4: RSI badge | Confidence badge | OTE zone badge
  Row 5: RSI Three-Entry table (filled ● / pending ○, with cumulative %)
  Row 6: Next entry highlight ("Next: Entry 2 — deploy 20% at RSI 24")
  Row 7: TP levels ("TP1: $77.72 (HERE)  TP2: $83.30")
  Row 8: Action items ("→ Close 6 of 12 contracts", "→ Move stop to $74.91")
  Row 9: Future ADD triggers ("If 4H QQE turns GREEN + price → $72, re-add")
  Row 10: Risk rules (compact, max 3)

Recommendation badge colors:
  ADD = green (ArrowUp icon)
  HOLD = sky blue (Layers icon)
  REDUCE = amber (Minus icon)
  CLOSE = red (X icon)
```

### 7.4 `frontend/components/portfolio/portfolio-dashboard.tsx` (MODIFY)

```tsx
// Add import (line ~22)
import { DcaPanel } from "@/components/portfolio/dca-panel";

// In render, after PositionAlertsPanel, before Tabs (~line 491):
<PositionAlertsPanel token={token} exchange={exchange} />

{/* Dynamic DCA — per-position recommendations */}
<DcaPanel token={token} exchange={exchange} />

<Tabs defaultValue="balances" className="w-full">
```

### 7.5 `frontend/lib/types.ts` (MODIFY)

Add after existing PositionAlert types (~line 528):

```typescript
export interface DcaEntryLevel {
  entry: string;
  trigger: string;
  position_size_pct: string;
  cumulative_pct: string;
  status: "filled" | "pending";
  trigger_type: "rsi" | "zone";
  rsi_target: number;
  level_price: number | null;
}

export interface DcaZone {
  low: number;
  high: number;
  label: string;
}

export interface DcaRecommendation {
  symbol: string;
  position_side: string;
  entry_price: number;
  mark_price: number;
  pnl: number;
  pnl_percent: number;
  leverage: number;
  recommendation: "ADD" | "HOLD" | "REDUCE" | "CLOSE";
  reason: string;
  confidence: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  rsi_current: number | null;
  rsi_entries: DcaEntryLevel[];
  next_entry: DcaEntryLevel | null;
  dca_zone: DcaZone | null;
  tp_levels: number[];
  risk_rules: string[];
  future_add_triggers: string[];
  action_items: string[];
}

export interface DcaResponse {
  exchange: string;
  total_positions: number;
  add_count: number;
  reduce_count: number;
  close_count: number;
  hold_count: number;
  positions: DcaRecommendation[];
}
```

### 7.6 `mirai_core/trade_plan.py` (MODIFY)

In `generate_trade_plan()`, add explicit TP price fields to the return dict:

```python
# In the return dict (after take_profit_targets), add:
    # Explicit TP prices for DCA engine
    "tp1_price": tp1,
    "tp2_price": tp2,
```

### 7.7 `backend/services/analysis_service.py` (MODIFY)

In `_build_flat_trade_plan()`, expose TP prices:

```python
def _build_flat_trade_plan(tp: dict[str, Any]) -> dict[str, Any]:
    # ... existing code ...

    # NEW: TP prices for DCA engine
    flat["tp1_price"] = tp.get("tp1_price")
    flat["tp2_price"] = tp.get("tp2_price")

    return flat
```

### 7.8 `backend/obsidian.py` (MODIFY)

After the Trade Plan section (~line 342), add DCA export:

```python
# ── RSI Three-Entry System ──
if tp.get("rsi_entry_system"):
    rsi_sys = tp["rsi_entry_system"]
    lines.append("### RSI Three-Entry System")
    lines.append("")
    lines.append(f"- **Current RSI**: {rsi_sys.get('current_rsi', 'N/A')}")
    for entry in rsi_sys.get("entries", []):
        lines.append(f"- {entry['entry']}: {entry['trigger']} → {entry['position_size']}")
    lines.append("")

# ── DCA Strategy ──
if tp.get("dca_strategy"):
    lines.append("### DCA Strategy")
    lines.append("")
    for item in tp["dca_strategy"]:
        lines.append(f"- {item}")
    lines.append("")

# ── Risk Management ──
if tp.get("risk_management"):
    lines.append("### Risk Management")
    lines.append("")
    for rule in tp["risk_management"]:
        lines.append(f"- {rule}")
    lines.append("")
```

---

## 8. COMPARISON: EXISTING vs NEW

| Feature | Position Alerts (existing) | Dynamic DCA (new) |
|---------|---------------------------|---------------------|
| Purpose | Warn when signals conflict | Suggest specific actions |
| Output | ALERT type + severity | ADD/HOLD/REDUCE/CLOSE + entry ladder |
| RSI tracking | None | Adaptive three-entry system |
| OTE zone | Not checked | Primary DCA trigger |
| TP levels | Not checked | Auto-reduce at TP1/TP2 |
| PnL check | Not checked | Withdraw initial at +100% |
| Budget tracking | No | Enforces max position size |
| Future triggers | No | "What needs to happen for ADD" |
| Action items | Generic ("consider reducing") | Specific ("close 6 of 12 contracts") |
| Adaptive entry | No | Adjusts to user's actual RSI at entry |
| BMSB check | No | Below band = REDUCE for longs |

The two panels complement each other: Position Alerts = "something is wrong", Dynamic DCA = "here's exactly what to do about it."

---

## 9. LIVE TEST CASE (verified 2026-07-08)

Position data from ta.munafaplus.pk/portfolio:

| Field | Value |
|-------|-------|
| Symbol | SOLUSDT:USDT |
| Side | LONG |
| Size | 12 contracts |
| Entry Price | $77.17 |
| Mark Price | $77.57 |
| PnL | +$0.49 (+5.31%) |
| Leverage | 10x |
| Liquidation Price | $11.12 (85.65% away) |
| Margin | $9.26 |

Scan data from ta.munafaplus.pk/analysis/SOL-USD:

| Signal | Value | Alignment |
|--------|-------|-----------|
| Confluence | 25/30 (83%) | STRONG |
| Scan Direction | LONG | ALIGNED |
| TP1 | $77.72 1:1 R:R | PRICE IS HERE |
| TP2 | $83.30 1:2 R:R | — |
| QQE Daily | GREEN (Normal) | ALIGNED |
| QQE 4H | RED-STRONG | CONFLICTS |
| QQE 1H | RED-STRONG | CONFLICTS |
| Structure Weekly | HH (bullish) | ALIGNED |
| Structure Daily | HH (bullish) | ALIGNED |
| Structure 4H | HH (bullish) | ALIGNED |
| Structure 15m | LH (bearish) | Minor conflict |
| Chart Pattern | Double Top (confirmed) | CONFLICTS |
| BMSB | BELOW BAND ($82/$87) | BEAR REGIME |
| OTE Entry Zone | $72.14 (low) | Price ABOVE zone |

**Expected DCA output:**

```
Recommendation: REDUCE
Confidence: HIGH
Reason: TP1 hit ($77.72). QQE 4H+1H flipped RED-STRONG.
        Double Top confirmed. Below BMSB (bear regime).
        Reduce 50% — take partial profits.

RSI Three-Entry (Adaptive):
  ● Entry 1  RSI 30    20%  FILLED
  ● Entry 2  RSI 24    20%  PENDING (next if price pulls back)
  ○ Entry 3  RSI 16    60%  PENDING

OTE Zone: $66.56 - $72.14
TP1: $77.72 (AT TARGET)  TP2: $83.30

Action Items:
  → Close 6 of 12 contracts at ~$77.57 (TP1 hit)
  → Move stop to $74.91 (last 4H swing low)
  → If 4H QQE turns GREEN + price returns to $72, re-enter 20%

Risk Rules:
  • Risk 0.5-1% per trade
  • When doubled → withdraw initial capital
  • Wait for candle CLOSE confirmation

Future ADD Triggers:
  - 4H QQE must turn GREEN
  - Price must pull back to OTE zone ($66.56-$72.14)
  - RSI must drop below 40
  - Double Top pattern must invalidate (price breaks above $83.90)
```

---

## 10. IMPLEMENTATION ORDER

```
Phase 1: Backend Core (1-2h)
  ☐ 1. Create backend/services/dca_service.py
  ☐ 2. Add endpoint + schemas to backend/routes/portfolio.py
  ☐ 3. Add tp1_price/tp2_price to mirai_core/trade_plan.py
  ☐ 4. Update _build_flat_trade_plan in analysis_service.py
  ☐ 5. Test: curl GET /api/v1/portfolio/mexc/dca

Phase 2: Frontend (1-2h)
  ☐ 6. Add types to frontend/lib/types.ts
  ☐ 7. Create frontend/components/portfolio/dca-panel.tsx
  ☐ 8. Wire into portfolio-dashboard.tsx
  ☐ 9. Test UI at ta.munafaplus.pk/portfolio

Phase 3: Polish (30min)
  ☐ 10. Add DCA export to backend/obsidian.py
  ☐ 11. Verify against live SOL position
  ☐ 12. Commit + push
```

---

## 11. MIRAJ RULES ENCODED

| Rule | Source | Implementation |
|------|--------|---------------|
| RSI three-entry: 20%@30, 20%@24, 60%@16-18 | Mirage Secret Scalping Strategy | `compute_adaptive_entries()` |
| DCA only into valid zones (confluence >= 10) | Miraj Methodology | Step 4 (DCA disabled) |
| QQE must confirm before adding | Module 3 | Step 5 (QQE aligned check) |
| BB squeezing = don't trade | Module 7 | Step 4a |
| When investment doubles, withdraw initial | Module 2 | Step 2a |
| Wait for candle CLOSE confirmation | Module 4+5 | Risk rules |
| Below BMSB = avoid longs | Module 9 | Step 1c |
| OTE zone 0.62-0.705 = optimal entry | OTE Model notes | Step 5 (zone-based ADD) |
| Cash is a position | All modules | HOLD as default |
| Don't overtrade | Module 2 | No ADD when disabled |
| Risk 0.5-1% max per trade | Module 2 | Budget enforcement |
| HTF first, then LTF | Module 3 | Weekly/Daily structure checked first |
| Volume must confirm breakouts | Module 7 | (future: volume in ADD check) |
| Touch points: 5+ = likely to break | Module 4+5 | (future: touch point scoring) |

---

## 12. EDGE CASES

| Scenario | Handling |
|----------|---------|
| RSI never hits 24 or 16 | Zone-based ADD: if price is in OTE + QQE aligned, ADD regardless of RSI level |
| User entered at RSI 18 (deepest oversold) | All entries FILLED, no more DCA, HOLD only |
| User entered at RSI 45 (breakout) | Ladder shifts: Entry 1 becomes zone-based, Entries 2-3 stay RSI-based |
| Full position deployed (100% budget) | No ADD possible, only HOLD/REDUCE/CLOSE |
| Scan fails (network error) | Return HOLD with reason "Scan unavailable" |
| No positions open | Don't render panel (return null) |
| Position in profit but QQE flips | REDUCE — momentum is dying despite profit |
| Multiple positions same symbol | Evaluate each independently |
| No OTE zone in scan | Use demand zone from SMC; if none, HOLD |
| Liquidation price is 0 or null | Skip liq distance check, continue evaluation |
| Mark price is 0 or null | Use entry_price as fallback |

---

## 13. API CONTRACT

### Request
```
GET /api/v1/portfolio/{exchange}/dca
Authorization: Bearer <jwt>
```

### Response (200)
```json
{
  "exchange": "mexc",
  "total_positions": 1,
  "add_count": 0,
  "reduce_count": 1,
  "close_count": 0,
  "hold_count": 0,
  "positions": [
    {
      "symbol": "SOLUSDT:USDT",
      "position_side": "LONG",
      "entry_price": 77.17,
      "mark_price": 77.57,
      "pnl": 0.49,
      "pnl_percent": 5.31,
      "leverage": 10,
      "recommendation": "REDUCE",
      "reason": "TP1 hit ($77.72). QQE 4H+1H RED-STRONG...",
      "confidence": "HIGH",
      "rsi_current": 55.3,
      "rsi_entries": [
        {
          "entry": "Entry 1",
          "trigger": "RSI hits 30",
          "position_size_pct": "20%",
          "cumulative_pct": "20%",
          "status": "filled",
          "trigger_type": "rsi",
          "rsi_target": 30,
          "level_price": null
        },
        {
          "entry": "Entry 2",
          "trigger": "RSI hits 24",
          "position_size_pct": "20%",
          "cumulative_pct": "40%",
          "status": "pending",
          "trigger_type": "rsi",
          "rsi_target": 24,
          "level_price": null
        },
        {
          "entry": "Entry 3",
          "trigger": "RSI hits 16",
          "position_size_pct": "60%",
          "cumulative_pct": "100%",
          "status": "pending",
          "trigger_type": "rsi",
          "rsi_target": 16,
          "level_price": null
        }
      ],
      "next_entry": {
        "entry": "Entry 2",
        "trigger": "RSI hits 24",
        "position_size_pct": "20%",
        "cumulative_pct": "40%",
        "status": "pending",
        "trigger_type": "rsi",
        "rsi_target": 24,
        "level_price": null
      },
      "dca_zone": {
        "low": 66.56,
        "high": 72.14,
        "label": "OTE 66.56-72.14"
      },
      "tp_levels": [77.72, 83.30],
      "risk_rules": [
        "Risk 0.5-1% of portfolio per trade",
        "When investment DOUBLES → withdraw initial capital",
        "Use DCA — split entries, don't enter full position at once",
        "Wait for candle CLOSE confirmation"
      ],
      "future_add_triggers": [
        "4H QQE must turn GREEN",
        "Price must pull back to OTE zone ($66.56-$72.14)",
        "RSI must drop below 40",
        "Double Top pattern must invalidate"
      ],
      "action_items": [
        "Close 6 of 12 contracts at ~$77.57 (TP1 hit)",
        "Move stop to $74.91 (last 4H swing low)",
        "If 4H QQE turns GREEN + price returns to $72, re-enter 20%"
      ]
    }
  ]
}
```

### Error responses
- 404: Unsupported exchange
- 501: ccxt not installed
- 401: Not authenticated
