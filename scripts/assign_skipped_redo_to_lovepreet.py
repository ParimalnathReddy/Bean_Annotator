"""
Assign skipped images from finished annotators to Lovepreet for redo/review.

Rules:
- Original skipped assignments remain untouched for audit history.
- A new assignment row is created for Lovepreet with assignment_kind='skipped_redo'.
- Each original skipped assignment can be queued only once.
- Only annotators with no primary pending/in_progress assignments are considered finished.

Dry run:
    python scripts/assign_skipped_redo_to_lovepreet.py

Execute:
    python scripts/assign_skipped_redo_to_lovepreet.py --execute
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


TARGET_USERNAME = "lovepreet123456"
DEFAULT_AUDIT_CSV = "logs/skipped_redo_lovepreet_runs.csv"
AUDIT_COLUMNS = [
    "run_started_at_utc",
    "mode",
    "target_username",
    "candidate_count",
    "assigned_count",
    "by_original_annotator_json",
]


def db_config() -> dict:
    return {
        "host": os.environ.get("DB_HOST", "bean-annotator-db.ck1kkik42dzg.us-east-1.rds.amazonaws.com"),
        "port": int(os.environ.get("DB_PORT", 5432)),
        "dbname": os.environ.get("DB_NAME", "bean_annotator"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "sslmode": "require",
        "connect_timeout": 20,
    }


def fetch_target(cur) -> dict:
    cur.execute(
        """SELECT *
           FROM annotators
           WHERE lower(username) = lower(%s)
             AND role = 'annotator'
             AND is_active = true
           LIMIT 1""",
        (TARGET_USERNAME,),
    )
    target = cur.fetchone()
    if not target:
        raise RuntimeError(f'Active annotator "{TARGET_USERNAME}" was not found.')
    return dict(target)


def fetch_candidates(cur) -> list[dict]:
    cur.execute(
        """WITH finished_annotators AS (
               SELECT annotator_id
               FROM assignments
               WHERE assignment_kind = 'primary'
               GROUP BY annotator_id
               HAVING COUNT(*) FILTER (WHERE status IN ('pending', 'in_progress')) = 0
           )
           SELECT orig.id AS original_assignment_id,
                  orig.image_id,
                  orig.annotator_id AS original_annotator_id,
                  orig.assigned_by_admin,
                  img.filename,
                  img.s3_key,
                  ann.name AS original_annotator_name,
                  ann.username AS original_annotator_username
           FROM assignments orig
           JOIN finished_annotators fin ON fin.annotator_id = orig.annotator_id
           JOIN images img ON img.id = orig.image_id
           JOIN annotators ann ON ann.id = orig.annotator_id
           LEFT JOIN skipped_redo_queue q ON q.original_assignment_id = orig.id
           WHERE orig.assignment_kind = 'primary'
             AND orig.status = 'skipped'
             AND q.id IS NULL
           ORDER BY ann.name, orig.assigned_at, orig.id"""
    )
    return [dict(r) for r in cur.fetchall()]


def assign_redo(conn, execute: bool) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        target = fetch_target(cur)
        candidates = fetch_candidates(cur)
        if not execute:
            return {
                "target": target["username"],
                "candidates": len(candidates),
                "assigned": 0,
                "by_original_annotator": _counts_by_annotator(candidates),
            }

        assigned = 0
        for row in candidates:
            cur.execute(
                """INSERT INTO assignments
                       (image_id, annotator_id, assigned_by_admin, status,
                        assignment_kind, source_assignment_id, metadata)
                   VALUES (%s, %s, %s, 'pending', 'skipped_redo', %s, %s::jsonb)
                   ON CONFLICT (source_assignment_id)
                       WHERE assignment_kind = 'skipped_redo'
                   DO NOTHING
                   RETURNING id, assigned_at""",
                (
                    row["image_id"],
                    target["id"],
                    row["assigned_by_admin"],
                    row["original_assignment_id"],
                    psycopg2.extras.Json(
                        {
                            "reason": "redo skipped image",
                            "original_annotator_id": str(row["original_annotator_id"]),
                            "original_annotator_username": row["original_annotator_username"],
                        }
                    ),
                ),
            )
            inserted = cur.fetchone()
            if not inserted:
                continue
            cur.execute(
                """INSERT INTO skipped_redo_queue
                       (original_assignment_id, redo_assignment_id, image_id,
                        original_annotator_id, redo_annotator_id, queued_by,
                        assigned_at, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'assigned')
                   ON CONFLICT (original_assignment_id) DO NOTHING""",
                (
                    row["original_assignment_id"],
                    inserted["id"],
                    row["image_id"],
                    row["original_annotator_id"],
                    target["id"],
                    row["assigned_by_admin"],
                    inserted["assigned_at"],
                ),
            )
            assigned += cur.rowcount

        return {
            "target": target["username"],
            "candidates": len(candidates),
            "assigned": assigned,
            "by_original_annotator": _counts_by_annotator(candidates),
        }


def _counts_by_annotator(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['original_annotator_name']} ({row['original_annotator_username']})"
        counts[key] = counts.get(key, 0) + 1
    return counts


def append_audit_csv(result: dict, execute: bool, run_started_at: datetime, csv_path: Path) -> None:
    """Append one structured audit row for each script run."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    row = {
        "run_started_at_utc": run_started_at.isoformat(),
        "mode": "execute" if execute else "dry_run",
        "target_username": result["target"],
        "candidate_count": int(result["candidates"]),
        "assigned_count": int(result["assigned"]),
        "by_original_annotator_json": json.dumps(
            result["by_original_annotator"],
            sort_keys=True,
        ),
    }
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--audit-csv",
        default=DEFAULT_AUDIT_CSV,
        help="Append a per-run CSV audit row to this path.",
    )
    args = parser.parse_args()

    run_started_at = datetime.now(timezone.utc)
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    conn = psycopg2.connect(**db_config())
    try:
        result = assign_redo(conn, args.execute)
        if args.execute:
            conn.commit()
            print("Skipped redo assignments created.")
        else:
            conn.rollback()
            print("Dry run only. No assignments created.")
        append_audit_csv(result, args.execute, run_started_at, Path(args.audit_csv))
        print(f"Audit CSV updated: {args.audit_csv}")
        print(result)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
