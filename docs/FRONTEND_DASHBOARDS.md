# Frontend And Dashboards

The frontend is Streamlit. There is no separate JavaScript framework. The main
UI state is stored in `st.session_state`, with some custom HTML/CSS used for
polished dashboards and the polygon canvas.

## Admin Dashboard

Entrypoint: `admin_app.py`

Navigation:

- Progress
- Team
- Assign Images
- Export

### Progress Page

Data source:

- `get_progress_summary(None)`

KPIs:

- Total Assigned: sum of all assignment rows for active annotators.
- Done: assignments with `status = 'done'`.
- In Progress: assignments with `status = 'in_progress'`.
- Skipped: assignments with `status = 'skipped'`.
- Pending: assignments with `status = 'pending'`.
- Overall completion: `round(100 * done / total_assigned)`.

Visualization:

- Five metric cards.
- Overall progress bar.
- Per-annotator cards with username, owner, last active timestamp, status
  counts, and completion percentage.

Scope:

- Global. All admins see all active annotator progress.

### Team Page

Data sources:

- `get_all_annotators()`
- `get_progress_summary(None)`
- Cognito Admin APIs for user creation and disabling.

Features:

- Create annotator account with full name and username.
- Generate secure password.
- Create Cognito user, set permanent password, add to `annotators` group.
- Create DB annotator row with `created_by_admin`.
- Display username/password to owning admin.
- Show other admins' annotators as view-only.
- Deactivate owned annotators.

Deactivation behavior:

- Disables the Cognito user.
- Sets `annotators.is_active = false`.
- Releases only `pending` and `in_progress` assignments.
- Keeps completed/skipped assignments and annotations.
- Keeps username reserved forever.

### Assign Images Page

Data sources:

- `list_all_images(prefix='images/')`
- `get_all_assigned_s3_keys()`
- `get_annotator_assignment_summary(None)`
- `ensure_shuffle_order`
- `get_unassigned_images_in_shuffle_order`
- `get_assignment_status_counts`

KPIs:

- Total images: count of S3 images under `images/`.
- Not assigned to anyone: S3 keys not present in assignments.
- Given to someone: total S3 keys minus unassigned keys.

Assignment modes:

- Assign by count: takes the next unassigned rows in `image_shuffle_order`.
- Pick specific images: admin searches filenames and selects exact images.

Management restrictions:

- Drop-down contains only annotators created by the current admin.
- Summary section still shows all annotators globally.

Adjustment:

- Admin can reduce owned annotator assignment count.
- Only pending assignments are removed.
- Started, done, and skipped assignments are protected.

Reports:

- Global assignment report: `reports/assignment_report.csv`.
- Admin-scoped report: `reports/assignment_report_<admin_id>.csv`.
- Annotator report: `assignments/<username>/assignment_report.csv`.

### Export Page

Data source:

- `get_all_annotations_for_job(job_id, None)`

KPIs:

- Total rows.
- Good count.
- Bad count.
- Skipped count.

Downloads:

- CSV result export.
- JSON result export.

## Annotator Dashboard

Entrypoint: `annotate_beans.py`

Flow:

1. Require Cognito login.
2. Ensure matching `annotators` row exists.
3. Load assigned queue from Postgres.
4. Resume at the first pending or in-progress assignment.
5. Lazy-load current image and nearby images from S3.
6. Render annotation interface.
7. Save changed annotations to DB and S3 JSON mirror.

Navigation:

- Previous.
- Jump to image number.
- Next.
- Next unfinished.

Rating actions:

- Good: saves severity 1 and advances.
- Bad: saves severity 2 and opens defect drawing step.
- Skip: saves skip status and advances.

Redo/correction behavior:

- Annotators can navigate back to an image and save again.
- The existing annotation row is updated because the database enforces one
  annotation per assignment.

## Polygon Defect UI

Implemented in `annotation.py`.

Data stored for each defect:

- shape type, currently polygon.
- polygon points in original image coordinates.
- defect label/notes where applicable.

The UI uses an HTML5 canvas for professional polygon drawing and editing. It
supports zoom, pan, draw mode, edit mode, vertex/polygon movement, delete, fit,
and confirmation before writing polygons into Streamlit state.

