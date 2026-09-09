---
title: API Rate Limits
doc_type: product
product: platform
effective_date: 2026-03-01
version: "4.2"
---

# API Rate Limits

## Tiers

Every API key is bound to the rate limit of its plan. Limits are enforced per key,
not per organization.

| Plan       | Requests/minute | Burst | Concurrent connections |
|------------|-----------------|-------|------------------------|
| Free       | 60              | 90    | 4                      |
| Pro        | 600             | 900   | 32                     |
| Enterprise | Contractual     | —     | Contractual            |

## What happens at the limit

Exceeding your limit returns HTTP 429 with a `Retry-After` header giving the number
of seconds until the window resets. The response body carries error code `E1004`.

```json
{"error": {"code": "E1004", "message": "rate limit exceeded", "retry_after": 12}}
```

Clients should back off exponentially. Retrying immediately on a 429 counts against
the next window and will extend the lockout.

## Raising a limit

Pro customers can request a temporary increase of up to 3x for a maximum of 14 days
through support. Permanent increases require moving to Enterprise.
