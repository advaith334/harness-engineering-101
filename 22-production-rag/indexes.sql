-- Applied AFTER the initial load. Building HNSW on an empty table is fine, but
-- building it before a bulk load means paying for incremental inserts, and on a
-- small compute a late build on a large table can exceed maintenance_work_mem.

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_english ON chunks USING gin (tsv_english);
CREATE INDEX IF NOT EXISTS chunks_tsv_simple  ON chunks USING gin (tsv_simple);
CREATE INDEX IF NOT EXISTS chunks_metadata    ON chunks USING gin (metadata);
CREATE INDEX IF NOT EXISTS chunks_document    ON chunks (document_id, ordinal);
CREATE INDEX IF NOT EXISTS chunks_section     ON chunks (section_key);
CREATE INDEX IF NOT EXISTS documents_type     ON documents (doc_type, effective_date);
