# Current State

Last verified: **2026-08-25**

---

## What This Project Is

A production Streamlit annotation system for MSU Bean Lab. Human annotators review
individual bean crop images and label each one as **"No splits / cracks"** (clean)
or **"Splits / cracks"** (defective), optionally drawing polygon outlines over
defect regions. The resulting labeled dataset is used to retrain a CNN bean
quality classifier.

---

## Annotation Progress Right Now

### Overall (as of 2026-08-25)

| Metric | Count |
|---|---|
| Total images in DB | 11,040 |
| Total labeled (done) | **6,554** |
| Pending (lovepreet123456 queue) | **3,285** |
| Skipped (no label saved) | 1,200 |
| Total annotation records | 9,305 |

### Label Split

| Label | Count | % of labeled |
|---|---|---|
| No splits / cracks (severity=1) | 4,336 | 66% |
| Splits / cracks (severity=2) | 2,218 | 34% |

### By Image Batch

| Batch | Total | Done | Pending | Skipped |
|---|---|---|---|---|
| Class-balanced (12 varieties × 500) | 6,000 | 4,182 | 1,142 | 676 |
| Other batches (batch_001, pooled_2000, etc.) | 5,040 | 2,372 | 2,143 | 524 |

### Annotator Status

| Annotator | Done | Pending | Status |
|---|---|---|---|
| tj_teshome | 656 | 0 | ✅ Done |
| carlos_m | 500 | 0 | ✅ Done |
| john | 448 | 0 | ✅ Done |
| olumide_f | 443 | 0 | ✅ Done |
| breanna_m | 410 | 0 | ✅ Done |
| parimal_123 | 406 | 0 | ✅ Done |
| patrick_b | 398 | 0 | ✅ Done |
| cerit_mustafa | 384 | 0 | ✅ Done |
| sharon_h | 383 | 0 | ✅ Done |
| awale_halima | 371 | 0 | ✅ Done |
| jorge_xyz | 340 | 0 | ✅ Done |
| z_marysia | 322 | 0 | ✅ Done |
| ram_neupane | 87 | 0 | ✅ Done |
| karen_c | 50 | 0 | ✅ Done |
| valerio_hoyos | 2 | 0 | ✅ Done |
| **lovepreet123456** | ~1,354+ | **3,285** | 🔄 Active |

**All remaining work belongs to lovepreet123456. No other annotator has pending work.**

---

## Dataset Structure

### 12 Bean Varieties (class-balanced batch)

BLACK, CRAN, DRK, GN, KIDNEY, LRK, NAVY, OTEBO, PINTO, SMR, WK, YELLOW

Each variety: **500 images** sampled across 4 difficulty buckets:
- `suspect` (200): model was ~50-70% confident — edge cases
- `high_bad` (125): model was >90% confident it's defective
- `boundary_low` (100): low confidence, near decision boundary
- `good_control` (75): model was confident it's clean

Variety metadata is in `s3://bean-quality-annotation-combined-5400/annotation_manifest.csv`.
The `images` table in DB does **not** have a variety column — join on filename to get variety.

### Other 5,040 Images

Earlier batches (batch_001, pooled_2000). No variety metadata tracked.
Usable for binary defect classification only, not variety-specific training.

---

## Source of Truth: DB, Not S3

**Important:** S3 JSON annotation mirrors are **incomplete and stale**.
Do not use S3 JSON file counts for annotation statistics.

- S3 count: ~4,642 unique crops (stale, from old data before DB wipes)
- DB count: **6,554 unique labeled images** ← use this
- Every image has exactly **1 annotator** (no multi-annotator overlap)

Always query the DB for accurate counts.

---

## Lovepreet Account Situation

There are 5 accounts with "lovepreet" in the username:

| Username | Active | Role | Assignments |
|---|---|---|---|
| `lovepreet123456` | ✅ | annotator | **All active work** |
| `lovepreet_k` | ✅ | annotator | 0 (cleared) |
| `lovepreet` | ✅ | admin | 0 |
| `lovepreet_s` | ❌ | annotator | 0 |
| `lovepreet1234` | ❌ | annotator | 0 |

**`lovepreet123456` is the active annotator doing all remaining work.**
All pending images from other annotators (Jorge, Jose, Andrei, Valerio, Ram, Karen)
were consolidated into this account on 2026-08-14.

---

## Infrastructure

