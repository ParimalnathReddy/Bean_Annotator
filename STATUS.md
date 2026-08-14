# Annotation Project Status

Last updated: **2026-08-14**

---

## Current Numbers

| Metric | Count |
|---|---|
| Total images in DB | 11,040 |
| Total annotations saved | 8,190 |
| Completed (labeled) | 5,836 |
| Pending (lovepreet123456's queue) | 4,401 |
| Skipped (no label saved) | 2,354 |

### Label Split (completed annotations)

| Label | Count |
|---|---|
| No splits / cracks | 3,759 |
| Splits / cracks | 2,077 |

---

## Annotator Status

| Annotator | Done | Pending | Skipped |
|---|---|---|---|
| tj_teshome | 656 | 0 | 344 |
| **lovepreet123456** | 636 | **4,401** | 803 |
| carlos_m | 500 | 0 | 0 |
| john | 448 | 0 | 52 |
| olumide_f | 443 | 0 | 57 |
| breanna_m | 410 | 0 | 90 |
| parimal_123 | 406 | 0 | 94 |
| patrick_b | 398 | 0 | 102 |
| cerit_mustafa | 384 | 0 | 116 |
| sharon_h | 383 | 0 | 117 |
| awale_halima | 371 | 0 | 129 |
| jorge_xyz | 340 | 0 | 160 |
| z_marysia | 322 | 0 | 178 |
| ram_neupane | 87 | 0 | 79 |
| karen_c | 50 | 0 | 33 |
| valerio_hoyos | 2 | 0 | 0 |

All annotators except `lovepreet123456` have finished their assigned batches.

---

## Recent Operational Changes (Aug 2026)

### Assignment Consolidation (2026-08-14)
- All pending images from Jorge, Jose, Andrei, Valerio, Ram, Karen were
  released and reassigned to `lovepreet123456`.
- All 112 skipped images from other annotators not yet assigned to
  `lovepreet123456` were added as `skipped_redo` pending assignments.
- Net result: `lovepreet123456` holds all 4,401 remaining images to annotate.
- Every other annotator has 0 pending — they are done.

### Button Rename
- Annotation severity labels renamed: **Good → "No splits / cracks"** (green),
  **Bad → "Splits / cracks"** (red).
- DB `overall_severity` values unchanged: `1` = no splits, `2` = splits/cracks.

### Deactivation Fix
- Annotator deactivation now releases pending/in_progress assignments back to
  the pool automatically.

### Canvas Pan Fix
- Draw mode and Edit mode both support plain drag-to-pan (no Space key needed).
- Click vs drag disambiguated by a 5px threshold.

---

## EC2 Scripts

| Script | Purpose |
|---|---|
| `/opt/bean-annotator/assign_skipped_to_lovepreet.py` | Assigns any newly skipped images from other annotators to `lovepreet123456` as `skipped_redo` pending. Safe to re-run. Logs to `/var/log/bean-assign-skipped.log`. |
| `scripts/prepare_class_balanced_6000.py` | Registers S3 images into DB. |
| `scripts/assign_skipped_redo_to_lovepreet.py` | Earlier version of the skipped redo script. |

### Setting Up Nightly Cron (run once on EC2)

```bash
(crontab -l 2>/dev/null | grep -v assign_skipped; \
  echo "0 2 * * * set -a && source /opt/bean-annotator/.env && set +a && \
  /opt/bean-annotator/venv/bin/python3 /opt/bean-annotator/assign_skipped_to_lovepreet.py") \
  | crontab -
```

---

## Known Issues

| Issue | Status |
|---|---|
| Cookie-based session persistence (stay logged in on refresh) | 🔴 Unresolved — `streamlit-cookies-controller` writes cookie but reads always return None. Debug `AUTH_DEBUG` logs still deployed in `auth.py`. |
| AUTH_DEBUG print statements in production | 🟡 Remove once cookie issue is fixed. |

---

## Infrastructure

| Resource | Value |
|---|---|
| EC2 instance | `54.209.181.30` |
| EC2 security group | `sg-01ae7845d17ac4192` |
| RDS endpoint | `bean-annotator-db.ck1kkik42dzg.us-east-1.rds.amazonaws.com` |
| S3 bucket | `bean-quality-annotation-combined-5400` |
| Admin URL | `beanlab-admin.mooo.com` |
| Annotator URL | `beanlab.mooo.com` |
| SSH key | `~/.ssh/bean-annotator-key.pem` |
