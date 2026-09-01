# Signed signal webhooks

Miraj can deliver an already-confirmed trade alert to a user-controlled HTTPS
endpoint. Webhooks are another alert channel: they use the same per-pair enable,
threshold, notification-channel, and cooldown rules as Telegram and
email. A high score alone is not enough; the scan's trade plan must contain the
literal `"trade_decision": true` confirmation.

Webhooks do not place orders. They contain a small normalized signal payload and
exclude raw analysis data, account data, exchange credentials, and API keys.

## Configure a channel

Create a signing secret with at least 32 characters and save the channel through
the authenticated Settings API:

```http
POST /api/v1/settings/channels
Authorization: Bearer <token>
Content-Type: application/json

{
  "channel_type": "webhook",
  "config": {
    "webhook_url": "https://automation.example.com/hooks/miraj",
    "signing_secret": "replace-with-a-random-secret-of-32-or-more-characters"
  },
  "enabled": true
}
```

Only public HTTPS URLs on the default TLS port are accepted. Miraj checks the
resolved destination again before every delivery, rejects multicast and special
transition ranges, pins the connection to those validated IP addresses, does
not follow redirects, and enforces a hard delivery deadline without buffering
the receiver's response body.
The Settings API never returns `signing_secret`; it returns
`"has_signing_secret": true` instead.

Confirmed signals are committed to a durable outbox before network I/O. The
dispatcher claims rows with a lease, retries transient failures with bounded
backoff, and reuses the same delivery ID for the same user, channel, and source
scan instance. This keeps scan/database transactions independent of slow
receivers and gives receivers a stable idempotency key after lost responses.
Delivery normally begins on the next one-minute dispatcher tick.

Dispatch is fair across users, runs with bounded concurrency, and stops at a
fixed per-job deadline. Pending rows are tied to the URL and signing-secret
generation that created them; rotating channel configuration cancels older
queued rows instead of redirecting them. Terminal outbox payloads are retained
for 30 days and removed by a daily cleanup job.

This contract is emitted by the confirmed scan-alert pipeline. Price-alert and
real-time lifecycle outboxes continue to use their explicitly supported channel
types and do not turn those events into `signal.created` webhooks.

## Delivery contract

Each request includes:

```text
X-Miraj-Event: signal.created
X-Miraj-Delivery: <UUID>
X-Miraj-Timestamp: <Unix time in milliseconds>
X-Miraj-Signature: <hex HMAC-SHA256>
Content-Type: application/json
```

Example body:

```json
{
  "event": "signal.created",
  "dateKey": "2026-08-09",
  "sentAt": "2026-08-09T07:30:00Z",
  "data": {
    "signal": {
      "symbol": "BTCUSDT",
      "score": 83.5,
      "direction": "LONG",
      "tradeDecision": "confirmed",
      "entry": 65000.0,
      "stopLoss": 64000.0,
      "target": 68000.0,
      "rationale": "Confirmed multi-timeframe setup"
    }
  }
}
```

Optional price and rationale fields are omitted when unavailable.

## Verify a delivery

Reject timestamps older than five minutes, then compute HMAC-SHA256 over the
exact raw request body prefixed by the timestamp and a period:

```python
import hashlib
import hmac

signed = timestamp.encode("utf-8") + b"." + raw_body
expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
valid = hmac.compare_digest(signature, expected)
```

Store `X-Miraj-Delivery` before starting downstream work and ignore duplicates.
Miraj intentionally reuses this ID when retrying the same logical signal.