| Resource | Value |
|---|---|
| EC2 | `54.209.181.30` (ubuntu) |
| EC2 security group | `sg-01ae7845d17ac4192` |
| RDS endpoint | `bean-annotator-db.ck1kkik42dzg.us-east-1.rds.amazonaws.com` |
| DB name | `bean_annotator` |
| S3 bucket | `bean-quality-annotation-combined-5400` |
| Admin dashboard | `beanlab-admin.mooo.com` (port 8502) |
| Annotator dashboard | `beanlab.mooo.com` (port 8501) |
| SSH key | `~/.ssh/bean-annotator-key.pem` |
| EC2 app dir | `/opt/bean-annotator/` |
| EC2 venv | `/opt/bean-annotator/venv/` |
| EC2 env file | `/opt/bean-annotator/.env` |
| Systemd services | `bean-admin`, `bean-annotator` |

**Note:** EC2 SSH requires your current IP whitelisted on sg-01ae7845d17ac4192 port 22.
Home IPs rotate — re-authorize before SSHing:
```bash
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id sg-01ae7845d17ac4192 \
  --protocol tcp --port 22 --cidr "${MY_IP}/32"
```

---

## EC2 Scripts

| Script | Location | Purpose |
|---|---|---|
| DB image registration | `scripts/prepare_class_balanced_6000.py` | Register S3 images into DB |
| Skipped redo (app) | `scripts/assign_skipped_redo_to_lovepreet.py` | Official skipped redo pipeline |
| Skipped assign (ad hoc) | `/opt/bean-annotator/assign_skipped_to_lovepreet.py` | Ad-hoc EC2 script; assigns newly-skipped images from others to lovepreet123456 |

The ad-hoc EC2 script (`assign_skipped_to_lovepreet.py`) was created manually during
this session. It is **not in git**. The nightly cron for it was never set up
(permission denied during setup). To enable:

```bash
# Run on EC2
(crontab -l 2>/dev/null | grep -v assign_skipped; \
  echo "0 2 * * * set -a && source /opt/bean-annotator/.env && set +a && \
  /opt/bean-annotator/venv/bin/python3 /opt/bean-annotator/assign_skipped_to_lovepreet.py") \
  | crontab -
```

---

## Known Issues

| Issue | Severity | Status |
|---|---|---|
| Cookie-based session persistence broken | High | 🔴 Unresolved — `streamlit-cookies-controller` writes cookie (confirmed by AUTH_DEBUG log) but reads always return None. Users lose session on every hard browser refresh. |
| AUTH_DEBUG print statements in production | Low | 🟡 Still deployed in `auth.py`. Remove once cookie issue fixed. |
| S3 JSON mirrors incomplete | Low | 🟡 4,642 JSON files vs 6,554 DB records. Old files from pre-wipe batches exist in S3. Do not use S3 for counts. |
| Ad-hoc EC2 script not in git | Low | 🟡 `/opt/bean-annotator/assign_skipped_to_lovepreet.py` exists on EC2 only. |
| Nightly cron not set up | Low | 🟡 Skipped-redo nightly cron was never installed on EC2. |
| `lovepreet_k` has 0 assignments but is active | Low | 🟡 Cleanup: consider deactivating unused lovepreet accounts. |

---

## Do NOT Revert These

1. **INNER JOIN fix in `db.py`** (`get_unassigned_images_in_shuffle_order`):
   Changed from `LEFT JOIN images` to `INNER JOIN images i ON i.s3_key = so.s3_key`
   without `AND i.job_id = so.job_id`. Reverting breaks image pool assignment.

2. **Deactivation releases pending assignments**: `deactivate_annotator()` in `db.py`
   now DELETEs pending/in_progress assignments on deactivation. Do not remove.

3. **Button labels**: SEVERITY dict uses `"No splits / cracks"` and `"Splits / cracks"`.
   DB stores `overall_severity = 1` (clean) or `2` (defective). Do not rename back.

4. **Assignment consolidation to lovepreet123456**: All 3,285 pending images
   now belong to lovepreet123456. Do not reassign away from this account without
   deliberate decision.

---

## Next Steps

1. **lovepreet123456 finishes remaining 3,285 images** — no action needed, just wait.
2. **Fix cookie session persistence** — diagnose why `streamlit-cookies-controller`
   reads return None despite write succeeding. Check browser console `document.cookie`
   after login.
3. **Remove AUTH_DEBUG prints** from `auth.py` once cookie issue resolved.
4. **Set up nightly cron** on EC2 for skipped redo assignment (command above).
5. **Export for training**: once lovepreet123456 is done, export from DB (not S3)
   joining with `annotation_manifest.csv` for variety labels.
6. **Deactivate unused lovepreet accounts**: `lovepreet_k`, `lovepreet_s`, `lovepreet1234`.
