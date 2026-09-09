"""Hybrid search: three retrieval arms fused with RRF, in ONE SQL query.

Folder 06 does this fusion in Python because it has no database. With Postgres it
is a single round trip, and that is the argument for not bolting a separate vector
store onto a system that already has a relational one.

THREE arms, not two:
  dense    — pgvector cosine. Meaning.
  english  — to_tsvector('english'): stems, so "rotating"/"rotation" match.
  simple   — to_tsvector('simple'): does NOT stem, so E1004, --dry-run and
             pg_stat_statements survive as literal tokens. English stemming
             mangles exactly the identifiers people search for most confidently.

Details that are easy to get wrong and expensive to debug:

  * The pre-filter is applied INSIDE every arm, before each takes its top-N.
    Filtering after fusion changes the ranks and silently corrupts the result.
  * FULL OUTER JOIN, not INNER. An inner join drops rows found by only one arm —
    which is precisely the keyword-only hit that hybrid search exists to catch.
  * websearch_to_tsquery, not to_tsquery. `to_tsquery` raises a syntax error on
    ordinary user text containing '?', '&' or a hyphen. plainto_tsquery works but
    silently discards quoted phrases.
  * RRF scores from short lists sit in a very narrow band. Treat the ORDER as
    meaningful and the score as arbitrary; the reranker is what adds precision.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import CANDIDATES_PER_ARM, FUSED_K, RRF_K
from db import Vector, connect
from filters import Filters


@dataclass
class Candidate:
    chunk_id: int
    document_id: int
    uri: str
    heading_path: str
    content: str
    section_key: str
    token_count: int
    score: float
    dense_rank: int | None
    lexical_rank: int | None

    @property
    def found_by(self) -> str:
        if self.dense_rank and self.lexical_rank:
            return "both"
        return "dense" if self.dense_rank else "lexical"


SQL = """
WITH filtered AS (
    SELECT c.id, c.document_id, c.section_key, c.heading_path, c.content,
           c.token_count, c.embedding, c.tsv_english, c.tsv_simple, d.uri
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE {where}
),
dense AS (
    SELECT id, RANK() OVER (ORDER BY embedding <=> %(qvec)s) AS rank
    FROM filtered WHERE embedding IS NOT NULL
    ORDER BY embedding <=> %(qvec)s LIMIT %(arm)s
),
lex_en AS (
    SELECT id, RANK() OVER (ORDER BY ts_rank_cd(tsv_english, q) DESC) AS rank
    FROM filtered, websearch_to_tsquery('english', %(q)s) q
    WHERE tsv_english @@ q
    ORDER BY ts_rank_cd(tsv_english, q) DESC LIMIT %(arm)s
),
lex_raw AS (
    SELECT id, RANK() OVER (ORDER BY ts_rank_cd(tsv_simple, q) DESC) AS rank
    FROM filtered, websearch_to_tsquery('simple', %(q)s) q
    WHERE tsv_simple @@ q
    ORDER BY ts_rank_cd(tsv_simple, q) DESC LIMIT %(arm)s
),
fused AS (
    SELECT COALESCE(d.id, e.id, r.id) AS id,
           COALESCE(1.0/(%(k)s + d.rank), 0)
         + COALESCE(1.0/(%(k)s + e.rank), 0)
         + COALESCE(1.0/(%(k)s + r.rank), 0) AS score,
           d.rank AS dense_rank,
           LEAST(COALESCE(e.rank, 9999), COALESCE(r.rank, 9999)) AS lexical_rank
    FROM dense d
    FULL OUTER JOIN lex_en  e ON e.id = d.id
    FULL OUTER JOIN lex_raw r ON r.id = COALESCE(d.id, e.id)
)
SELECT f.id, c.document_id, c.uri, c.heading_path, c.content, c.section_key,
       c.token_count, f.score, f.dense_rank,
       NULLIF(f.lexical_rank, 9999) AS lexical_rank
FROM fused f JOIN filtered c ON c.id = f.id
ORDER BY f.score DESC
LIMIT %(limit)s
"""


def hybrid_search(query: str, qvec: list[float], filters: Filters | None = None,
                  limit: int = FUSED_K) -> list[Candidate]:
    filters = filters or Filters()
    where, params = filters.where()
    params |= {"qvec": Vector(qvec), "q": query, "arm": CANDIDATES_PER_ARM,
               "k": RRF_K, "limit": limit}

    with connect() as conn, conn.cursor() as cur:
        # pgvector's HNSW index is a POST-filtering index: it walks ef_search
        # candidates and only then applies the WHERE, so a selective filter
        # under-fills the result with rows that aren't the true nearest. At this
        # corpus size an exact scan is sub-millisecond and simply correct.
        # iterative_scan keeps the behaviour right as the corpus grows.
        cur.execute("SET LOCAL hnsw.ef_search = 200")
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        cur.execute(SQL.format(where=where), params)
        return [Candidate(*row) for row in cur.fetchall()]


def count_filtered(filters: Filters) -> int:
    where, params = filters.where()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM chunks c JOIN documents d "
                    f"ON d.id = c.document_id WHERE {where}", params)
        return cur.fetchone()[0]


if __name__ == "__main__":
    import mistral

    for q in ["E1004", "how do I rotate an API key", "pg_stat_statements"]:
        vec = mistral.embed([q])[0]
        hits = hybrid_search(q, vec, limit=5)
        print(f"\nQ: {q}")
        for h in hits:
            print(f"  {h.score:.4f} [{h.found_by:>7}] {h.uri} :: {h.heading_path[:52]}")
