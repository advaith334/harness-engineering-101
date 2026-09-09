"""Ingestion: parse -> chunk -> enrich -> embed -> upsert.

Two properties that turn a demo script into something you can actually run twice:

  IDEMPOTENT. Documents are keyed by uri and carry a content hash. Re-running skips
  unchanged files entirely, so a crash halfway through costs you only the remainder.

  COMMITTED PER DOCUMENT. A failure on document 9 does not roll back documents 1-8.
  One giant transaction is the classic way to lose 20 minutes of embedding spend.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import mistral
from chunking import chunk_document, parse_document
from config import EMBED_DIM
from db import Vector, bootstrap, build_indexes, connect
from enrich import enrich_document

CORPUS = Path(__file__).parent / "corpus"


def ingest_document(conn, path: Path, force: bool = False) -> int:
    doc = parse_document(path)
    content_hash = hashlib.sha256(doc.raw.encode()).hexdigest()

    with conn.cursor() as cur:
        cur.execute("SELECT id, content_hash FROM documents WHERE uri = %s", (doc.uri,))
        row = cur.fetchone()
        if row and row[1] == content_hash and not force:
            print(f"  {doc.uri}: unchanged, skipped")
            return 0

        chunks = chunk_document(doc)
        metadata = enrich_document(doc, chunks)

        vectors = mistral.embed([c.embed_text for c in chunks])
        assert all(len(v) == EMBED_DIM for v in vectors), "embedding dimension mismatch"

        cur.execute("""
            INSERT INTO documents (uri, title, doc_type, product, service,
                                   effective_date, version, content_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (uri) DO UPDATE SET
                title=EXCLUDED.title, doc_type=EXCLUDED.doc_type,
                product=EXCLUDED.product, service=EXCLUDED.service,
                effective_date=EXCLUDED.effective_date, version=EXCLUDED.version,
                content_hash=EXCLUDED.content_hash, ingested_at=now()
            RETURNING id
        """, (doc.uri, doc.title, doc.doc_type, doc.product, doc.service,
              doc.effective_date, doc.version, content_hash))
        doc_id = cur.fetchone()[0]

        # Replace wholesale: chunk boundaries move when a document is edited, so
        # matching old chunks to new ones is a fiction. Cheaper to re-embed.
        cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

        for c, vec in zip(chunks, vectors):
            cur.execute("""
                INSERT INTO chunks (document_id, section_key, heading_path, ordinal,
                                    content, token_count, embedding, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (doc_id, c.section_key, c.heading_path, c.ordinal, c.content,
                  c.token_count, Vector(vec), json.dumps(metadata[c.ordinal])))

    conn.commit()          # per document, deliberately
    print(f"  {doc.uri}: {len(chunks)} chunks")
    return len(chunks)


def main(force: bool = False) -> None:
    bootstrap()
    total = 0
    for path in sorted(CORPUS.glob("*.md")):
        with connect() as conn:            # short-lived: Neon autosuspends
            total += ingest_document(conn, path, force=force)
    build_indexes()                        # after the load, never before

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        docs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")
        embedded = cur.fetchone()[0]
    print(f"\n{docs} documents, {embedded} embedded chunks "
          f"({total} written this run){' [OFFLINE vectors]' if mistral.OFFLINE else ''}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
