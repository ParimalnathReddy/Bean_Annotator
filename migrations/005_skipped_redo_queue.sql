-- Allow skipped images to be assigned again for review without losing original history.
-- Primary assignments remain one-per-image; skipped redo assignments reference the
-- original skipped assignment.

ALTER TABLE assignments
    ADD COLUMN IF NOT EXISTS assignment_kind VARCHAR(50) NOT NULL DEFAULT 'primary',
    ADD COLUMN IF NOT EXISTS source_assignment_id UUID REFERENCES assignments(id),
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

DROP INDEX IF EXISTS idx_assignments_one_active_owner_per_image;

CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_one_primary_owner_per_image
    ON assignments(image_id)
    WHERE assignment_kind = 'primary';

CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_one_skipped_redo_per_source
    ON assignments(source_assignment_id)
    WHERE assignment_kind = 'skipped_redo';

CREATE INDEX IF NOT EXISTS idx_assignments_assignment_kind
    ON assignments(assignment_kind);

CREATE INDEX IF NOT EXISTS idx_assignments_source_assignment
    ON assignments(source_assignment_id);

CREATE TABLE IF NOT EXISTS skipped_redo_queue (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_assignment_id     UUID NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    redo_assignment_id         UUID REFERENCES assignments(id) ON DELETE SET NULL,
    image_id                   UUID NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    original_annotator_id      UUID NOT NULL REFERENCES annotators(id),
    redo_annotator_id          UUID NOT NULL REFERENCES annotators(id),
    queued_by                  UUID REFERENCES annotators(id),
    queued_at                  TIMESTAMPTZ DEFAULT NOW(),
    assigned_at                TIMESTAMPTZ,
    status                     VARCHAR(50) NOT NULL DEFAULT 'assigned',
    UNIQUE(original_assignment_id),
    UNIQUE(redo_assignment_id)
);

CREATE INDEX IF NOT EXISTS idx_skipped_redo_queue_redo_annotator
    ON skipped_redo_queue(redo_annotator_id);

CREATE INDEX IF NOT EXISTS idx_skipped_redo_queue_status
    ON skipped_redo_queue(status);
