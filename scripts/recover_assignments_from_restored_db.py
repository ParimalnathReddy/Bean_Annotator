"""
Recover assignments/annotations from a temporary restored RDS instance.

This script assumes the current DB already has the full S3 image set registered.
It copies historical assignments from the restored DB, remapping image_id by s3_key,
and preserves assignment ids so annotations continue to reference them.

Dry run:
    python scripts/recover_assignments_from_restored_db.py --restore-host <endpoint>

Execute:
    python scripts/recover_assignments_from_restored_db.py --restore-host <endpoint> --execute
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


def db_config(host: str | None = None) -> dict:
    return {
        "host": host or os.environ.get("DB_HOST", "bean-annotator-db.ck1kkik42dzg.us-east-1.rds.amazonaws.com"),
        "port": int(os.environ.get("DB_PORT", 5432)),
        "dbname": os.environ.get("DB_NAME", "bean_annotator"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "sslmode": "require",
        "connect_timeout": 20,
    }


def count_table(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def load_restored_assignments(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT a.id,
                      i.s3_key,
                      a.annotator_id,
                      a.status,
                      a.assigned_at,
                      a.last_image_idx,
                      a.last_active_at,
                      a.assigned_by_admin
               FROM assignments a
               JOIN images i ON i.id = a.image_id
               ORDER BY a.assigned_at, a.id"""
        )
        return [dict(r) for r in cur.fetchall()]


def load_restored_annotations(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT id,
                      assignment_id,
                      annotator_id,
                      overall_severity,
                      overall_notes,
                      defects,
                      skip_reason,
                      annotation_version,
                      saved_at
               FROM annotations
               ORDER BY saved_at, id"""
        )
        return [dict(r) for r in cur.fetchall()]


def recover(current_conn, restored_conn, execute: bool) -> dict:
    before = {
        "current_assignments": count_table(current_conn, "assignments"),
        "current_annotations": count_table(current_conn, "annotations"),
        "restored_assignments": count_table(restored_conn, "assignments"),
        "restored_annotations": count_table(restored_conn, "annotations"),
    }

    restored_assignments = load_restored_assignments(restored_conn)
    restored_annotations = load_restored_annotations(restored_conn)

    with current_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, s3_key FROM images")
        current_image_ids = {r["s3_key"]: r["id"] for r in cur.fetchall()}

        missing_image_keys = sorted({r["s3_key"] for r in restored_assignments if r["s3_key"] not in current_image_ids})
        if missing_image_keys:
            raise RuntimeError(f"{len(missing_image_keys)} restored assignment images are missing in current DB.")

        assignment_values = [
            (
                r["id"],
                current_image_ids[r["s3_key"]],
                r["annotator_id"],
                r["status"],
                r["assigned_at"],
                r["last_image_idx"],
                r["last_active_at"],
                r["assigned_by_admin"],
            )
            for r in restored_assignments
        ]
        annotation_values = [
            (
                r["id"],
                r["assignment_id"],
                r["annotator_id"],
                r["overall_severity"],
                r["overall_notes"],
                psycopg2.extras.Json(r["defects"] or []),
                r["skip_reason"],
                r["annotation_version"],
                r["saved_at"],
            )
            for r in restored_annotations
        ]

        if not execute:
            return {
                "before": before,
                "after": None,
                "assignments_to_copy": len(assignment_values),
                "annotations_to_copy": len(annotation_values),
            }

        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO assignments
                   (id, image_id, annotator_id, status, assigned_at,
                    last_image_idx, last_active_at, assigned_by_admin)
               VALUES %s
               ON CONFLICT (id) DO NOTHING""",
            assignment_values,
            page_size=1000,
        )

        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO annotations
                   (id, assignment_id, annotator_id, overall_severity, overall_notes,
                    defects, skip_reason, annotation_version, saved_at)
               VALUES %s
               ON CONFLICT (assignment_id) DO UPDATE
               SET overall_severity = EXCLUDED.overall_severity,
                   overall_notes = EXCLUDED.overall_notes,
                   defects = EXCLUDED.defects,
                   skip_reason = EXCLUDED.skip_reason,
                   annotation_version = EXCLUDED.annotation_version,
                   saved_at = EXCLUDED.saved_at""",
            annotation_values,
            page_size=1000,
        )

    after = {
        "current_assignments": count_table(current_conn, "assignments"),
        "current_annotations": count_table(current_conn, "annotations"),
    }
    return {
        "before": before,
        "after": after,
        "assignments_to_copy": len(assignment_values),
        "annotations_to_copy": len(annotation_values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-host", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    current_conn = psycopg2.connect(**db_config())
    restored_conn = psycopg2.connect(**db_config(args.restore_host))
    try:
        result = recover(current_conn, restored_conn, args.execute)
        if args.execute:
            current_conn.commit()
            print("Recovery copied historical assignments and annotations.")
        else:
            current_conn.rollback()
            print("Dry run only. No current DB changes made.")
        print(result)
    except Exception:
        current_conn.rollback()
        raise
    finally:
        current_conn.close()
        restored_conn.close()


if __name__ == "__main__":
    main()
