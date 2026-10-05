CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_one_polygon_review_per_source
    ON assignments(source_assignment_id)
    WHERE assignment_kind = 'polygon_review';

ALTER TABLE assignments ADD CONSTRAINT assignments_polygon_review_source_check
    CHECK (assignment_kind <> 'polygon_review' OR source_assignment_id IS NOT NULL);
