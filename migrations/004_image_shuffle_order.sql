-- Persisted shuffled image order for auditable count-based assignment.
-- Run after 003_admin_visible_password.sql.

CREATE TABLE IF NOT EXISTS image_shuffle_order (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id             UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    s3_key             VARCHAR(1024) NOT NULL,
    filename           VARCHAR(255) NOT NULL,
    shuffle_rank       INTEGER NOT NULL,
    shuffle_seed       VARCHAR(128) NOT NULL,
    created_by_admin   UUID REFERENCES annotators(id),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(job_id, s3_key),
    UNIQUE(job_id, shuffle_rank)
);

CREATE INDEX IF NOT EXISTS idx_image_shuffle_order_job_rank
    ON image_shuffle_order(job_id, shuffle_rank);

CREATE INDEX IF NOT EXISTS idx_image_shuffle_order_s3_key
    ON image_shuffle_order(s3_key);
