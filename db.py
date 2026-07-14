"""
db.py — PostgreSQL connection and all query functions for Bean Annotator.
"""

import json
import os
import random
import secrets
import threading
import psycopg2
import psycopg2.extras
import psycopg2.pool
from contextlib import contextmanager

# ── Connection config — read on every call so load_dotenv() always wins ───────

def _db_config() -> dict:
    return {
        "host":     os.environ.get("DB_HOST", "bean-annotator-db.ck1kkik42dzg.us-east-1.rds.amazonaws.com"),
        "port":     int(os.environ.get("DB_PORT", 5432)),
        "dbname":   os.environ.get("DB_NAME", "bean_annotator"),
        "user":     os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "sslmode":  "require",
    }


# ── Thread-safe connection pool (shared across all Streamlit sessions) ─────────

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()
_POOL_MIN, _POOL_MAX = 2, 20   # handles 15 annotators + admin with headroom


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(_POOL_MIN, _POOL_MAX, **_db_config())
    return _pool


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Return connection to pool (not closed — reused for next request)
        pool.putconn(conn)


# ── Annotators ────────────────────────────────────────────────────────────────

def get_or_create_annotator(
    cognito_sub: str,
    name: str,
    email: str,
    role: str = "annotator",
    username: str | None = None,
    created_by_admin: str | None = None,
    admin_visible_password: str | None = None,
) -> dict:
    email = (email or "").strip() or f"{cognito_sub}@beanlab.local"
    explicit_username = username.strip() if username else None
    username = (explicit_username or email.split("@", 1)[0] or cognito_sub).strip()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM annotators WHERE cognito_sub = %s", (cognito_sub,)
            )
            row = cur.fetchone()
            if row:
                next_username = explicit_username or row["username"]
                cur.execute(
                    """UPDATE annotators
                       SET last_active_at = NOW(),
                           username = %s,
                           name = %s,
                           email = %s,
                           role = %s,
                           created_by_admin = COALESCE(created_by_admin, %s),
                           admin_visible_password = COALESCE(%s, admin_visible_password),
                           is_active = true
                       WHERE cognito_sub = %s
                       RETURNING *""",
                    (next_username, name, email, role, created_by_admin, admin_visible_password, cognito_sub),
                )
                return dict(cur.fetchone())
            cur.execute(
                "SELECT * FROM annotators WHERE lower(username) = lower(%s)",
                (username,),
            )
            row = cur.fetchone()
            if row:
                state = "active" if row["is_active"] else "historical/deactivated"
                raise ValueError(
                    f'Username "{username}" is already reserved by an {state} account. '
                    "Choose a different username so historical assignments and annotations stay unambiguous."
                )
            cur.execute(
                """INSERT INTO annotators
                       (cognito_sub, username, name, email, role, created_by_admin, admin_visible_password)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (cognito_sub, username, name, email, role, created_by_admin, admin_visible_password),
            )
            return dict(cur.fetchone())


def get_all_annotators(admin_id: str | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = """SELECT ann.*,
                              creator.name AS created_by_admin_name,
                              creator.username AS created_by_admin_username
                       FROM annotators ann
                       LEFT JOIN annotators creator ON creator.id = ann.created_by_admin
                       WHERE ann.role = 'annotator'
                         AND ann.is_active = true"""
            if admin_id:
                cur.execute(
                    query + " AND ann.created_by_admin = %s ORDER BY ann.name",
                    (admin_id,),
                )
            else:
                cur.execute(query + " ORDER BY ann.name")
            return [dict(r) for r in cur.fetchall()]


def get_annotator_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM annotators WHERE lower(username) = lower(%s) LIMIT 1",
                (username,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def deactivate_annotator(annotator_id: str, admin_id: str) -> bool:
    """Soft-delete a team member owned by this admin.

    Pending and in-progress assignments are deleted so those images return
    to the unassigned pool. Completed and skipped assignments are kept for
    the audit trail.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE annotators
                   SET is_active = false
                   WHERE id = %s
                     AND created_by_admin = %s
                     AND role = 'annotator'
                     AND is_active = true""",
                (annotator_id, admin_id),
            )
            if cur.rowcount != 1:
                return False
            # Release unworked images back to the pool.
            cur.execute(
                """DELETE FROM assignments
                   WHERE annotator_id = %s
                     AND status IN ('pending', 'in_progress')""",
                (annotator_id,),
            )
            return True


# ── Jobs ──────────────────────────────────────────────────────────────────────

def create_job(name: str, description: str, created_by: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO jobs (name, description, created_by)
                   VALUES (%s, %s, %s) RETURNING *""",
                (name, description, created_by),
            )
            return dict(cur.fetchone())


