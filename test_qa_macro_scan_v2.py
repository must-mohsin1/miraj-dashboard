"""QA test: Macro API and Scan API endpoints — v2 with correct field access"""
import json, subprocess, sys

BASE = "http://localhost:8000"

def curl(method, path, headers=None, data=None, timeout=30):
    cmd = ["curl", "-s", "-X", method, f"{BASE}{path}"]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr

def json_of(text):
    try:
        return json.loads(text.strip())
    except:
        return None

passed = 0
failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        failed += 1

print("=" * 60)
print("QA: Macro & Scan API Tests (v2)")
print("=" * 60)

# Register a user first
out, _ = curl("POST", "/api/v1/auth/register", data={
    "username": "apiuser", "email": "api@test.com", "password": "ApiTest123!"
})
# Login
out, _ = curl("POST", "/api/v1/auth/login", data={
    "username": "apiuser", "password": "ApiTest123!"
})
d = json_of(out)
token = d.get("access_token", "") if d else ""
print(f"Auth token obtained: {bool(token)}")

# ──────────────────────────────────────────────
# Macro API
# ──────────────────────────────────────────────
print("\n--- GET /api/v1/macro ---")
out, _ = curl("GET", "/api/v1/macro", timeout=30)
macro = json_of(out)

# The macro API wraps data in a "data" envelope
macro_data = macro.get("data", {}) if macro else {}
check("Macro response is dict", isinstance(macro, dict), f"type: {type(macro)}")
check("Macro has 'data' envelope", "data" in macro, f"keys: {list(macro.keys()) if macro else 'None'}")
check("Macro has 'stale' flag", "stale" in macro, f"got: {macro}")
check("Macro has 'cached_at' timestamp", "cached_at" in macro, f"got: {macro}")

MACRO_FIELDS = ["btc_dominance", "usdt_dominance", "dxy", "fear_greed_index", 
                "fear_greed_label", "binance_ls_ratio", "regime"]
for f in MACRO_FIELDS:
    present = f in macro_data
    check(f"Macro field '{f}' present", present, f"data keys: {list(macro_data.keys()) if macro_data else 'None'}")

check("btc_dominance is numeric", 
      isinstance(macro_data.get("btc_dominance"), (int, float)),
      f"got: {macro_data.get('btc_dominance')}")
check("usdt_dominance is numeric",
      isinstance(macro_data.get("usdt_dominance"), (int, float)),
      f"got: {macro_data.get('usdt_dominance')}")
check("fear_greed_index is numeric",
      isinstance(macro_data.get("fear_greed_index"), (int, float)),
      f"got: {macro_data.get('fear_greed_index')}")
check("binance_ls_ratio is numeric",
      isinstance(macro_data.get("binance_ls_ratio"), (int, float)),
      f"got: {macro_data.get('binance_ls_ratio')}")
check("regime is a non-empty string",
      isinstance(macro_data.get("regime"), str) and len(macro_data["regime"]) > 0,
      f"regime: {macro_data.get('regime')}")
check("fear_greed_label is a string",
      isinstance(macro_data.get("fear_greed_label"), str),
      f"label: {macro_data.get('fear_greed_label')}")
check("dxy gracefully degrades (null with error)",
      macro_data.get("dxy") is None and len(macro.get("errors", [])) > 0,
      f"dxy: {macro_data.get('dxy')}, errors: {macro.get('errors', [])}")

# ──────────────────────────────────────────────
# Scan API
# ──────────────────────────────────────────────
print("\n--- POST /api/v1/scan/BTC-USD ---")
out, _ = curl("POST", "/api/v1/scan/BTC-USD", timeout=120)
scan = json_of(out)

print(f"Scan response: {out[:300] if out else 'EMPTY'}")

check("Scan response received", scan is not None, f"empty response")
if scan:
    check("Scan - symbol field", scan.get("symbol") == "BTC-USD",
          f"symbol: {scan.get('symbol')}")
    check("Scan - confluence_score (0-30)",
          isinstance(scan.get("confluence_score"), (int, float)) and 0 <= scan["confluence_score"] <= 30,
          f"score: {scan.get('confluence_score')}")
    check("Scan - trade_plan present",
          isinstance(scan.get("trade_plan"), dict) and len(scan["trade_plan"]) > 0,
          f"tp keys: {list(scan.get('trade_plan', {}).keys())}")
    check("Scan - score_breakdown present",
          isinstance(scan.get("score_breakdown"), dict),
          f"sb keys: {list(scan.get('score_breakdown', {}).keys())}")
    check("Scan - stale flag present", "stale" in scan, f"stale: {scan.get('stale')}")

    # Trade plan details
    tp = scan.get("trade_plan", {})
    check("Trade plan - direction", "direction" in tp, f"keys: {list(tp.keys())}")
    check("Trade plan - entry price", "entry" in tp or "entry_zone" in tp,
          f"keys: {list(tp.keys())}")
    check("Trade plan - stop_loss", "stop_loss" in tp, f"keys: {list(tp.keys())}")

print()
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
sys.exit(failed)
