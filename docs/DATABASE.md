# Database Design

## Database

The app uses Amazon RDS PostgreSQL with SSL required. Connection settings are
read from environment variables by `db.py`:

| Variable | Purpose |
| --- | --- |
| `DB_HOST` | RDS endpoint |
| `DB_PORT` | PostgreSQL port, usually `5432` |
| `DB_NAME` | Database name |
| `DB_USER` | Database user |
| `DB_PASSWORD` | Database password |

`db.py` uses a `ThreadedConnectionPool` with min `2` and max `20` connections to
support the current target of roughly 10-15 annotators plus admin usage.

## Tables

### `annotators`

Stores both admins and annotators.

Important columns:

- `id`: internal UUID primary key.
- `cognito_sub`: Cognito subject identifier.
- `username`: login username, unique case-insensitively.
- `name`, `email`: display/contact identity.
- `role`: `admin` or `annotator`.
- `is_active`: soft-delete flag.
- `created_by_admin`: owner admin for annotator accounts.
- `admin_visible_password`: current prototype convenience field used so the
  owning admin can display generated annotator passwords.
- `created_at`, `last_active_at`: lifecycle timestamps.

Rules:

- Usernames are never reused, even after deactivation.
- Deactivation sets `is_active = false` and disables the Cognito user.
- Historical rows remain for audit and exports.

### `jobs`

Represents an image batch. Current production uses the `Default` job.

Important columns:

- `id`
- `name`
- `description`
- `created_by`
- `status`
- `total_images`
- `created_at`

### `images`

One row per source S3 image.

Important columns:

- `id`
- `job_id`
- `filename`
- `s3_key`
- `uploaded_by`
- `uploaded_at`

Rules:

- `s3_key` is unique.
- The image row stores the source image key under `images/`.
- The annotator UI derives the boundary overlay with `boundary_images/<same file>`.

### `image_shuffle_order`

Persistent shuffled assignment order for auditable count-based distribution.

Important columns:

- `job_id`
- `s3_key`
- `filename`
- `shuffle_rank`
- `shuffle_seed`
- `created_by_admin`
- `created_at`

Rules:

- `(job_id, s3_key)` is unique.
- `(job_id, shuffle_rank)` is unique.
- New images are appended to the existing order instead of reshuffling old rows.

### `assignments`

One work item for an annotator.

Important columns:

- `id`
- `image_id`
- `annotator_id`
- `assigned_by_admin`
- `status`: `pending`, `in_progress`, `done`, or `skipped`.
- `assigned_at`
- `last_image_idx`
- `last_active_at`
- `assignment_kind`: `primary` or `skipped_redo`.
- `source_assignment_id`: original skipped assignment when this is redo work.
- `metadata`: JSONB audit metadata for special assignment flows.

Rules:

- Primary assignments are one owner per image.
- Skipped-redo assignments may reuse the same image, but each original skipped
  assignment can be queued only once.
- Assignment reduction deletes only newest `pending` rows. Started, done, and
  skipped work is preserved.

### `annotations`

One saved result per assignment.

Important columns:

- `assignment_id`: unique assignment result key.
- `annotator_id`
- `overall_severity`: current production uses `1 = Good`, `2 = Bad`.
- `overall_notes`
- `defects`: JSONB polygon defect data.
- `skip_reason`
- `annotation_version`
- `saved_at`

Rules:

- `assignment_id` is unique.
- Saving is an upsert, so redo/correction on the same assignment updates the
  prior annotation rather than creating duplicates.
- Assignment status is updated with every save.

### `skipped_redo_queue`

Audit table for skipped images routed to the redo annotator.

Important columns:

- `original_assignment_id`
- `redo_assignment_id`
- `image_id`
- `original_annotator_id`
- `redo_annotator_id`
- `queued_by`
- `queued_at`
- `assigned_at`
- `status`

Rules:

- `original_assignment_id` is unique.
- `redo_assignment_id` is unique.
- Original skipped records remain untouched.

## Indexes And Constraints

Defined by migrations:

- `idx_annotators_username_unique` on `lower(username)`.
- `idx_annotators_created_by_admin`.
- `idx_images_s3_key_unique`.
- `idx_images_job`.
- `idx_assignments_annotator`.
- `idx_assignments_status`.
- `idx_assignments_assigned_by_admin`.
- `idx_assignments_one_primary_owner_per_image` partial unique index on
  `assignments(image_id)` where `assignment_kind = 'primary'`.
- `idx_assignments_one_skipped_redo_per_source` partial unique index on
  `source_assignment_id` where `assignment_kind = 'skipped_redo'`.
- `idx_assignments_assignment_kind`.
- `idx_assignments_source_assignment`.
- `idx_annotations_one_result_per_assignment`.
- `idx_annotations_assignment`.
- `idx_image_shuffle_order_job_rank`.
- `idx_image_shuffle_order_s3_key`.
- `idx_skipped_redo_queue_redo_annotator`.
- `idx_skipped_redo_queue_status`.

## Data Flow

### Image Registration

1. S3 is listed under `images/`.
2. Missing images are inserted into `images`.
3. Missing shuffle rows are inserted into `image_shuffle_order`.
4. `jobs.total_images` is recalculated.

### Assignment

1. Admin selects an annotator they own.
2. Count-based assignment calls `get_unassigned_images_in_shuffle_order`.
3. Explicit selection uses selected S3 image rows.
4. `register_and_assign_images` upserts image rows and inserts primary
   assignments with `ON CONFLICT DO NOTHING`.
5. Shared and per-admin/per-annotator assignment report CSVs are written to S3.

### Annotation

1. Annotator queue is loaded from `assignments` joined to `images`, `jobs`, and
   existing `annotations`.
2. Boundary image bytes are loaded from S3 on demand.
3. UI saves a result into Streamlit session state.
4. `save_annotation` upserts `annotations` and updates `assignments.status`.
5. A JSON mirror is uploaded to S3.