def get_all_jobs() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]


def update_job_image_count(job_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET total_images = (SELECT COUNT(*) FROM images WHERE job_id = %s) WHERE id = %s",
                (job_id, job_id),
            )


# ── Images ────────────────────────────────────────────────────────────────────

def register_image(job_id: str, filename: str, s3_key: str, uploaded_by: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO images (job_id, filename, s3_key, uploaded_by)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (job_id, filename, s3_key, uploaded_by),
            )
            return dict(cur.fetchone())


def register_and_assign_images(
    image_rows: list[dict],
    job_id: str,
    uploaded_by: str,
    annotator_id: str,
    assigned_by_admin: str,
) -> int:
    """
    Bulk-register S3 images if needed, then assign them globally once.
    This keeps the admin click fast and avoids partial per-image commits.
    Requires UNIQUE(images.s3_key) and UNIQUE(assignments.image_id).
    """
    if not image_rows:
        return 0

    values = [(img["filename"], img["key"], job_id, uploaded_by) for img in image_rows]
    keys = [img["key"] for img in image_rows]

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO images (filename, s3_key, job_id, uploaded_by)
                   VALUES %s
                   ON CONFLICT (s3_key) DO NOTHING""",
                values,
                template="(%s, %s, %s, %s)",
            )
            cur.execute(
                "SELECT id FROM images WHERE s3_key = ANY(%s)",
                (keys,),
            )
            image_ids = [r["id"] for r in cur.fetchall()]
            if not image_ids:
                return 0

            assignment_values = [
                (image_id, annotator_id, assigned_by_admin)
                for image_id in image_ids
            ]
            inserted = psycopg2.extras.execute_values(
                cur,
                """INSERT INTO assignments (image_id, annotator_id, assigned_by_admin, assignment_kind)
                   VALUES %s
                   ON CONFLICT DO NOTHING
                   RETURNING id""",
                assignment_values,
                template="(%s, %s, %s, 'primary')",
                fetch=True,
            )
            cur.execute(
                "UPDATE jobs SET total_images = (SELECT COUNT(*) FROM images WHERE job_id = %s) WHERE id = %s",
                (job_id, job_id),
            )
            return len(inserted)


def get_images_for_job(job_id: str) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM images WHERE job_id = %s ORDER BY filename",
                (job_id,),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Shuffle order ─────────────────────────────────────────────────────────────

def ensure_shuffle_order(job_id: str, image_rows: list[dict], admin_id: str) -> dict:
    """
    Create a persistent shuffled order for the image pool once per job.
    Count-based assignment consumes unassigned images from this order.
    """
    if not image_rows:
        return {"created": False, "count": 0, "seed": None, "created_at": None}

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"image_shuffle_order:{job_id}",),
            )
            cur.execute(
                """SELECT COUNT(*) AS count,
                          MIN(shuffle_seed) AS seed,
                          MIN(created_at) AS created_at,
                          COALESCE(MAX(shuffle_rank), 0) AS max_rank
                   FROM image_shuffle_order
                   WHERE job_id = %s""",
                (job_id,),
            )
            existing = dict(cur.fetchone())
            existing_count = int(existing["count"] or 0)

            cur.execute(
                "SELECT s3_key FROM image_shuffle_order WHERE job_id = %s",
                (job_id,),
            )
            known_keys = {r["s3_key"] for r in cur.fetchall()}
            missing = [img for img in image_rows if img["key"] not in known_keys]

            if not missing:
                return {
                    "created": False,
                    "count": existing_count,
                    "seed": existing["seed"],
                    "created_at": existing["created_at"],
                }

            seed = existing["seed"] or secrets.token_hex(8)
            start_rank = int(existing["max_rank"] or 0)
            shuffled = list(missing)
            random.Random(seed).shuffle(shuffled)
            values = [
                (
                    job_id,
                    img["key"],
                    img["filename"],
                    start_rank + idx,
                    seed,
                    admin_id,
                )
                for idx, img in enumerate(shuffled, start=1)
            ]
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO image_shuffle_order
                       (job_id, s3_key, filename, shuffle_rank, shuffle_seed, created_by_admin)
                   VALUES %s
                   ON CONFLICT (job_id, s3_key) DO NOTHING""",
                values,
                template="(%s, %s, %s, %s, %s, %s)",
            )
            # Verify the shuffle_order now covers every image in the input list.
            cur.execute(
                "SELECT COUNT(*) FROM image_shuffle_order WHERE job_id = %s",
                (job_id,),
            )
            actual_count = cur.fetchone()[0]
            missing_from_shuffle = len(image_rows) - actual_count
            return {
                "created": existing_count == 0,
                "count": actual_count,
                "seed": seed,
                "created_at": existing["created_at"],
                "missing_from_shuffle": missing_from_shuffle,
            }


