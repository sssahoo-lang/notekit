CREATE EXTENSION IF NOT EXISTS vector;

-- One row per canonical study topic. The slug is what the ingestion cache keys
-- on, so "reinforcement learning" and "RL" must normalise to the same slug
-- upstream (see pipeline.plan_syllabus) or the corpus fragments.
CREATE TABLE IF NOT EXISTS topics (
    slug         TEXT PRIMARY KEY,
    namespace    TEXT NOT NULL,
    raw_goal     TEXT NOT NULL,
    ingested_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    namespace    TEXT NOT NULL,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (namespace, source, external_id)
);

-- 384 dims matches bge-small-en-v1.5. Changing the embedding model means
-- changing this column and re-ingesting; see config.EMBEDDING.
CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    namespace    TEXT NOT NULL,
    ordinal      INT NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector(384),
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx
    ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_namespace_idx
    ON chunks (namespace);
