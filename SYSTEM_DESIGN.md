# System Design

The production system design is documented in the `docs/` directory.

Current production is an EC2-hosted Streamlit deployment backed by AWS Cognito,
Amazon RDS PostgreSQL, and Amazon S3.

## Canonical Documents

- [Architecture](docs/ARCHITECTURE.md): end-to-end system workflow.
- [Database](docs/DATABASE.md): tables, relationships, indexes, and data flow.
- [Backend](docs/BACKEND.md): Python service modules and internal logic.
- [Frontend And Dashboards](docs/FRONTEND_DASHBOARDS.md): admin and annotator UI.
- [Data Pipelines](docs/DATA_PIPELINES.md): S3 registration, assignment, annotation,
  and skipped-redo workflows.
- [Authentication And Authorization](docs/AUTHORIZATION.md): Cognito, roles, and
  permissions.
- [Deployment](docs/DEPLOYMENT.md): EC2, systemd, GitHub Actions, environment
  configuration, logs, and pitfalls.
- [Developer Guide](docs/DEVELOPER_GUIDE.md): local setup and onboarding.
- [Testing And Operations](docs/TESTING_OPERATIONS.md): validation checklists and
  health queries.
- [Decisions And Limitations](docs/DECISIONS_LIMITATIONS.md): tradeoffs, assumptions,
  limitations, and future work.

