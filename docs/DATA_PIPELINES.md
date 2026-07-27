# Data Pipelines

## Source Image Upload Pipeline

Images are uploaded outside the Streamlit app to S3.

Required S3 layout:

```text
s3://<bucket>/images/<filename>
s3://<bucket>/boundary_images/<filename>
```

The filename must match between `images/` and `boundary_images/` so
`storage.boundary_key` can derive the boundary image key from the source image
key.

Current known production count:

- `images/`: 11,040 files.
- `boundary_images/`: 11,040 files.

## Database Image Registration Pipeline

Script: `scripts/prepare_class_balanced_6000.py`

Despite the historical filename, this script currently expects 11,040 images by
default through `EXPECTED_IMAGE_COUNT = 11040`.

Dry run:

```bash
python scripts/prepare_class_balanced_6000.py
```

Execute:

```bash
python scripts/prepare_class_balanced_6000.py --execute
```

What it does:

1. Loads `.env`.
2. Lists S3 images under `images/`.
3. Verifies the count unless `--allow-count` is supplied.
4. Finds or creates the `Default` job.
5. Inserts missing `images` rows by `s3_key`.
6. Appends missing rows to `image_shuffle_order`.
7. Recalculates `jobs.total_images`.

Important behavior:

- Existing annotators, assignments, annotations, and progress are not deleted.
- New S3 data is appended, not rebuilt.
- Existing shuffle rows stay stable; new rows are shuffled and appended after the
  current max rank.

## Assignment Pipeline

Admin count assignment:

```text
S3 list -> ensure shuffle order -> select next unassigned shuffle rows
  -> register missing image rows -> insert primary assignments
  -> write assignment report CSV mirrors to S3
```

Admin explicit assignment:

```text
S3 list -> admin search/select filenames
  -> register missing image rows -> insert primary assignments
  -> write assignment report CSV mirrors to S3
```

## Annotation Save Pipeline

Annotator save:

```text
UI action -> Streamlit session annotation object
  -> save_annotation upsert in Postgres
  -> assignment status update
  -> upload annotation JSON mirror to S3
```

JSON mirror path:

```text
annotations/<job_id>/annotators/<username>/<image_stem>.json
```

The database remains the source of truth if the S3 JSON mirror fails. The app
warns the annotator if DB save succeeded but S3 upload failed.

## Skipped Redo Pipeline

Script: `scripts/assign_skipped_redo_to_lovepreet.py`

Target username:

```text
lovepreet123456
```

Dry run:

```bash
python scripts/assign_skipped_redo_to_lovepreet.py
```

Execute:

```bash
python scripts/assign_skipped_redo_to_lovepreet.py --execute
```

Logic:

1. Find active target annotator `lovepreet123456`.
2. Find annotators whose primary assignments have zero `pending` or
   `in_progress` work.
3. For those finished annotators, find primary assignments with
   `status = 'skipped'`.
4. Ignore skipped assignments already present in `skipped_redo_queue`.
5. Insert a new `assignments` row for Lovepreet with
   `assignment_kind = 'skipped_redo'`.
6. Insert a `skipped_redo_queue` audit row linking original and redo assignment.

Nightly schedule:

```cron
0 2 * * * cd /opt/bean-annotator && <venv-python> scripts/assign_skipped_redo_to_lovepreet.py --execute >> logs/skipped_redo_lovepreet.log 2>&1
```

Design rule:

- Original skipped assignments are not modified.
- Redo work is tracked as separate assignments linked to the original skipped
  assignment.

