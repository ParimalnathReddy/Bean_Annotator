-- Prototype/admin convenience only:
-- stores the generated annotator password so the admin dashboard can display it.
-- Do not use this pattern for a high-security production deployment.

ALTER TABLE annotators
    ADD COLUMN IF NOT EXISTS admin_visible_password TEXT;
