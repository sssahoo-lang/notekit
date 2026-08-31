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

-- A description of how someone writes, never what they wrote about. Derived
-- from a writing sample at learn time; the sample itself is not stored, and the
-- profile is deliberately content-free so it cannot smuggle unsourced facts
-- into generated notes.
CREATE TABLE IF NOT EXISTS style_profiles (
    user_id      TEXT PRIMARY KEY,
    profile      JSONB NOT NULL,
    sample_chars INT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Finished courses, so reopening the UI does not regenerate (and re-bill).
-- user_id is trust-based, same model as uploads: isolation, not auth.
CREATE TABLE IF NOT EXISTS courses (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL DEFAULT '',
    goal                TEXT NOT NULL,
    summary             TEXT NOT NULL DEFAULT '',
    namespace           TEXT NOT NULL,
    module_titles       JSONB NOT NULL DEFAULT '[]',
    modules             JSONB NOT NULL DEFAULT '[]',
    estimated_cost_usd  DOUBLE PRECISION,
    with_quiz           BOOLEAN NOT NULL DEFAULT false,
    used_style          BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Which modules have been read, and where the reader left off.
    progress            JSONB NOT NULL DEFAULT '{}',
    opened_at           TIMESTAMPTZ,
    -- Clean library label, and course length for a reading estimate.
    title               TEXT,
    word_count          INT NOT NULL DEFAULT 0,
    -- generating | complete | partial, so History can show in-flight courses.
    generation_status   TEXT NOT NULL DEFAULT 'complete',
    -- Planner output kept so a partial course can resume without re-planning.
    syllabus            JSONB
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx
    ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_namespace_idx
    ON chunks (namespace);
CREATE INDEX IF NOT EXISTS courses_user_created_idx
    ON courses (user_id, created_at DESC);
