-- One Postgres doing both jobs: relational metadata AND vector search.
-- The design claim of this folder is that a second, dedicated vector store
-- would buy nothing here and cost you a consistency story.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- documents
CREATE TABLE IF NOT EXISTS documents (
    id             bigserial PRIMARY KEY,
    uri            text NOT NULL UNIQUE,        -- natural key; re-ingest updates in place
    title          text NOT NULL,
    doc_type       text NOT NULL,               -- product | policy | runbook | release_notes
    product        text,
    service        text,
    effective_date date,
    version        text,
    content_hash   text NOT NULL,               -- skip re-processing unchanged files
    ingested_at    timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------- chunks
CREATE TABLE IF NOT EXISTS chunks (
    id           bigserial PRIMARY KEY,
    document_id  bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_key  text NOT NULL,        -- chunks sharing this belong to one section
    heading_path text NOT NULL,        -- "H1 > H2 > H3", prepended to the embedded text
    ordinal      int  NOT NULL,        -- position within the document
    content      text NOT NULL,
    token_count  int  NOT NULL,
    embedding    vector(1024),         -- mistral-embed
    metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- TWO lexical arms, on purpose.
    --   'english' stems prose: "rotating"/"rotation" match.
    --   'simple'  does not:    E1004, --dry-run and pg_stat_statements survive intact.
    -- Both must use the two-argument form: to_tsvector(content) alone is only
    -- STABLE, not IMMUTABLE, and Postgres rejects it in a generated column.
    tsv_english  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    tsv_simple   tsvector GENERATED ALWAYS AS (to_tsvector('simple',  content)) STORED,

    UNIQUE (document_id, ordinal)
);

-- ------------------------------------------------------ retrieval telemetry
-- The highest-value table here. Without the per-stage candidate ids you cannot
-- tell whether a wrong answer means the pre-filter killed the right chunk, the
-- fusion ranked it 40th, or the reranker dropped it.
CREATE TABLE IF NOT EXISTS retrieval_traces (
    id              bigserial PRIMARY KEY,
    question        text NOT NULL,
    sub_question    text NOT NULL,
    route           text NOT NULL,
    filters         jsonb NOT NULL DEFAULT '{}'::jsonb,
    filter_relaxed  boolean NOT NULL DEFAULT false,
    prefilter_count int  NOT NULL DEFAULT 0,   -- stage 1: rows surviving the WHERE
    fused_ids       bigint[] NOT NULL DEFAULT '{}',  -- stage 2
    reranked_ids    bigint[] NOT NULL DEFAULT '{}',  -- stage 3
    assembled_ids   bigint[] NOT NULL DEFAULT '{}',  -- stage 4
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------- eval runs
CREATE TABLE IF NOT EXISTS eval_runs (
    id              bigserial PRIMARY KEY,
    run_label       text NOT NULL,
    question        text NOT NULL,
    expected_docs   text[] NOT NULL DEFAULT '{}',
    answer          text,
    -- deterministic, no model call
    citations_valid boolean,
    hit             boolean,
    reciprocal_rank double precision,
    -- judged
    groundedness    int,
    completeness    int,
    judge_note      text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
