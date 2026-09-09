---
title: Billing Service Rollback
doc_type: runbook
service: billing
effective_date: 2026-04-02
version: "1.4"
---

# Billing Service Rollback

## When to use this

Roll back when the billing service is emitting `E2001` (destination timeout) at more
than 2% of requests for over five minutes, or when any invoice-generation error is
observed. Do not roll back for elevated latency alone — see the scaling runbook.

## Procedure

1. Declare a P1 in `#incidents` and page the billing on-call.
2. Identify the last known-good release tag:

   ```bash
   kubectl -n billing rollout history deployment/billing-api
   ```

3. Roll back and watch the rollout:

   ```bash
   kubectl -n billing rollout undo deployment/billing-api --to-revision=<n>
   kubectl -n billing rollout status deployment/billing-api --timeout=180s
   ```

4. Confirm `E2001` rate returns below 0.1% on the billing dashboard.
5. Do **not** replay the failed invoice queue until the rollback is confirmed
   healthy for 15 minutes. Replaying early double-charges customers.

## After the rollback

Freeze billing deploys until a postmortem is scheduled. The freeze is lifted by the
service owner, not by the on-call.