def get_unassigned_images_in_shuffle_order(job_id: str, limit: int) -> list[dict]:
    """Next unassigned images according to the persistent shuffle order.

    INNER JOIN on images ensures we never hand out a shuffle-order entry that
    has no corresponding row in the images table (which would fail at assign time).
    """
    if limit <= 0:
        return []
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT so.filename,
                          so.s3_key AS key,
                          so.shuffle_rank,
                          so.shuffle_seed
                   FROM image_shuffle_order so
                   INNER JOIN images i ON i.s3_key = so.s3_key
                   LEFT  JOIN assignments a ON a.image_id = i.id
                   WHERE so.job_id = %s
                     AND a.id IS NULL
                   ORDER BY so.shuffle_rank
                   LIMIT %s""",
                (job_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Assignments ───────────────────────────────────────────────────────────────

def get_or_create_batch(name: str, created_by: str) -> dict:
    """Find a job (batch) by name or create it. Used when registering S3 images."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE name = %s LIMIT 1", (name,))
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute(
                "INSERT INTO jobs (name, created_by) VALUES (%s, %s) RETURNING *",
                (name, created_by),
            )
            return dict(cur.fetchone())


def get_image_by_s3_key(s3_key: str) -> dict | None:
    """Return an existing image row by S3 key, or None."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM images WHERE s3_key = %s LIMIT 1", (s3_key,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_assigned_s3_keys(annotator_id: str) -> set:
    """Return the set of S3 keys already assigned to this annotator."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT i.s3_key FROM assignments a
                   JOIN images i ON i.id = a.image_id
                   WHERE a.annotator_id = %s""",
                (annotator_id,),
            )
            return {row[0] for row in cur.fetchall()}


def assign_images_to_annotator(image_ids: list[str], annotator_id: str, assigned_by_admin: str) -> int:
    """Bulk-assign images to an annotator. Skips any already assigned globally."""
    if not image_ids:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            rows = psycopg2.extras.execute_values(
                cur,
                """INSERT INTO assignments (image_id, annotator_id, assigned_by_admin, assignment_kind)
                   VALUES %s
                   ON CONFLICT DO NOTHING
                   RETURNING id""",
                [(iid, annotator_id, assigned_by_admin) for iid in image_ids],
                template="(%s, %s, %s, 'primary')",
                fetch=True,
            )
            return len(rows)


def get_assignment_status_counts(annotator_id: str, admin_id: str) -> dict:
    """Assignment counts for one annotator, scoped to the assigning admin."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT
                       COUNT(*)                                          AS total,
                       COUNT(*) FILTER (WHERE status = 'pending')       AS pending,
                       COUNT(*) FILTER (WHERE status = 'in_progress')   AS in_progress,
                       COUNT(*) FILTER (WHERE status = 'done')          AS done,
                       COUNT(*) FILTER (WHERE status = 'skipped')       AS skipped
                   FROM assignments
                   WHERE annotator_id = %s
                     AND assigned_by_admin = %s""",
                (annotator_id, admin_id),
            )
            row = dict(cur.fetchone())
            return {k: int(v or 0) for k, v in row.items()}


def reduce_pending_assignments(annotator_id: str, admin_id: str, target_total: int) -> int:
    """
    Reduce an annotator's assignment count to target_total by deleting newest pending rows.
    Completed, skipped, and in-progress assignments are intentionally preserved.
    """
    target_total = max(0, int(target_total))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*)
                   FROM assignments
                   WHERE annotator_id = %s
                     AND assigned_by_admin = %s""",
                (annotator_id, admin_id),
            )
            total = cur.fetchone()[0]
            remove_count = max(0, total - target_total)
            if remove_count == 0:
                return 0

            cur.execute(
                """WITH doomed AS (
                       SELECT id
                       FROM assignments
                       WHERE annotator_id = %s
                         AND assigned_by_admin = %s
                         AND status = 'pending'
                       ORDER BY assigned_at DESC, id DESC
                       LIMIT %s
                   )
                   DELETE FROM assignments a
                   USING doomed
                   WHERE a.id = doomed.id""",
                (annotator_id, admin_id, remove_count),
            )
            return cur.rowcount


