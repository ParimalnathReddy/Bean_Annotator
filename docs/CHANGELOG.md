# Changelog

---

## 2026-08-25

### Verified

- DB is source of truth for annotation counts (not S3 JSON mirrors).
- S3 JSON files show 4,642 unique crops — stale/incomplete. DB shows 6,554 done. Use DB.
- All 6,554 done images have exactly 1 annotator (no multi-annotator overlap).
- lovepreet123456 has 3,285 pending; no other annotator has pending work.

---

## 2026-08-14

### Assignment Consolidation

- All pending/in_progress images from Jorge (500), Jose (500), Andrei (500),
  Valerio (498+1), Ram (334), Karen (416+1) were released from those annotators
  and reassigned to `lovepreet123456` as `pending`.
- Total moved: 2,749 images.
- `lovepreet123456` now holds all remaining work (3,285 pending as of 2026-08-25).
- All other annotators have 0 pending — they are done.

### EC2 Script Created

- `/opt/bean-annotator/assign_skipped_to_lovepreet.py` created on EC2.
- Assigns newly-skipped images (from other annotators) to `lovepreet123456`.
- Logs to `/var/log/bean-assign-skipped.log`.
- **Not committed to git. Nightly cron not yet installed.**

### Documentation

- Created `STATUS.md` at project root (committed, pushed to main).
- Created `docs/current-state.md` (this session).
- Created `docs/CHANGELOG.md` (this session).

---

## 2026-07-27 (previous session)

### Code Changes

- **annotation.py**: Renamed severity labels: Good → "No splits / cracks" (green,
  severity=1), Bad → "Splits / cracks" (red, severity=2). Updated SEVERITY dict,
  STEPS descriptions, button text, and JS style lookup keys.
- **annotation.py**: Fixed severity revert bug — added
  `st.session_state[sev_key] = sev` inside `_do_save()`.
- **annotation.py**: Draw mode drag-to-pan — `drawPending` state + 5px threshold
  disambiguates click vs drag in both Draw and Edit canvas modes.
- **auth.py**: Added cookie-based session persistence using
  `streamlit-cookies-controller==0.0.4`. Adds `_set_auth_cookie`,
  `_clear_auth_cookie`, `_try_restore_session`. Cookie named `bean_auth`,
  max_age 29 days. **Still broken — reads always return None.**
- **admin_app.py**: Cognito rollback on DB failure during account creation
  (fix #2). Password display scoped to owning admin only (fix #3).
- **db.py**: `get_unassigned_images_in_shuffle_order` — changed LEFT JOIN to
  INNER JOIN on s3_key only (no job_id). Fixes empty pool bug.
- **db.py**: `deactivate_annotator` — now DELETEs pending/in_progress
  assignments on deactivation, releasing images back to pool.
- **db.py**: `ensure_shuffle_order` — post-insert count verification, returns
  `missing_from_shuffle` field.
- **requirements.txt**: Added `streamlit-cookies-controller==0.0.4`.

### DB Operations

- Wiped all annotators (role=annotator), assignments, annotations.
- Kept images, admins, shuffle order.
- Ran fresh assignment batches to annotators.
- Created admin account: karen (Karen Cichy).
- Backfilled 1,000 stuck assignments from two previously-deactivated annotators
  by manually deleting their pending/in_progress rows.

---

## Earlier (pre-2026-07)

- Initial production deployment on EC2 with nginx + Let's Encrypt TLS.
- AWS Cognito user pools for admin and annotator roles.
- RDS PostgreSQL schema: annotators, jobs, images, assignments, annotations,
  image_shuffle_order, skipped_redo_queue.
- S3 bucket `bean-quality-annotation-combined-5400` with 11,040 images.
- Class-balanced batch of 6,000 images (12 varieties × 500) prepared via
  `scripts/prepare_class_balanced_6000.py`.
