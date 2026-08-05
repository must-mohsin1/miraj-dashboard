# Trade Explorer detail — orders + pre-entry scan

**Status:** Implemented  
**Date:** 2026-08-05  
**Branch:** `feat/trade-detail-fills-scan`

## Scope

1. `GET /api/v1/analytics/{exchange}/trade-explorer/{position_id}`
   - Position row (same as explorer item)
   - Orders matched by normalised symbol + open/close time window (±2m)
   - Nearest pre-entry Miraj scan + `/analysis/{scan_symbol}` link
   - Linked journal entries
2. Drawer lazy-loads detail when opened (requires JWT)
3. Honest copy: orders are not FK-linked to exchange position id
4. Symbol normaliser: `BTC_USDT` → `BTC-USD` for scan join

## Out of scope

- Full-history CSV export  
- True fill stream if separate from OrderHistory  
- Auth browser e2e (Keychain blocked this session)
