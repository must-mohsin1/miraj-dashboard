# DCA validation QA fixture

This fixture seeds deterministic, offline data for the DCA Shadow-Mode Validation approval slice. It is designed for local QA databases only: it reads `backend/tests/fixtures/dca_validation_expected.json`, creates one authenticated test user, stores scan-history rows in `Analysis.result`, adds portfolio position context, and embeds shadow-history examples that explicitly record `live_order_placed: false`.

## Safety properties

- No live exchange clients are imported.
- No API keys are read or required.
- The script writes only to the SQLite database path passed with `--db` or `DATABASE_URL`.
- The default seed is idempotent for the fixture user because `--reset` is enabled by default.
- The rollback is `--reset-only` for a shared local DB, or deleting the scratch DB file.

## Seed a scratch QA database

From the repository root:

```bash
python scripts/seed_dca_validation_fixture.py \
  --init-schema \
  --db /tmp/miraj-dca-validation-qa.db
```

Expected headline output:

- `username`: `qa_dca_validation`
- `email`: `qa-dca-validation@example.test`
- `password`: `qa-dca-validation-password`
- `analyses`: `21`
- `open_positions`: `1`
- `position_history`: `1`
- `portfolio_trades`: `6`
- `shadow_decisions`: `21`
- `fixtures`: `long_btc_closed_three_entries`, `short_eth_open_three_entries`
- `edge_cases`: all six skip-reason fixtures from the expected JSON

The seeded data is local-only. Use the printed username/password to sign in through the normal auth flow when pointing the app at the scratch DB.

## Seed the default development database

If your backend uses the default local DB path:

```bash
python scripts/seed_dca_validation_fixture.py --init-schema
```

If your backend is configured with `DATABASE_URL`:

```bash
DATABASE_URL=/path/to/crypto_analysis.db python scripts/seed_dca_validation_fixture.py --init-schema
```

To use a non-default expected-values file, pass it explicitly:

```bash
python scripts/seed_dca_validation_fixture.py \
  --db /tmp/miraj-dca-validation-qa.db \
  --expected backend/tests/fixtures/dca_validation_expected.json \
  --init-schema
```

## Reset fixture data

Remove only the deterministic fixture user and all rows created for that user:

```bash
python scripts/seed_dca_validation_fixture.py \
  --db /tmp/miraj-dca-validation-qa.db \
  --reset-only
```

The normal seed command also resets the fixture user first. If QA needs to preserve a seeded fixture user for investigation, pass a different `--username` and `--email` rather than disabling reset.

## Verify against expected values

The fixture source of truth is:

```text
backend/tests/fixtures/dca_validation_expected.json
```

After seeding, verify that the local DB contains the expected headline counts and metric anchors:

```bash
python - <<'PY'
import json
import sqlite3

DB = "/tmp/miraj-dca-validation-qa.db"
EXPECTED = "backend/tests/fixtures/dca_validation_expected.json"

with open(EXPECTED, "r", encoding="utf-8") as handle:
    expected = json.load(handle)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
user = conn.execute(
    "select id, username, email from users where username = ?",
    ("qa_dca_validation",),
).fetchone()
assert user, "fixture user missing"

counts = {
    "analyses": conn.execute("select count(*) from analyses where user_id = ?", (user["id"],)).fetchone()[0],
    "open_positions": conn.execute("select count(*) from portfolio_positions where user_id = ?", (user["id"],)).fetchone()[0],
    "position_history": conn.execute("select count(*) from position_history where user_id = ?", (user["id"],)).fetchone()[0],
    "portfolio_trades": conn.execute("select count(*) from portfolio_trades where user_id = ?", (user["id"],)).fetchone()[0],
}
assert counts == {
    "analyses": 21,
    "open_positions": 1,
    "position_history": 1,
    "portfolio_trades": 6,
}, counts

results = [
    json.loads(row["result"])
    for row in conn.execute(
        "select result from analyses where user_id = ? and analysis_type like 'dca_validation_fixture%'",
        (user["id"],),
    )
]
shadow_decisions = sum(len(result.get("shadow_history", [])) for result in results)
assert shadow_decisions == 21, shadow_decisions
assert all(
    decision.get("live_order_placed") is False
    for result in results
    for decision in result.get("shadow_history", [])
)

long_expected = next(item for item in expected["fixtures"] if item["id"] == "long_btc_closed_three_entries")
short_expected = next(item for item in expected["fixtures"] if item["id"] == "short_eth_open_three_entries")

closed = conn.execute(
    "select pnl from position_history where user_id = ? and symbol = ?",
    (user["id"], long_expected["symbol"]),
).fetchone()
assert round(closed["pnl"], 2) == long_expected["expected_metrics"]["net_pnl"]

open_pos = conn.execute(
    "select pnl from portfolio_positions where user_id = ? and symbol = ?",
    (user["id"], short_expected["symbol"]),
).fetchone()
assert round(open_pos["pnl"], 2) == short_expected["expected_metrics"]["net_open_pnl"]

skip_reasons = sorted({
    json.loads(row["result"])["dca_validation"]["edge_expected"]["skip_reason"]
    for row in conn.execute(
        "select result from analyses where user_id = ? and analysis_type = 'dca_validation_fixture_edge_case'",
        (user["id"],),
    )
    if json.loads(row["result"])["dca_validation"].get("edge_expected")
})
assert skip_reasons == sorted(expected["expected_skip_reasons"]), skip_reasons

print({"user": dict(user), "counts": counts, "shadow_decisions": shadow_decisions, "skip_reasons": skip_reasons})
PY
```

Expected metric anchors from `backend/tests/fixtures/dca_validation_expected.json`:

| Fixture | Seeded table | Headline metric |
| --- | --- | --- |
| `long_btc_closed_three_entries` | `position_history` | `pnl = 3019.42` |
| `short_eth_open_three_entries` | `portfolio_positions` | `pnl = 694.12` |
| all edge cases | `analyses.result.dca_validation.edge_expected.skip_reason` | `insufficient_history`, `missing_rsi`, `missing_mark_price`, `malformed_scan_result`, `unsupported_direction`, `missing_position_context` |

## What the script creates

For the authenticated QA user, the script creates:

- `Analysis` rows for every deterministic scan and edge-case scan. Each row stores the original scan values, fill assumptions, position context, expected metrics or skip reason, and one shadow-history entry in `result` JSON.
- `PortfolioPosition` for the open short ETH fixture.
- `PositionHistory` for the closed long BTC fixture.
- `PortfolioTrade` rows for all six deterministic simulated DCA fills.

No `ExchangeKey` rows are created, so QA can verify the validation path without real API credentials.
