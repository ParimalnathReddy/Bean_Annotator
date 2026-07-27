# Design Decisions And Limitations

## Key Design Decisions

### Streamlit For Both Apps

Streamlit keeps the admin and annotator experiences simple to build and deploy.
The tradeoff is that session state and reruns require careful handling,
especially around login cookies and annotation save synchronization.

### Postgres As Source Of Truth

Assignments, annotations, progress, and audit records are stored in Postgres.
This gives reliable joins and exports. S3 JSON and CSV files are mirrors for
traceability and convenience.

### Persistent Shuffle Order

Count-based assignment uses `image_shuffle_order` instead of selecting randomly
each time. This makes distribution auditable and repeatable:

- existing rows keep their rank
- new data is appended after the existing max rank
- admins can see shuffle rank in assignment reports

### Soft Delete For Annotators

Annotator deletion is implemented as deactivation. This keeps historical data
intact and avoids orphaning annotations. Usernames remain permanently reserved
so old rows never become ambiguous.

### Global Admin Visibility, Owner-Only Management

All admins can monitor overall lab progress. Only the admin who created an
annotator can manage that annotator's account or assignments.

### Separate Skipped Redo Assignments

Skipped images are not overwritten. A redo assignment is a new assignment row
with `assignment_kind = 'skipped_redo'`, linked back to the original skipped
assignment. This keeps both the original annotator's decision and the redo
review history.

## Assumptions

- S3 `images/` and `boundary_images/` filenames match.
- Cognito groups are maintained correctly.
- The active production job is named `Default`.
- Admins use the dashboard for creating annotators instead of manually creating
  Cognito-only users.
- RDS is reachable from EC2 and from approved developer environments.
- The team size remains modest enough for Streamlit and the current connection
  pool.

## Known Limitations

- Generated passwords are stored in plaintext in `admin_visible_password` for
  prototype convenience. Replace this before strict production/security review.
- There is no formal automated test suite yet.
- There is no REST API; business logic is called directly from Streamlit.
- The script name `prepare_class_balanced_6000.py` is historical even though the
  current expected count is 11,040.
- Migrations are SQL files but there is no migration runner yet.
- Progress pages filter to active annotators, so deactivated users are preserved
  in the database but not displayed in normal active dashboards.
- Assignment reports are regenerated after assignment actions, not continuously
  on every annotation save.
- The app currently assumes one active production bucket configured by env.

## Future Improvements

- Add a real migration runner such as Alembic or a small internal migration
  registry.
- Add automated tests and CI validation.
- Replace plaintext password display with invite links or admin-triggered reset.
- Add admin audit events table for create, assign, reduce, deactivate, export,
  and skipped-redo actions.
- Add data quality dashboards for class balance, annotator agreement, skip
  reasons, and defect distributions.
- Add row-level permission helpers in `db.py` so ownership checks are centralized.
- Add a deployment preflight that verifies `.env`, venv path, DB migration state,
  S3 counts, and service status before restart.
- Add dead-letter logging for failed S3 JSON mirror uploads.
- Add annotator workload balancing and assignment caps.
- Add duplicate filename checks between `images/` and `boundary_images/`.

