# Deployment

## Production Architecture

Production runs on an Ubuntu EC2 instance.

Known production app directory:

```text
/opt/bean-annotator
```

Systemd services:

```text
bean-annotator
bean-admin
```

Expected ports:

- Annotator app: `8501`
- Admin app: `8502`

## Required Environment

The production app directory must include a `.env` file. Do not commit this file.

Required values:

```text
AWS_REGION=us-east-1
S3_BUCKET=bean-quality-annotation-combined-5400
DB_HOST=<rds-endpoint>
DB_PORT=5432
DB_NAME=bean_annotator
DB_USER=<db-user>
DB_PASSWORD=<db-password>
COGNITO_USER_POOL_ID=<user-pool-id>
COGNITO_CLIENT_ID=<client-id>
COGNITO_CLIENT_SECRET=<client-secret-if-used>
```

## Manual Restart

SSH from local machine:

```bash
ssh -i /Users/parimal/.ssh/bean-annotator-key.pem ubuntu@54.209.181.30
```

Restart services:

```bash
cd /opt/bean-annotator
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart bean-annotator bean-admin
sudo systemctl status bean-admin --no-pager
sudo systemctl status bean-annotator --no-pager
```

## GitHub Actions Deployment

Workflow file:

```text
.github/workflows/deploy.yml
```

Trigger:

```text
push to main
```

Required GitHub repository secrets:

```text
EC2_HOST
EC2_USER
EC2_SSH_KEY
```

Recommended production state:

- `/opt/bean-annotator` should be a Git checkout.
- The production `.env` should exist only on EC2.
- The virtual environment should be named either `venv` or `.venv`; the workflow
  supports both.

Deployment steps:

1. SSH to EC2.
2. `cd /opt/bean-annotator`.
3. `git pull origin main`.
4. Activate virtual environment.
5. `pip install -r requirements.txt`.
6. Install/update nightly skipped-redo cron.
7. Restart `bean-annotator` and `bean-admin`.

## Production Logs

Systemd logs:

```bash
journalctl -u bean-admin -n 100 --no-pager
journalctl -u bean-annotator -n 100 --no-pager
```

Nightly skipped-redo log:

```bash
tail -n 100 /opt/bean-annotator/logs/skipped_redo_lovepreet.log
```

## Deployment Pitfalls

- If EC2 is not a Git checkout, `git pull` fails with
  `fatal: not a git repository`.
- If the workflow uses `.venv` but EC2 has `venv`, deployment fails at activate.
- If schema migrations are applied but old code is running, assignment may fail
  with `there is no unique or exclusion constraint matching the ON CONFLICT
  specification`.
- Never overwrite production `.env` from local rsync.

