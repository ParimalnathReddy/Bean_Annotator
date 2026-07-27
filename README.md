# Bean Quality Annotation GUI

Production Streamlit applications for the MSU Bean Lab image annotation workflow.
The system lets admins create annotators, distribute bean images from S3, monitor
progress globally, export results, and route skipped images to a redo annotator.
Annotators sign in, inspect each assigned image, mark it Good, Bad, or Skip, and
draw polygon defects for bad images.

## Applications

| App | Entrypoint | Port | Audience | Purpose |
| --- | --- | --- | --- | --- |
| Annotator Dashboard | `annotate_beans.py` | `8501` | Annotators | Image review, rating, polygon defects, skip flow |
| Admin Dashboard | `admin_app.py` | `8502` | Admins | Team, assignment, progress, exports, audit reports |

## Current Production Shape

```text
Browser
  -> Streamlit apps on EC2
  -> AWS Cognito for login and roles
  -> Amazon RDS PostgreSQL for users, images, assignments, progress, annotations
  -> Amazon S3 for source images, boundary images, JSON mirrors, assignment reports
```

The active S3 bucket is configured by `S3_BUCKET` and currently defaults to
`bean-quality-annotation-combined-5400`. Images live under `images/`; boundary
overlay images shown in the annotator UI live under `boundary_images/`.

## Documentation

Start here:

- [Architecture](docs/ARCHITECTURE.md)
- [Database](docs/DATABASE.md)
- [Backend](docs/BACKEND.md)
- [Frontend And Dashboards](docs/FRONTEND_DASHBOARDS.md)
- [Data Pipelines](docs/DATA_PIPELINES.md)
- [Authentication And Authorization](docs/AUTHORIZATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [Testing And Operations](docs/TESTING_OPERATIONS.md)
- [Decisions And Limitations](docs/DECISIONS_LIMITATIONS.md)

## Local Setup

```bash
cd /Users/parimal/PROJECTS/Annotation_GUI
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a local `.env` file with the required AWS, Cognito, S3, and database
values. See [Developer Guide](docs/DEVELOPER_GUIDE.md) for the full list.

Run the annotator app:

```bash
python -m streamlit run annotate_beans.py --server.port 8501
```

Run the admin app:

```bash
python -m streamlit run admin_app.py --server.port 8502
```

## Production Deployment

Production runs on EC2 under `/opt/bean-annotator` using systemd services:

- `bean-annotator`
- `bean-admin`

Future deployments should use GitHub Actions. The workflow is:

```text
git push origin main
  -> .github/workflows/deploy.yml
  -> SSH to EC2
  -> git pull
  -> install requirements
  -> install nightly skipped-redo cron
  -> restart services
```

See [Deployment](docs/DEPLOYMENT.md) before changing production.

