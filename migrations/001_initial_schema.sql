CREATE TABLE annotators (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_sub     VARCHAR(255) UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    role            VARCHAR(50)  NOT NULL DEFAULT 'annotator',
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ
);

CREATE TABLE jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(255) NOT NULL,
    description  TEXT,
    created_by   UUID REFERENCES annotators(id),
    status       VARCHAR(50) DEFAULT 'active',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    total_images INTEGER DEFAULT 0
);

CREATE TABLE images (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID REFERENCES jobs(id) ON DELETE CASCADE,
    filename    VARCHAR(255) NOT NULL,
    s3_key      VARCHAR(1024) NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    uploaded_by UUID REFERENCES annotators(id)
);

CREATE TABLE assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        UUID REFERENCES images(id) ON DELETE CASCADE,
    annotator_id    UUID REFERENCES annotators(id),
    status          VARCHAR(50) DEFAULT 'pending',
    assigned_at     TIMESTAMPTZ DEFAULT NOW(),
    last_image_idx  INTEGER DEFAULT 0,
    last_active_at  TIMESTAMPTZ,
    UNIQUE(image_id, annotator_id)
);

CREATE TABLE annotations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id       UUID REFERENCES assignments(id) ON DELETE CASCADE,
    annotator_id        UUID REFERENCES annotators(id),
    overall_severity    INTEGER CHECK (overall_severity BETWEEN 1 AND 5),
    overall_notes       TEXT,
    defects             JSONB DEFAULT '[]',
    skip_reason         TEXT,
    annotation_version  INTEGER DEFAULT 3,
    saved_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_assignments_annotator  ON assignments(annotator_id);
CREATE INDEX idx_assignments_status     ON assignments(status);
CREATE INDEX idx_annotations_assignment ON annotations(assignment_id);
CREATE INDEX idx_images_job             ON images(job_id);
