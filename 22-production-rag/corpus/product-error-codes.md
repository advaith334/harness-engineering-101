---
title: Error Code Reference
doc_type: product
product: platform
effective_date: 2026-06-30
version: "4.4"
---

# Error Code Reference

## Authentication and request errors

| Code  | Meaning | Action |
|-------|---------|--------|
| E1001 | Malformed API key | Check for whitespace or truncation |
| E1002 | Revoked or expired API key | Rotate to a current key |
| E1004 | Rate limit exceeded, or webhook signature failed | Back off; verify against the raw body |
| E1005 | Payload exceeded 1 MB | Split the request |

## Upstream errors

| Code  | Meaning | Action |
|-------|---------|--------|
| E2001 | Destination timed out | Retry with backoff; check the destination's health |
| E2002 | Destination returned a non-2xx | Inspect the delivery log |

`E1004` is deliberately overloaded across rate limiting and webhook signature
failure for historical reasons. Disambiguate using the `source` field on the error
object rather than the code alone.
