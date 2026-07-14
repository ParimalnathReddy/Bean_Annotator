"""
Prepare the database for the current class-balanced image distribution.

This keeps every account, assignment, annotation, and progress row intact.
It appends only S3 images that are not already registered in the database,
then appends those new images to the existing shuffle order.

Run dry-run:
    python scripts/prepare_class_balanced_6000.py

Run for real:
    python scripts/prepare_class_balanced_6000.py --execute
"""

from __future__ import annotations

import argparse
import os
import random
import secrets
from pathlib import Path

import boto3
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


IMAGE_PREFIX = "images/"
JOB_NAME = "Default"
EXPECTED_IMAGE_COUNT = 11040


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


def list_s3_images(bucket: str, prefix: str = IMAGE_PREFIX) -> list[dict]:
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    rows = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            name = key.rsplit("/", 1)[-1]
            if not name:
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in exts:
                continue
            rows.append({"key": key, "filename": name})
    rows.sort(key=lambda r: r["key"])
    return rows


def fetch_counts(conn) -> dict:
    tables = [
        "annotators",
        "jobs",
        "images",
        "assignments",
        "annotations",
        "image_shuffle_order",
    ]
    counts = {}
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
    return counts


def prepare_database(conn, images: list[dict], execute: bool) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        before = fetch_counts(conn)
        cur.execute("SELECT id FROM annotators WHERE role = 'admin' ORDER BY created_at LIMIT 1")
        admin = cur.fetchone()
        if not admin:
            raise RuntimeError("No admin account found. Create an admin before preparing the image job.")
        admin_id = admin["id"]

        cur.execute(
            "SELECT id FROM jobs WHERE name = %s ORDER BY created_at LIMIT 1",
            (JOB_NAME,),
        )
        job = cur.fetchone()
        if job:
            job_id = job["id"]
        else:
            cur.execute(
                """INSERT INTO jobs (name, description, created_by, total_images)
                   VALUES (%s, %s, %s, 0)
                   RETURNING id""",
                (JOB_NAME, "Default assignment batch prepared from S3 images/.", admin_id),
            )
            job_id = cur.fetchone()["id"]

        cur.execute("SELECT s3_key FROM images")
        known_image_keys = {row["s3_key"] for row in cur.fetchall()}
        new_images = [img for img in images if img["key"] not in known_image_keys]

        cur.execute("SELECT s3_key FROM image_shuffle_order WHERE job_id = %s", (job_id,))
        known_shuffle_keys = {row["s3_key"] for row in cur.fetchall()}
        missing_shuffle_images = [img for img in images if img["key"] not in known_shuffle_keys]

        if not execute:
            return {
                "before": before,
                "after": None,
                "shuffle_seed": None,
                "job_id": job_id,
                "new_image_count": len(new_images),
                "new_shuffle_count": len(missing_shuffle_images),
            }

        if new_images:
            image_values = [
                (job_id, img["filename"], img["key"], admin_id)
                for img in new_images
            ]
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO images (job_id, filename, s3_key, uploaded_by)
                   VALUES %s
                   ON CONFLICT (s3_key) DO NOTHING""",
                image_values,
                template="(%s, %s, %s, %s)",
                page_size=1000,
            )

        shuffle_seed = secrets.token_hex(8)
        cur.execute(
            "SELECT COALESCE(MAX(shuffle_rank), 0) AS max_rank FROM image_shuffle_order WHERE job_id = %s",
            (job_id,),
        )
        start_rank = int(cur.fetchone()["max_rank"] or 0)
        shuffled = list(missing_shuffle_images)
        random.Random(shuffle_seed).shuffle(shuffled)
        shuffle_values = [
            (job_id, img["key"], img["filename"], start_rank + rank, shuffle_seed, admin_id)
            for rank, img in enumerate(shuffled, start=1)
        ]
        if shuffle_values:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO image_shuffle_order
                       (job_id, s3_key, filename, shuffle_rank, shuffle_seed, created_by_admin)
                   VALUES %s
                   ON CONFLICT (job_id, s3_key) DO NOTHING""",
                shuffle_values,
                template="(%s, %s, %s, %s, %s, %s)",
                page_size=1000,
            )

        cur.execute(
            "UPDATE jobs SET total_images = (SELECT COUNT(*) FROM images WHERE job_id = %s) WHERE id = %s",
            (job_id, job_id),
        )
        after = fetch_counts(conn)
        return {
            "before": before,
            "after": after,
            "shuffle_seed": shuffle_seed,
            "job_id": job_id,
            "new_image_count": len(new_images),
            "new_shuffle_count": len(missing_shuffle_images),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually append missing S3 images to the DB.")
    parser.add_argument("--allow-count", type=int, default=EXPECTED_IMAGE_COUNT)
    args = parser.parse_args()

    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    bucket = os.environ.get("S3_BUCKET", "bean-quality-annotation-combined-5400")
    images = list_s3_images(bucket)
    print(f"S3 bucket: {bucket}")
    print(f"S3 prefix: {IMAGE_PREFIX}")
    print(f"S3 image count: {len(images)}")
    if images:
        print(f"First image: {images[0]['key']}")
        print(f"Last image:  {images[-1]['key']}")

    if len(images) != args.allow_count:
        raise SystemExit(
            f"Refusing to continue: expected {args.allow_count} images under {IMAGE_PREFIX}, found {len(images)}."
        )

    conn = psycopg2.connect(**db_config())
    try:
        result = prepare_database(conn, images, args.execute)
        if args.execute:
            conn.commit()
            print("Database prepared.")
            print(f"Job id: {result['job_id']}")
            print(f"Shuffle seed: {result['shuffle_seed']}")
            print(f"New images added: {result['new_image_count']}")
            print(f"New shuffle rows added: {result['new_shuffle_count']}")
            print(f"Before: {result['before']}")
            print(f"After:  {result['after']}")
        else:
            conn.rollback()
            print("Dry run only. No database changes made.")
            print(f"Current counts: {result['before']}")
            print(f"New images that would be added: {result['new_image_count']}")
            print(f"New shuffle rows that would be added: {result['new_shuffle_count']}")
            print(f"Run again with --execute to append missing images from the {len(images)} S3 images.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
