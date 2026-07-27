# Testing And Operations

## Current Testing Strategy

The project currently relies mostly on operational validation rather than a
formal automated test suite. Before deploying changes, validate the affected
end-to-end flows manually and run syntax/import checks locally.

Recommended baseline checks:

```bash
python -m py_compile admin_app.py annotate_beans.py annotation.py auth.py db.py storage.py
python scripts/prepare_class_balanced_6000.py --allow-count 11040
python scripts/assign_skipped_redo_to_lovepreet.py
```

The two scripts should be safe in dry-run mode.

## Manual Validation Checklist

### Login

- Admin can sign in to the admin dashboard.
- Annotator can sign in to the annotator dashboard.
- Browser refresh restores the session when the refresh cookie is valid.
- Sign out clears the session and cookie.

### Team

- Admin can create a new annotator.
- Generated username and password display to the owning admin.
- Other admins can view but not manage the annotator.
- Deactivation disables login and removes the annotator from active lists.
- The same username cannot be reused after deactivation.

### Assignment

- Dashboard total images matches S3/DB expected count.
- Count assignment assigns from saved shuffle order.
- Specific image assignment works.
- Assignment report CSV downloads.
- Reducing assignment count removes only pending rows.
- Started/done/skipped work is preserved.

### Annotator

- Queue loads only assigned images.
- Current image and nearby images load from S3.
- Good saves and advances.
- Bad opens drawing step.
- Polygon defects save correctly.
- Skip saves and advances.
- Previous navigation allows correcting accidental choices.
- Re-saving updates the existing DB row.

### Exports

- Admin export includes expected rows.
- Good/Bad/Skipped counts match progress summaries.
- CSV and JSON downloads work.

### Skipped Redo

- Dry-run reports candidates.
- Execute creates `skipped_redo` assignments only once.
- Lovepreet sees the redo queue.
- Original skipped assignment rows remain unchanged.

## Operational Health Queries

Useful PostgreSQL checks:

```sql
SELECT COUNT(*) FROM images;
SELECT COUNT(*) FROM image_shuffle_order;
SELECT assignment_kind, status, COUNT(*)
FROM assignments
GROUP BY assignment_kind, status
ORDER BY assignment_kind, status;

SELECT ann.name, ann.username,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE a.status = 'done') AS done,
       COUNT(*) FILTER (WHERE a.status = 'skipped') AS skipped,
       COUNT(*) FILTER (WHERE a.status = 'pending') AS pending,
       COUNT(*) FILTER (WHERE a.status = 'in_progress') AS in_progress
FROM assignments a
JOIN annotators ann ON ann.id = a.annotator_id
GROUP BY ann.name, ann.username
ORDER BY ann.name;
```

Check for duplicate primary assignments:

```sql
SELECT image_id, COUNT(*)
FROM assignments
WHERE assignment_kind = 'primary'
GROUP BY image_id
HAVING COUNT(*) > 1;
```

Check for annotations without assignment:

```sql
SELECT an.id
FROM annotations an
LEFT JOIN assignments a ON a.id = an.assignment_id
WHERE a.id IS NULL;
```

## Monitoring

Minimum operational monitoring:

- EC2 CPU, memory, disk.
- RDS connections, CPU, free storage.
- Streamlit systemd service health.
- S3 object counts under `images/` and `boundary_images/`.
- Nightly skipped-redo cron log.

## Suggested Automated Tests

Future work should add:

- unit tests for `db.py` query builders using a test Postgres database
- integration tests for assignment insert conflicts
- migration tests from empty and existing schemas
- auth role mapping tests
- Streamlit smoke tests for both entrypoints
- browser tests for major admin and annotator flows

