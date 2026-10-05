# Bad Bean Polygon Review

The annotator sidebar Queue selector separates Assigned Beans (primary and
skipped redo work) from Bad Beans - Polygon Review.

## Storage

Original annotations are preserved. A review is a new assignment with
`assignment_kind = 'polygon_review'`, the same `image_id`, and
`source_assignment_id` referencing the original primary assignment. A partial
unique index allows one review per source. The existing unique constraint on
`(image_id, annotator_id)` also prevents allocating the same image twice to one
reviewer; allocation fails atomically if such a conflict exists.

The reviewer's result is stored in `annotations`, keyed by the review assignment
ID. `defects` stores polygons in image pixel coordinates. Save verifies ownership,
Bad severity and nondegenerate polygon geometry, and writes the result and done
status in one PostgreSQL transaction before navigation. Confirm alone does not
save to PostgreSQL. Existing labels are never copied into completed review rows.

The existing S3 JSON mirror includes assignment kind and source assignment ID.
PostgreSQL remains authoritative; mirror failures display a warning and are
retried during the current session. Durable mirror retry across sessions is not
yet implemented. Historical edits overwrite the review result; revision history
is not yet implemented.

## Deployment and Allocation

Apply `migrations/006_polygon_review.sql` once before allocation. Then run:

```sh
venv/bin/python scripts/assign_bad_polygon_reviews.py
venv/bin/python scripts/assign_bad_polygon_reviews.py --execute
```

The default target is `lovepreet123456`; override with `--username`. Only other
annotators' completed primary Bad labels with empty defects are eligible.
Repeated runs do not allocate existing reviews again. Allocation does not run
from the nightly skipped-redo cron.

Queue completion counts only saved polygons. Global assignment reports can
include multiple tasks per image: filter `assignment_kind` when calculating
primary-label totals; do not interpret task counts as unique-image counts.
