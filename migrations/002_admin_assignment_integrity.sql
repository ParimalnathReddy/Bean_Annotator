-- Admin dashboard integrity additions.
-- Run after 001_initial_schema.sql.

ALTER TABLE annotators
    ADD COLUMN IF NOT EXISTS username VARCHAR(255),
    ADD COLUMN IF NOT EXISTS created_by_admin UUID REFERENCES annotators(id);

UPDATE annotators
SET username = COALESCE(NULLIF(username, ''), NULLIF(split_part(email, '@', 1), ''), cognito_sub)
WHERE username IS NULL OR username = '';

ALTER TABLE annotators
    ALTER COLUMN username SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_annotators_username_unique
    ON annotators (lower(username));

CREATE INDEX IF NOT EXISTS idx_annotators_created_by_admin
    ON annotators(created_by_admin);

ALTER TABLE assignments
    ADD COLUMN IF NOT EXISTS assigned_by_admin UUID REFERENCES annotators(id);

UPDATE assignments a
SET assigned_by_admin = j.created_by
FROM images i
JOIN jobs j ON j.id = i.job_id
WHERE a.image_id = i.id
  AND a.assigned_by_admin IS NULL;

ALTER TABLE assignments
    ALTER COLUMN assigned_by_admin SET NOT NULL;

-- One image should be assigned to one annotator by default.
-- If this fails, resolve duplicate image assignments before rerunning.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_one_active_owner_per_image
    ON assignments(image_id);

CREATE INDEX IF NOT EXISTS idx_assignments_assigned_by_admin
    ON assignments(assigned_by_admin);

CREATE UNIQUE INDEX IF NOT EXISTS idx_annotations_one_result_per_assignment
    ON annotations(assignment_id);

-- Each S3 object should map to one image record.
-- If this fails, resolve duplicate image rows by s3_key before rerunning.
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_s3_key_unique
    ON images(s3_key);
