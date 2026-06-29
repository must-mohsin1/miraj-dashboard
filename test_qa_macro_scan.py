"""QA test: Macro API and Scan API endpoints"""
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
print("QA: Macro & Scan API Tests")
print("=" * 60)

# Get auth token first
out, _ = curl("POST", "/api/v1/auth/login", data={
    "username": "qauser", "password": "QaTest123!"
})
d = json_of(out)
token = d.get("access_token", "") if d else ""

# ──────────────────────────────────────────────
# Macro API
# ──────────────────────────────────────────────
print("\n--- GET /api/v1/macro ---")
out, _ = curl("GET", "/api/v1/macro", timeout=30)
macro = json_of(out)

MACRO_FIELDS = ["btc_dominance", "usdt_dominance", "dxy", "fear_greed_index", 
                "fear_greed_label", "binance_ls_ratio", "regime"]
for f in MACRO_FIELDS:
    present = macro and f in macro
    val = macro.get(f) if macro else None
    check(f"Macro field '{f}' present", present, f"got fields: {list(macro.keys()) if macro else 'None'}")

check("Macro - numeric values for btc_dominance", 
      macro and isinstance(macro.get("btc_dominance"), (int, float)),
      f"got: {macro}")
check("Macro - numeric values for usdt_dominance",
      macro and isinstance(macro.get("usdt_dominance"), (int, float)),
      f"got: {macro}")
check("Macro - numeric values for fear_greed_index",
      macro and isinstance(macro.get("fear_greed_index"), (int, float)),
      f"got: {macro}")
check("Macro - numeric values for binance_ls_ratio",
      macro and isinstance(macro.get("binance_ls_ratio"), (int, float)),
      f"got: {macro}")
check("Macro - regime is a string",
      macro and isinstance(macro.get("regime"), str) and len(macro.get("regime","")) > 0,
      f"regime: {macro.get('regime') if macro else 'N/A'}")
check("Macro - fear_greed_label is a string",
      macro and isinstance(macro.get("fear_greed_label"), str),
      f"label: {macro.get('fear_greed_label') if macro else 'N/A'}")

# ──────────────────────────────────────────────
# Scan API
# ──────────────────────────────────────────────
print("\n--- POST /api/v1/scan/BTC-USD ---")
out, _ = curl("POST", f"/api/v1/scan/BTC-USD", timeout=120)
scan = json_of(out)

check("Scan response is dict", isinstance(scan, dict), f"got: {out[:200]}")
check("Scan - symbol field", scan and scan.get("symbol") == "BTC-USD",
      f"symbol: {scan.get('symbol') if scan else 'N/A'}")
check("Scan - confluence_score present (0-30)",
      scan and isinstance(scan.get("confluence_score"), (int, float)) and 0 <= scan["confluence_score"] <= 30,
      f"score: {scan.get('confluence_score') if scan else 'N/A'}")
check("Scan - trade_plan present with keys",
      scan and isinstance(scan.get("trade_plan"), dict) and len(scan["trade_plan"]) > 0,
      f"keys: {list(scan.get('trade_plan', {}).keys()) if scan else 'N/A'}")
check("Scan - score_breakdown present",
      scan and isinstance(scan.get("score_breakdown"), dict),
      f"keys: {list(scan.get('score_breakdown', {}).keys()) if scan else 'N/A'}")
check("Scan - stale flag present",
      scan and "stale" in scan,
      f"stale: {scan.get('stale') if scan else 'N/A'}")

# Check trade_plan has expected fields
tp = scan.get("trade_plan", {}) if scan else {}
check("Trade plan - direction", "direction" in tp, f"keys: {list(tp.keys())}")
check("Trade plan - entry", "entry" in tp, f"keys: {list(tp.keys())}")
check("Trade plan - stop_loss", "stop_loss" in tp, f"keys: {list(tp.keys())}")

print()
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
sys.exit(failed)
