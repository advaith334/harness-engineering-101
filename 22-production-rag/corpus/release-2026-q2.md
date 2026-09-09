---
title: Release Notes Q2 2026
doc_type: release_notes
product: platform
effective_date: 2026-06-30
version: "2026.Q2"
---

# Release Notes — Q2 2026

## Added

- OIDC single sign-on, joining the existing SAML support on Enterprise.
- Audit log retention is now configurable on Enterprise up to 7 years.

## Changed

- Webhook retries increased from 5 attempts to 8, spread over roughly 24 hours.
- The refund window for annual plans changed from 14 days to 30 days, pro-rata.

## Fixed

- `E1002` was previously returned for both revoked and malformed keys. Malformed
  keys now correctly return `E1001`.