def get_annotator_queue(annotator_id: str) -> list[dict]:
    """Load all assigned images + existing annotations for an annotator (resume flow)."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT
                       a.id              AS assignment_id,
                       a.status,
                       a.assigned_at,
                       a.assigned_by_admin,
                       a.last_image_idx,
                       a.last_active_at,
                       i.id              AS image_id,
                       i.filename,
                       i.s3_key,
                       j.id              AS job_id,
                       j.name            AS batch_name,
                       ann.overall_severity,
                       ann.overall_notes,
                       ann.defects,
                       ann.skip_reason,
                       ann.saved_at
                   FROM assignments a
                   JOIN images i ON i.id = a.image_id
                   JOIN jobs j ON j.id = i.job_id
                   LEFT JOIN annotations ann ON ann.assignment_id = a.id
                   WHERE a.annotator_id = %s
                   ORDER BY a.assigned_at, i.filename""",
                (annotator_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def update_assignment_cursor(assignment_id: str, last_image_idx: int, status: str = "in_progress") -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE assignments
                   SET status = %s, last_image_idx = %s, last_active_at = NOW()
                   WHERE id = %s""",
                (status, last_image_idx, assignment_id),
            )


# ── Annotations ───────────────────────────────────────────────────────────────

def save_annotation(
    assignment_id: str,
    annotator_id: str,
    overall_severity: int | None,
    overall_notes: str,
    defects: list,
    skip_reason: str | None = None,
) -> None:
    status = "skipped" if skip_reason else "done"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO annotations
                       (assignment_id, annotator_id, overall_severity, overall_notes,
                        defects, skip_reason, saved_at)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW())
                   ON CONFLICT (assignment_id) DO UPDATE
                   SET overall_severity = EXCLUDED.overall_severity,
                       overall_notes    = EXCLUDED.overall_notes,
                       defects          = EXCLUDED.defects,
                       skip_reason      = EXCLUDED.skip_reason,
                       saved_at         = NOW()""",
                (
                    assignment_id,
                    annotator_id,
                    overall_severity,
                    overall_notes,
                    json.dumps(defects),
                    skip_reason,
                ),
            )
            cur.execute(
                """UPDATE assignments
                   SET status = %s, last_active_at = NOW()
                   WHERE id = %s""",
                (status, assignment_id),
            )


# ── Admin progress ────────────────────────────────────────────────────────────

def get_progress_summary(admin_id: str | None = None) -> list[dict]:
    """Per-annotator progress for the admin dashboard."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params = []
            admin_filter = ""
            if admin_id:
                admin_filter = "AND a.assigned_by_admin = %s"
                params.append(admin_id)
            cur.execute(
                f"""SELECT
                       ann.id,
                       ann.name,
                       ann.username,
                       ann.email,
                       ann.created_by_admin,
                       creator.name                                      AS created_by_admin_name,
                       COUNT(*)                                          AS total,
                       COUNT(*) FILTER (WHERE a.status = 'done')        AS done,
                       COUNT(*) FILTER (WHERE a.status = 'skipped')     AS skipped,
                       COUNT(*) FILTER (WHERE a.status = 'in_progress') AS in_progress,
                       COUNT(*) FILTER (WHERE a.status = 'pending')     AS pending,
                       MAX(a.last_active_at)                            AS last_active
                   FROM assignments a
                   JOIN annotators ann ON ann.id = a.annotator_id
                   LEFT JOIN annotators creator ON creator.id = ann.created_by_admin
                   WHERE ann.role = 'annotator'
                     AND ann.is_active = true
                     {admin_filter}
                   GROUP BY ann.id, ann.name, ann.username, ann.email, ann.created_by_admin, creator.name
                   ORDER BY ann.name""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]


def get_all_assigned_s3_keys() -> set:
    """Return S3 keys that have at least one assignment (to any annotator)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT i.s3_key
                   FROM assignments a
                   JOIN images i ON i.id = a.image_id"""
            )
            return {row[0] for row in cur.fetchall()}


