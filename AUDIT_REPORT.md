# Operational Audit Summary

This file is a short entry point for audit and operations documentation. The
detailed current documentation now lives in `docs/`.

## Current Audit-Relevant Guarantees

- All assignment and annotation history is stored in Postgres.
- Annotator deactivation is a soft delete; historical assignments and
  annotations are retained.
- Usernames are permanently reserved, including deactivated accounts.
- Primary image assignments are globally unique per image.
- Skipped redo assignments are separate records linked to the original skipped
  assignment.
- Count-based assignment uses a persistent shuffled order for repeatability.
- Admins have global visibility, but only the creator admin can manage an
  annotator account.
- Assignment reports are mirrored to S3 after assignment changes.
- Annotation JSON mirrors are written to S3 after annotation saves, while
  Postgres remains the source of truth.

## Detailed References

- [Architecture](docs/ARCHITECTURE.md)
- [Database](docs/DATABASE.md)
- [Frontend And Dashboards](docs/FRONTEND_DASHBOARDS.md)
- [Data Pipelines](docs/DATA_PIPELINES.md)
- [Testing And Operations](docs/TESTING_OPERATIONS.md)
- [Decisions And Limitations](docs/DECISIONS_LIMITATIONS.md)

