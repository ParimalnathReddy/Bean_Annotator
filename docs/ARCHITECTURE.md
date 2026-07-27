# Architecture

## Purpose

The Bean Quality Annotation GUI is a two-application Streamlit system for
distributing bean image annotation work and collecting structured labels. It is
designed for a small research annotation team, roughly 10-15 concurrent
annotators plus admins.

## High-Level Components

```text
Admin Browser
  -> admin_app.py
     -> auth.py -> AWS Cognito
     -> db.py   -> Amazon RDS PostgreSQL
     -> storage.py -> Amazon S3

Annotator Browser
  -> annotate_beans.py
     -> annotation.py for interactive image UI
     -> auth.py -> AWS Cognito
     -> db.py   -> Amazon RDS PostgreSQL
     -> storage.py -> Amazon S3

Scheduled job
  -> scripts/assign_skipped_redo_to_lovepreet.py
     -> Amazon RDS PostgreSQL
```

## Runtime Workflow

1. Admin signs in through Cognito on port `8502`.
2. Admin creates annotator accounts. The admin dashboard creates the Cognito
   user, sets a permanent password, adds the user to the `annotators` group, and
   creates a matching `annotators` database row.
3. Admin assigns images by count or by explicit selection. Count-based assignment
   consumes images from a persistent shuffled order stored in Postgres.
4. Assignment rows are written to `assignments`, and CSV assignment reports are
   mirrored to S3.
5. Annotator signs in through Cognito on port `8501`.
6. Annotator queue is loaded from Postgres. Boundary images are downloaded from
   S3 lazily around the current cursor.
7. Annotator saves Good, Bad, or Skip decisions. Bad images may include polygon
   defect geometry.
8. Annotation results are upserted into Postgres and mirrored as JSON to S3.
9. Admin dashboard reads aggregate progress and exports results from Postgres.
10. Nightly skipped-redo job finds finished annotators with skipped primary
    assignments and assigns those images to the redo annotator.

## Data Ownership Model

All admins can see global annotator progress and assignment summaries. Management
actions are owner-restricted:

- The admin who created an annotator can deactivate/manage that annotator.
- Other admins can view progress, username, and owner information.
- Other admins cannot deactivate or manage someone else's annotator.

Historical integrity is preserved. Deactivated annotators remain in the database,
their usernames stay reserved, and completed/skipped annotations remain linked to
their original account.

## Source Of Truth

Postgres is the system of record for:

- annotators and roles
- images registered from S3
- persistent shuffle order
- assignments and assignment status
- annotation result rows
- redo queue records

S3 is the system of record for:

- source image files under `images/`
- boundary overlay images under `boundary_images/`
- assignment report CSV mirrors under `reports/` and `assignments/<username>/`
- annotation JSON mirrors under `annotations/<job_id>/annotators/<username>/`

