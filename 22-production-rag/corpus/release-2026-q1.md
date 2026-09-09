---
title: Release Notes Q1 2026
doc_type: release_notes
product: platform
effective_date: 2026-03-31
version: "2026.Q1"
---

# Release Notes — Q1 2026

## Added

- Bulk export endpoint, Pro and above, capped at 10 exports per day.
- SCIM provisioning alongside SAML for Enterprise.
- `Retry-After` is now returned on every 429 response, not just sustained overages.

## Changed

- Webhook payload cap raised from 512 KB to 1 MB. Payloads above the cap still
  return `E1005`.
- Pro rate limit raised from 300 to 600 requests per minute.

## Deprecated

- The `/v1/legacy-export` endpoint. It will be removed in Q3 2026. Use the bulk
  export endpoint instead.
