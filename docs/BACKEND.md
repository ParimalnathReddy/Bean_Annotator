# Backend Architecture

This project does not expose a separate REST API server. The Streamlit apps call
Python service modules directly. The backend boundary is organized by module.

## `db.py`

`db.py` owns all PostgreSQL access. It provides:

- connection pooling and transaction management
- account row creation and lookup
- soft deactivation
- job and image registration
- persistent shuffle order
- assignment creation, reduction, and queue loading
- annotation upserts
- progress and export queries

Important implementation details:

- Every `get_conn()` block commits on success and rolls back on exception.
- Bulk inserts use `psycopg2.extras.execute_values`.
- Normal assignment inserts use `assignment_kind = 'primary'`.
- Conflict handling uses `ON CONFLICT DO NOTHING` so partial unique indexes for
  primary and skipped-redo assignments work correctly.
- `ensure_shuffle_order` uses a Postgres advisory transaction lock to avoid two
  admins creating shuffle rows for the same job at the same time.

## `storage.py`

`storage.py` owns S3 access.

Main functions:

- `list_all_images`: paginated listing under `images/`.
- `download_image`: load image bytes from S3.
- `boundary_key`: convert `images/foo.png` to `boundary_images/foo.png`.
- `upload_annotation_json`: write annotation mirror JSON.
- `save_assignment_report`: write global or admin-scoped assignment CSV.
- `save_annotator_assignment_report`: write per-annotator assignment CSV.
- `download_assignment_report`: read assignment CSV for admin download.

S3 object layout:

```text
images/<filename>
boundary_images/<filename>
annotations/<job_id>/annotators/<username>/<image_stem>.json
reports/assignment_report.csv
reports/assignment_report_<admin_id>.csv
assignments/<username>/assignment_report.csv
exports/<job_id>/<filename>
```

## `auth.py`

`auth.py` owns Cognito login and role resolution.

Main responsibilities:

- `USER_PASSWORD_AUTH` login.
- ID-token signature verification through Cognito JWKS.
- refresh-token based session restoration using `streamlit-cookies-controller`.
- role mapping from Cognito group membership.
- shared login UI.
- logout and cookie clearing.

Roles:

- Cognito group `admins` maps to app role `admin`.
- Everyone else maps to `annotator` unless created otherwise in DB.

## `annotation.py`

`annotation.py` owns the interactive annotation experience. It is intentionally
UI-heavy and maintains local Streamlit session state for the current annotator
queue.

Important behavior:

- Good saves `overall_severity = 1` and advances.
- Bad saves `overall_severity = 2`, sends the user to the defect drawing step,
  and saves polygons when confirmed.
- Skip saves a skip reason and advances.
- Previous and numeric navigation allow annotators to revisit completed work.
- Because `annotations.assignment_id` is unique, revisiting and saving an image
  updates the existing result rather than creating a duplicate row.
- Polygon coordinates are stored in original image coordinates.

## Admin Service Logic

`admin_app.py` orchestrates admin workflows:

- creates Cognito annotator users
- creates corresponding DB rows
- displays global progress
- restricts management actions to account owners
- assigns images by persistent shuffle order
- assigns explicit selected images
- reduces only pending work
- exports annotation CSV/JSON

Cached reads:

- S3 image listing: 5 minute TTL.
- assignment and progress summaries: 30 second TTL.

After write operations, `_bust_cache()` clears cached assignment/progress reads
so the next render uses fresh values.

