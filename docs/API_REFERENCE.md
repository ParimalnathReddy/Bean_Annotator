# Internal API Reference

The project has no public HTTP API. This reference documents the internal Python
interfaces that form the app's service layer.

## Database API: `db.py`

### Accounts

- `get_or_create_annotator(...)`: create or update an admin/annotator DB row.
- `get_all_annotators(admin_id=None)`: list active annotators globally or owned
  by one admin.
- `get_annotator_by_username(username)`: enforce username reservation.
- `deactivate_annotator(annotator_id, admin_id)`: soft-delete an owned annotator
  and release unworked assignments.

### Jobs And Images

- `get_or_create_batch(name, created_by)`: find or create a batch/job.
- `register_and_assign_images(image_rows, job_id, uploaded_by, annotator_id,
  assigned_by_admin)`: bulk image upsert plus assignment insert.
- `ensure_shuffle_order(job_id, image_rows, admin_id)`: append missing images to
  persistent shuffle order.
- `get_unassigned_images_in_shuffle_order(job_id, limit)`: return next available
  shuffled rows.

### Assignments

- `get_assigned_s3_keys(annotator_id)`: keys assigned to one annotator.
- `get_all_assigned_s3_keys()`: keys assigned to anyone.
- `assign_images_to_annotator(image_ids, annotator_id, assigned_by_admin)`: bulk
  primary assignment insert.
- `get_assignment_status_counts(annotator_id, admin_id)`: status counts scoped to
  assigning admin.
- `reduce_pending_assignments(annotator_id, admin_id, target_total)`: delete
  newest pending rows to reduce workload.
- `get_annotator_queue(annotator_id)`: full queue with existing annotation data.
- `update_assignment_cursor(assignment_id, last_image_idx, status)`: update
  progress cursor and status.

### Annotations And Reports

- `save_annotation(...)`: upsert one annotation and update assignment status.
- `get_progress_summary(admin_id=None)`: dashboard progress rows.
- `get_annotator_assignment_summary(admin_id=None)`: assignment summary rows.
- `get_full_assignment_report(admin_id=None)`: CSV-ready assignment audit rows.
- `get_all_annotations_for_job(job_id, admin_id=None)`: export rows.

## Storage API: `storage.py`

- `list_all_images(prefix='images/')`
- `download_image(s3_key)`
- `boundary_key(s3_key)`
- `upload_annotation_json(data, job_id, annotator, filename)`
- `save_assignment_report(rows, admin_id=None)`
- `save_annotator_assignment_report(rows, annotator)`
- `download_assignment_report(admin_id=None)`
- `upload_export_csv(csv_bytes, job_id, filename)`

## Auth API: `auth.py`

- `require_login(login_title=None)`: render login or return authenticated user.
- `logout()`: clear session and auth cookie.
- `verify_token(id_token)`: validate Cognito ID token.

