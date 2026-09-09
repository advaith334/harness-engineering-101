---
title: Database Failover
doc_type: runbook
service: platform
effective_date: 2026-03-28
version: "2.1"
---

# Database Failover

## Detection

The primary is considered unhealthy when replication lag exceeds 30 seconds or the
health check fails three consecutive times. Both fire a page.

## Failover steps

1. Confirm the primary is genuinely unreachable, not merely slow:

   ```bash
   psql -h primary.internal -c "SELECT pg_is_in_recovery()" --connect-timeout=5
   ```

2. Check replica lag before promoting — promoting a lagging replica loses writes:

   ```sql
   SELECT client_addr, replay_lag FROM pg_stat_replication;
   ```

3. Promote the replica with the lowest lag.
4. Update the connection string in the secret store and restart dependent services.

## Known trap

`pg_stat_statements` resets on promotion, so query baselines will look anomalous for
about an hour afterwards. Do not chase that as a regression.
