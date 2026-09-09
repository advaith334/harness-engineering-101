"""The golden set. Small, hand-written, and including cases that should FAIL.

`expected_docs` is what makes retrieval measurable: hit rate and MRR are computed
against these, with no model call and no judgement. An eval that only scores the
final prose cannot tell you whether a bad answer was a retrieval problem or a
generation problem.

The negatives matter as much as the positives. A RAG system that never says "I
don't know" is not accurate, it is confident — and you only find out with a
question whose answer genuinely isn't in the corpus.
"""

GOLDEN = [
    # --- single-fact lookups ---
    dict(q="What is the refund window for annual plans?",
         docs=["policy-refunds.md"], route="lookup"),
    dict(q="How many requests per minute does the Pro plan allow?",
         docs=["product-api-limits.md"], route="lookup"),
    dict(q="How long are request logs kept on the Free plan?",
         docs=["policy-data-retention.md"], route="lookup"),
    dict(q="What is the first response SLA for a P1 on Enterprise?",
         docs=["policy-support-sla.md"], route="lookup"),
    dict(q="How do I rotate an API key without downtime?",
         docs=["product-authentication.md"], route="lookup"),

    # --- literal identifiers: the lexical arm must carry these ---
    dict(q="What does error code E1004 mean?",
         docs=["product-error-codes.md", "product-api-limits.md",
               "product-webhooks.md"], route="lookup"),
    dict(q="Why does pg_stat_statements look wrong after a failover?",
         docs=["runbook-database-failover.md"], route="lookup"),
    dict(q="What is the difference between E1001 and E1002?",
         docs=["product-error-codes.md"], route="lookup"),

    # --- procedure retrieval, where structure-aware chunking matters ---
    dict(q="What are the steps to roll back the billing service?",
         docs=["runbook-billing-rollback.md"], route="lookup"),
    dict(q="How often must the status page be updated during a P1?",
         docs=["runbook-incident-comms.md"], route="lookup"),

    # --- multi-part: the planner should fan out ---
    dict(q="Compare the webhook retry behaviour with the API rate limit behaviour.",
         docs=["product-webhooks.md", "product-api-limits.md"], route="compare"),
    dict(q="What changed for refunds and for SSO in 2026?",
         docs=["release-2026-q2.md", "policy-refunds.md"], route="compare"),

    # --- aggregate: SQL, not similarity ---
    dict(q="How many runbooks are in the documentation?",
         docs=[], route="aggregate"),

    # --- negatives: the corpus cannot answer these ---
    dict(q="Do you support deploying on Kubernetes with Helm charts?",
         docs=[], route="lookup", expect_refusal=True),
    dict(q="What is the CEO's home address?",
         docs=[], route="lookup", expect_refusal=True),
]
