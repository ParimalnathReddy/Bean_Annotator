"""
storage.py — S3 read/write helpers for Bean Annotator.
"""

import os
import io
import csv
import json
import boto3
from botocore.exceptions import ClientError

_DEFAULT_BUCKET = "bean-quality-annotation-combined-5400"
_DEFAULT_REGION = "us-east-1"

# Read bucket/region as functions so the value is always current, even if
# this module was imported before load_dotenv() ran in the Streamlit process.
def _bucket() -> str:
    return os.environ.get("S3_BUCKET", _DEFAULT_BUCKET)

def _region() -> str:
    return os.environ.get("AWS_REGION", _DEFAULT_REGION)

_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=_region())
    return _s3


# ── Image folder constants ─────────────────────────────────────────────────────

CROP_BANK_PREFIX   = "images/"           # plain bean images  (key stored in DB)
CROP_BANK_BOUNDARY = "boundary_images/"  # boundary overlay   (shown to annotators)


def boundary_key(s3_key: str) -> str:
    """images/foo.png  →  boundary_images/foo.png"""
    if s3_key.startswith(CROP_BANK_PREFIX):
        return CROP_BANK_BOUNDARY + s3_key[len(CROP_BANK_PREFIX):]
    return s3_key


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_image(file_bytes: bytes, job_id: str, filename: str) -> str:
    key = f"images/{job_id}/{filename}"
    _client().put_object(
        Bucket=_bucket(), Key=key, Body=file_bytes,
        ContentType=_guess_content_type(filename),
    )
    return key


def upload_annotation_json(data: dict, job_id: str, annotator: dict, filename: str) -> str:
    username = annotator.get("username") or annotator.get("name") or annotator["id"]
    stem = os.path.splitext(filename)[0]
    key = f"annotations/{job_id}/annotators/{_safe_prefix(username)}/{_safe_prefix(stem)}.json"
    _client().put_object(
        Bucket=_bucket(), Key=key,
        Body=json.dumps(data, default=str).encode(),
        ContentType="application/json",
    )
    return key


# ── Download ──────────────────────────────────────────────────────────────────

def download_image(s3_key: str) -> bytes:
    resp = _client().get_object(Bucket=_bucket(), Key=s3_key)
    return resp["Body"].read()


def download_annotation_json(s3_key: str) -> dict | None:
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=s3_key)
        return json.loads(resp["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


# ── Presigned URLs ────────────────────────────────────────────────────────────

def presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": s3_key},
        ExpiresIn=expires_in,
    )


# ── Listing ───────────────────────────────────────────────────────────────────

def list_all_images(prefix: str = CROP_BANK_PREFIX) -> list[dict]:
    """
    List every image file in the bucket under `prefix`.
    Returns list of {key, filename, size_kb, last_modified}.
    """
    _EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    paginator = _client().get_paginator("list_objects_v2")
    results = []
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            key  = obj["Key"]
            name = key.split("/")[-1]
            if not name:
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in _EXTS:
                continue
            results.append({
                "key":           key,
                "filename":      name,
                "size_kb":       round(obj["Size"] / 1024, 1),
                "last_modified": obj["LastModified"],
            })
    results.sort(key=lambda r: r["key"])
    return results


def list_images_for_job(job_id: str) -> list[str]:
    prefix = f"images/{job_id}/"
    paginator = _client().get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


# ── Assignment report ─────────────────────────────────────────────────────────

REPORT_KEY = "reports/assignment_report.csv"
_REPORT_COLS = ["bean_id", "image_id", "filename", "s3_key", "batch_name",
                "annotator_id", "annotator_name", "assigned_by_admin_id",
                "assigned_by", "shuffle_rank", "shuffle_seed",
                "assignment_kind", "source_assignment_id", "status",
                "assigned_at", "last_active_at"]


def _assignment_report_key(admin_id: str | None = None) -> str:
    if not admin_id:
        return REPORT_KEY
    safe_admin_id = "".join(c for c in str(admin_id) if c.isalnum() or c in "-_")
    return f"reports/assignment_report_{safe_admin_id}.csv"


def _safe_prefix(value: str) -> str:
    safe = "".join(c for c in str(value).strip().lower() if c.isalnum() or c in "-_")
    return safe or "annotator"


def save_assignment_report(rows: list[dict], admin_id: str | None = None) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_REPORT_COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    key = _assignment_report_key(admin_id)
    _client().put_object(
        Bucket=_bucket(), Key=key,
        Body=buf.getvalue().encode(), ContentType="text/csv",
    )
    return key


def save_annotator_assignment_report(rows: list[dict], annotator: dict) -> str:
    username = annotator.get("username") or annotator.get("name") or annotator["id"]
    key = f"assignments/{_safe_prefix(username)}/assignment_report.csv"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_REPORT_COLS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _client().put_object(
        Bucket=_bucket(), Key=key,
        Body=buf.getvalue().encode(), ContentType="text/csv",
    )
    return key


def download_assignment_report(admin_id: str | None = None) -> bytes | None:
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=_assignment_report_key(admin_id))
        return resp["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def upload_export_csv(csv_bytes: bytes, job_id: str, filename: str) -> str:
    key = f"exports/{job_id}/{filename}"
    _client().put_object(
        Bucket=_bucket(), Key=key, Body=csv_bytes, ContentType="text/csv",
    )
    return key


# ── Util ──────────────────────────────────────────────────────────────────────

def _guess_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png",
        "tif": "image/tiff", "tiff": "image/tiff",
    }.get(ext, "application/octet-stream")
