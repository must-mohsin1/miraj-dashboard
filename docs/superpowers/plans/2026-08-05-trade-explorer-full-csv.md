# Trade Explorer full filtered CSV export

**Status:** Implemented  
**Date:** 2026-08-05  
**Branch:** `feat/trade-explorer-full-csv`

## Scope

1. `GET /api/v1/analytics/{exchange}/trade-explorer/export`  
   - Same filter contract as Trade Explorer (no pagination)  
   - Cap **10_000** rows; headers: `X-Export-Row-Count`, `X-Export-Total-Matched`, `X-Export-Truncated`  
2. UI: **Export CSV (all filtered)** next to page export  
3. Keep page-local CSV for offline/quick use  

## Out of scope

- Win/loss result filter  
- Async job / email delivery for huge histories  