def get_annotator_assignment_summary(admin_id: str | None = None) -> list[dict]:
    """
    Per-annotator: total images assigned + list of admin names who made the assignments.
    Returns list of {annotator_name, image_count, assigned_by}.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params = []
            admin_filter = ""
            if admin_id:
                admin_filter = "AND a.assigned_by_admin = %s"
                params.append(admin_id)
            cur.execute(
                f"""SELECT
                       ann.id             AS annotator_id,
                       ann.name           AS annotator_name,
                       ann.created_by_admin,
                       creator.name        AS created_by_admin_name,
                       COUNT(a.id)        AS image_count,
                       COALESCE(
                           array_agg(DISTINCT adm.name ORDER BY adm.name)
                               FILTER (WHERE adm.name IS NOT NULL),
                           ARRAY[]::varchar[]
                       ) AS assigned_by
                   FROM assignments a
                   JOIN annotators ann ON ann.id = a.annotator_id
                   LEFT JOIN annotators creator ON creator.id = ann.created_by_admin
                   LEFT JOIN annotators adm ON adm.id = a.assigned_by_admin
                   WHERE ann.role = 'annotator'
                    AND ann.is_active = true
                    {admin_filter}
                   GROUP BY ann.id, ann.name, ann.created_by_admin, creator.name
                   ORDER BY ann.name""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]


def get_full_assignment_report(admin_id: str | None = None) -> list[dict]:
    """
    Master assignment report — one row per (image, annotator) pair.
    Used to generate the CSV saved to S3 after every assignment action.
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params = []
            admin_filter = ""
            if admin_id:
                admin_filter = "WHERE a.assigned_by_admin = %s"
                params.append(admin_id)
            cur.execute(
                f"""SELECT
                       i.id                                         AS image_id,
                       i.filename                                    AS filename,
                       i.s3_key                                     AS s3_key,
                       j.name                                       AS batch_name,
                       ann.id                                       AS annotator_id,
                       ann.name                                     AS annotator_name,
                       adm.id                                       AS assigned_by_admin_id,
                       adm.name                                     AS assigned_by,
                       so.shuffle_rank                              AS shuffle_rank,
                       so.shuffle_seed                              AS shuffle_seed,
                       a.assignment_kind                            AS assignment_kind,
                       a.source_assignment_id                       AS source_assignment_id,
                       a.status                                     AS status,
                       TO_CHAR(a.assigned_at,   'YYYY-MM-DD HH24:MI') AS assigned_at,
                       TO_CHAR(a.last_active_at,'YYYY-MM-DD HH24:MI') AS last_active_at
                   FROM assignments a
                   JOIN images     i   ON i.id   = a.image_id
                   JOIN annotators ann ON ann.id  = a.annotator_id
                   JOIN jobs       j   ON j.id   = i.job_id
                   LEFT JOIN annotators adm ON adm.id = a.assigned_by_admin
                   LEFT JOIN image_shuffle_order so ON so.job_id = i.job_id
                                                    AND so.s3_key = i.s3_key
                   {admin_filter}
                   ORDER BY so.shuffle_rank NULLS LAST, i.s3_key, ann.name""",
                params,
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                name = d["filename"]
                d["bean_id"] = name.rsplit(".", 1)[0] if "." in name else name
                rows.append(d)
            return rows


def get_all_annotations_for_job(job_id: str, admin_id: str | None = None) -> list[dict]:
    """Export: all annotations for a job."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            params = [job_id]
            admin_filter = ""
            if admin_id:
                admin_filter = "AND a.assigned_by_admin = %s"
                params.append(admin_id)
            cur.execute(
                f"""SELECT
                       i.id              AS image_id,
                       i.filename,
                       i.s3_key,
                       ann_r.id          AS annotator_id,
                       ann_r.name        AS annotator_name,
                       adm.id            AS assigned_by_admin_id,
                       adm.name          AS assigned_by_admin,
                       j.id              AS batch_id,
                       j.name            AS batch_name,
                       a.status,
                       an.overall_severity,
                       an.overall_notes,
                       an.defects,
                       an.skip_reason,
                       an.saved_at
                   FROM assignments a
                   JOIN images i        ON i.id  = a.image_id
                   JOIN jobs j          ON j.id  = i.job_id
                   JOIN annotators ann_r ON ann_r.id = a.annotator_id
                   LEFT JOIN annotators adm ON adm.id = a.assigned_by_admin
                   LEFT JOIN annotations an ON an.assignment_id = a.id
                   WHERE i.job_id = %s
                    {admin_filter}
                   ORDER BY i.filename, ann_r.name""",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
