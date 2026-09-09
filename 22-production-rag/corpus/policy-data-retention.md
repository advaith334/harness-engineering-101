---
title: Data Retention
doc_type: policy
product: platform
effective_date: 2026-02-01
version: "1.8"
---

# Data Retention

## Log retention by plan

| Plan       | Request logs | Audit logs |
|------------|--------------|------------|
| Free       | 30 days      | Not available |
| Pro        | 1 year       | 1 year        |
| Enterprise | Configurable | 7 years       |

## Deletion

Deleting a workspace schedules it for purge after 7 days. During those 7 days it can
be restored by support. After the purge completes the data is unrecoverable, including
from backups.

Export any data you need before deleting. The bulk export endpoint is available on Pro
and above and is capped at 10 exports per day.
