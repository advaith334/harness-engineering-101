"""Named aggregate queries — the relational half of "one database does both".

Without this, the relational side of the schema is decoration: everything goes
through vector search and Postgres is just a place vectors live. Questions like
"how many runbooks do we have?" or "what changed since March?" are SQL questions,
and answering them by embedding similarity is the wrong tool.

THE MODEL NEVER WRITES SQL. It picks a `query_name` from an enum and fills typed
parameters; execution looks the template up in this registry. That is the same
discipline as folder 12's "if you can express the check in Python, don't ask a
model" — a SQL sanitizer is a losing game, a whitelist is not.

Defence in depth on top of the whitelist: a statement timeout and a hard LIMIT
applied by the executor, not by the template.

One honest caveat, which the synthesizer is instructed to pass on: aggregates over
`metadata->'entities'` describe the ENRICHMENT PASS, not the world. "3 documents
mention Redis" means three documents whose extracted metadata mentions Redis.
"""

from __future__ import annotations

from db import connect

MAX_ROWS = 50
STATEMENT_TIMEOUT_MS = 3000

NAMED_QUERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "count_docs_by_type": (
        "SELECT doc_type, count(*) AS documents FROM documents "
        "GROUP BY doc_type ORDER BY documents DESC", ()),

    "list_docs_of_type": (
        "SELECT uri, title, effective_date FROM documents "
        "WHERE doc_type = %(doc_type)s ORDER BY effective_date DESC", ("doc_type",)),

    "docs_changed_since": (
        "SELECT uri, title, doc_type, effective_date FROM documents "
        "WHERE effective_date >= %(since)s ORDER BY effective_date DESC", ("since",)),

    "docs_mentioning_entity": (
        # jsonb lateral instead of an entities/chunk_entities join table: entity
        # normalization ("Postgres" vs "PostgreSQL") is real work that buys
        # nothing at this scale.
        "SELECT DISTINCT d.uri, d.title FROM documents d "
        "JOIN chunks c ON c.document_id = d.id "
        "CROSS JOIN LATERAL jsonb_array_elements_text("
        "  COALESCE(c.metadata->'entities', '[]'::jsonb)) AS e(name) "
        "WHERE lower(e.name) LIKE lower(%(entity)s) ORDER BY d.uri", ("entity",)),

    "coverage_by_document": (
        "SELECT d.uri, count(c.id) AS chunks, sum(c.token_count) AS tokens "
        "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
        "GROUP BY d.uri ORDER BY chunks DESC", ()),

    "services_with_runbooks": (
        "SELECT service, count(*) AS runbooks FROM documents "
        "WHERE doc_type = 'runbook' AND service IS NOT NULL "
        "GROUP BY service ORDER BY runbooks DESC", ()),
}

QUERY_NAMES = tuple(NAMED_QUERIES)


def run_named_query(name: str, params: dict) -> tuple[list[str], list[tuple]]:
    if name not in NAMED_QUERIES:
        raise ValueError(f"unknown query {name!r}; allowed: {QUERY_NAMES}")
    sql, required = NAMED_QUERIES[name]

    missing = [p for p in required if not params.get(p)]
    if missing:
        raise ValueError(f"{name} needs parameters {missing}")
    bound = {k: params[k] for k in required}

    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cur.execute(f"{sql} LIMIT {MAX_ROWS}", bound)   # LIMIT applied here, not in the template
        cols = [d.name for d in cur.description]
        return cols, cur.fetchall()


def format_rows(cols: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "(no rows)"
    lines = [" | ".join(cols), "-" * 40]
    lines += [" | ".join(str(v) for v in r) for r in rows]
    return "\n".join(lines)


if __name__ == "__main__":
    for name in ("count_docs_by_type", "services_with_runbooks", "coverage_by_document"):
        cols, rows = run_named_query(name, {})
        print(f"\n== {name} ==\n{format_rows(cols, rows[:6])}")
