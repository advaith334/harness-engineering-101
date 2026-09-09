---
title: Incident Communications
doc_type: runbook
service: platform
effective_date: 2026-02-20
version: "1.2"
---

# Incident Communications

## Who says what

The incident commander owns the timeline. The comms lead owns everything customers
see. Engineers do not post to the status page directly.

## Cadence

| Severity | Status page update | Internal update |
|----------|--------------------|-----------------|
| P1       | Every 30 minutes   | Every 15 minutes |
| P2       | Every 2 hours      | Every hour       |

## Wording rules

State impact, not cause. "Some customers cannot generate invoices" is publishable;
"the billing deploy broke the Stripe client" is not, until the postmortem. Never give
an ETA you are not certain of — say "next update in 30 minutes" instead.
