---
title: Webhooks
doc_type: product
product: platform
effective_date: 2026-01-20
version: "3.9"
---

# Webhooks

## Delivery guarantees

Webhooks are delivered at least once. Your endpoint must be idempotent — use the
`event_id` field to deduplicate. Delivery is not ordered.

## Signature verification

Every request carries an `X-Signature` header: an HMAC-SHA256 of the raw request
body, keyed by your webhook secret.

```python
import hmac, hashlib
expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, request.headers["X-Signature"]):
    raise ValueError("bad signature")
```

Verify against the **raw** body. Parsing the JSON and re-serializing it changes the
bytes and the signature will not match. A failed verification on our side returns
error code `E1004` in the delivery log; a payload above 1 MB is rejected as `E1005`.

## Retries

Failed deliveries retry 8 times with exponential backoff over roughly 24 hours.
After the final failure the endpoint is disabled and an email is sent to the
account owner.
