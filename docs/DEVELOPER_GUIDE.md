# Developer Guide

## Prerequisites

- Python 3.10+ recommended for production parity.
- Access to AWS credentials with S3, Cognito, and RDS permissions.
- Network access to the RDS instance.
- Local `.env` file with production or development configuration.

## Setup

```bash
cd /Users/parimal/PROJECTS/Annotation_GUI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Environment Variables

Create `.env`:

```text
AWS_REGION=us-east-1
S3_BUCKET=bean-quality-annotation-combined-5400
DB_HOST=<rds-endpoint>
DB_PORT=5432
DB_NAME=bean_annotator
DB_USER=<db-user>
DB_PASSWORD=<db-password>
COGNITO_USER_POOL_ID=<pool-id>
COGNITO_CLIENT_ID=<client-id>
COGNITO_CLIENT_SECRET=<client-secret-if-enabled>
```

`.env` is intentionally ignored by Git.

## Run Locally

Annotator app:

```bash
python -m streamlit run annotate_beans.py --server.port 8501
```

Admin app:

```bash
python -m streamlit run admin_app.py --server.port 8502
```

## Project Structure

```text
Annotation_GUI/
  admin_app.py                         Admin dashboard
  annotate_beans.py                    Annotator dashboard shell
  annotation.py                        Annotation UI and polygon canvas
  auth.py                              Cognito login, JWT verification, cookies
  db.py                                PostgreSQL queries and transaction helpers
  storage.py                           S3 helpers
  requirements.txt                     Python dependencies
  assets/                              MSU Bean Lab visual assets
  migrations/                          SQL schema migrations
  scripts/
    prepare_class_balanced_6000.py     Append S3 images to DB/shuffle order
    assign_skipped_redo_to_lovepreet.py Nightly skipped-redo assignment
    recover_assignments_from_restored_db.py Historical recovery utility
  docs/                                Project documentation
  .github/workflows/deploy.yml         GitHub Actions EC2 deployment
```

## Adding Fresh Data

1. Upload matching image and boundary files to S3:

```text
images/<filename>
boundary_images/<filename>
```

2. Verify S3 counts.
3. Run a dry run:

```bash
python scripts/prepare_class_balanced_6000.py --allow-count <expected-total>
```

4. Execute:

```bash
python scripts/prepare_class_balanced_6000.py --allow-count <expected-total> --execute
```

5. Restart the admin app if needed.

## Creating Annotators

Use the admin dashboard Team page. Do not create Cognito users manually unless
you also create the corresponding database row.

Usernames are permanent. If an annotator is deactivated, choose a different
username for any future person to preserve audit history.

## Assigning Images

Use Assign Images:

- Assign by count for normal distribution.
- Pick specific images for targeted cases.
- Adjust assignments only to reduce pending work.

Count-based assignment always uses the persisted shuffle order.

## Common Debug Commands

Service status:

```bash
sudo systemctl status bean-admin --no-pager
sudo systemctl status bean-annotator --no-pager
```

Recent logs:

```bash
journalctl -u bean-admin -n 100 --no-pager
journalctl -u bean-annotator -n 100 --no-pager
```

Check deployment folder:

```bash
cd /opt/bean-annotator
git status -sb
```

## Coding Guidelines

- Keep database writes in `db.py`.
- Keep S3 access in `storage.py`.
- Keep Cognito/auth behavior in `auth.py`.
- Keep admin workflow in `admin_app.py`.
- Keep annotation workflow and canvas behavior in `annotation.py`.
- Prefer adding migrations for schema changes instead of ad hoc SQL.

