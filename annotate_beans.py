"""
annotate_beans.py — Production annotator dashboard.

Wires Cognito auth, RDS Postgres, and S3 into the existing annotation UI.
Run:
    streamlit run annotate_beans.py --server.port 8501
"""

from dotenv import load_dotenv
load_dotenv()  # must run before local imports so env vars are set before storage/db read them

import streamlit as st

# Must be the very first Streamlit call in the process.
st.set_page_config(
    page_title="Bean Quality Annotator",
    layout="wide",
    initial_sidebar_state="expanded",
)

from auth import require_login, logout
from db import (
    get_or_create_annotator,
    get_annotator_queue,
    update_assignment_cursor,
    save_annotation as db_save,
)
from storage import download_image, boundary_key, upload_annotation_json
from annotation import (
    CSS,
    ANNOTATION_VER,
    annotation_view,
)

# Number of images to keep in the in-memory cache (current ± window on each side)
_IMG_CACHE_WINDOW = 4


# ── Queue loader ──────────────────────────────────────────────────────────────

def _load_queue() -> None:
    """
    Fetch assigned images from DB, build queue metadata, restore saved annotations.
    Images are NOT downloaded here — they are lazy-loaded on demand via _ensure_images().
    """
    user   = st.session_state["auth_user"]
    db_ann = st.session_state["db_annotator"]

    with st.spinner("Loading your queue…"):
        queue = get_annotator_queue(db_ann["id"])

    if not queue:
        st.markdown("## No images assigned yet")
        st.info("Your admin hasn't assigned any images to you. Check back later.")
        if st.button("Sign out"):
            _full_logout()
        st.stop()

    # Resume at first pending/in_progress item
    resume_idx = 0
    for i, item in enumerate(queue):
        if item["status"] in ("pending", "in_progress"):
            resume_idx = i
            break

    img_order   = []
    anns        = {}
    assignments = {}   # mask_id → assignment_id
    assignment_meta = {}
    s3_keys     = {}   # mask_id → s3_key (for lazy download)

    for item in queue:
        mid = str(item["image_id"])
        img_order.append(mid)
        assignments[mid] = str(item["assignment_id"])
        s3_keys[mid]     = item["s3_key"]
        assignment_meta[mid] = {
            "assignment_id": str(item["assignment_id"]),
            "assignment_status": item["status"],
            "assigned_at": str(item["assigned_at"]) if item.get("assigned_at") else None,
            "assigned_by_admin_id": str(item["assigned_by_admin"]) if item.get("assigned_by_admin") else None,
            "image_id": mid,
            "image_filename": item["filename"],
            "image_s3_key": item["s3_key"],
            "job_id": str(item["job_id"]),
            "batch_name": item.get("batch_name") or "",
        }

        if item.get("overall_severity") is not None or item.get("skip_reason"):
            anns[mid] = {
                "annotation_version": ANNOTATION_VER,
                "mask_id":            mid,
                "image_stem":         item["filename"].rsplit(".", 1)[0],
                "image_filename":     item["filename"],
                "overall_severity":   item["overall_severity"],
                "overall_notes":      item.get("overall_notes") or "",
                "defects":            item.get("defects") or [],
                "skip": {
                    "skipped": bool(item.get("skip_reason")),
                    "reason":  item.get("skip_reason") or "",
                },
                "timestamp": str(item["saved_at"]) if item.get("saved_at") else None,
                "annotator": user["name"],
            }

    st.session_state.update({
        "imgs":              {},        # populated lazily by _ensure_images()
        "img_order":         img_order,
        "anns":              anns,
        "annotator":         user["name"],
        "ready":             True,
        "idx":               resume_idx,
        "assignments":       assignments,
        "assignment_meta":    assignment_meta,
        "s3_keys":           s3_keys,
        "_last_synced_ts":   {},
        "_last_synced_idx":  None,
    })
    st.rerun()


# ── Lazy image loader ─────────────────────────────────────────────────────────

def _ensure_images(cur_idx: int) -> None:
    """
    Download boundary images for a sliding window around the current index.
    Evicts images outside the window to keep RAM bounded.
    """
    img_order = st.session_state.get("img_order", [])
    s3_keys   = st.session_state.get("s3_keys", {})
    imgs      = st.session_state.setdefault("imgs", {})
    total     = len(img_order)
    if total == 0:
        return

    # Window: current ± _IMG_CACHE_WINDOW, clamped to valid range
    lo = max(0, cur_idx - _IMG_CACHE_WINDOW)
    hi = min(total - 1, cur_idx + _IMG_CACHE_WINDOW)
    keep = {img_order[i] for i in range(lo, hi + 1)}

    # Evict images outside the window
    for mid in list(imgs.keys()):
        if mid not in keep:
            del imgs[mid]

    # Download any missing images in the window (current first)
    priority = [img_order[cur_idx]] + [img_order[i] for i in range(lo, hi + 1) if i != cur_idx]
    for mid in priority:
        if mid not in imgs:
            s3_key = s3_keys.get(mid)
            if not s3_key:
                continue
            try:
                imgs[mid] = download_image(boundary_key(s3_key))
            except Exception:
                # Use a 1×1 gray placeholder so the UI doesn't crash on a bad S3 key
                imgs[mid] = _gray_placeholder()

    st.session_state["imgs"] = imgs


def _gray_placeholder() -> bytes:
    """Return minimal valid PNG bytes (1×1 gray pixel) for a failed S3 download."""
    import io
    from PIL import Image as _PIL
    buf = io.BytesIO()
    _PIL.new("RGB", (400, 300), (200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


# ── DB sync ───────────────────────────────────────────────────────────────────

def _sync_to_db() -> None:
    """At the start of each render, flush newly saved annotations to Postgres and S3."""
    current_anns = st.session_state.get("anns", {})
    last_synced  = st.session_state.get("_last_synced_ts", {})
    assignments  = st.session_state.get("assignments", {})
    assignment_meta = st.session_state.get("assignment_meta", {})
    db_ann       = st.session_state.get("db_annotator")

    if not db_ann:
        return

    for mid, ann in current_anns.items():
        ts = ann.get("timestamp")
        if ts and ts != last_synced.get(mid):
            assignment_id = assignments.get(mid)
            if assignment_id:
                skip_info   = ann.get("skip") or {}
                skip_reason = skip_info.get("reason") if skip_info.get("skipped") else None
                db_save(
                    assignment_id    = assignment_id,
                    annotator_id     = db_ann["id"],
                    overall_severity = ann.get("overall_severity"),
                    overall_notes    = ann.get("overall_notes", ""),
                    defects          = ann.get("defects") or [],
                    skip_reason      = skip_reason,
                )
                meta = assignment_meta.get(mid, {})
                if meta.get("job_id") and meta.get("image_filename"):
                    payload = _annotation_payload(ann, meta, db_ann, skip_reason)
                    try:
                        upload_annotation_json(
                            payload,
                            job_id=meta["job_id"],
                            annotator=db_ann,
                            filename=meta["image_filename"],
                        )
                    except Exception as exc:
                        st.warning(
                            f"Saved to database, but the S3 JSON mirror failed for "
                            f"{meta['image_filename']}: {exc}"
                        )
                        continue
                last_synced[mid] = ts

    st.session_state["_last_synced_ts"] = last_synced

    # Update cursor only when idx actually changed — avoids a DB write on every render
    img_order        = st.session_state.get("img_order", [])
    idx              = st.session_state.get("idx", 0)
    last_synced_idx  = st.session_state.get("_last_synced_idx")
    if img_order and 0 <= idx < len(img_order) and idx != last_synced_idx:
        mid           = img_order[idx]
        assignment_id = assignments.get(mid)
        if assignment_id:
            ann    = current_anns.get(mid, {})
            status = (
                "skipped"     if ann.get("skip", {}).get("skipped")
                else "done"   if ann.get("overall_severity") is not None
                else "in_progress"
            )
            update_assignment_cursor(assignment_id, idx, status)
            st.session_state["_last_synced_idx"] = idx


def _annotation_payload(ann: dict, meta: dict, annotator: dict, skip_reason: str | None) -> dict:
    severity = ann.get("overall_severity")
    status = "skipped" if skip_reason else "done"
    return {
        "schema_version": 1,
        "annotation_version": ann.get("annotation_version", ANNOTATION_VER),
        "status": status,
        "assignment": {
            "id": meta.get("assignment_id"),
            "assigned_at": meta.get("assigned_at"),
            "assigned_by_admin_id": meta.get("assigned_by_admin_id"),
        },
        "annotator": {
            "id": str(annotator["id"]),
            "name": annotator.get("name", ""),
            "username": annotator.get("username", ""),
        },
        "image": {
            "id": meta.get("image_id") or ann.get("mask_id"),
            "filename": meta.get("image_filename") or ann.get("image_filename"),
            "s3_key": meta.get("image_s3_key"),
            "batch_id": meta.get("job_id"),
            "batch_name": meta.get("batch_name", ""),
        },
        "result": {
            "overall_severity": severity,
            "severity_label": {1: "Good", 2: "Bad"}.get(severity),
            "overall_notes": ann.get("overall_notes", ""),
            "skip": {
                "skipped": bool(skip_reason),
                "reason": skip_reason or "",
            },
            "defect_count": len(ann.get("defects") or []),
            "defects": ann.get("defects") or [],
        },
        "saved_at": ann.get("timestamp"),
    }


# ── Logout ────────────────────────────────────────────────────────────────────

def _full_logout() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    logout()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)

    # 1. Require Cognito login
    user = require_login()

    # 2. Ensure annotator row exists in DB
    if "db_annotator" not in st.session_state:
        st.session_state["db_annotator"] = get_or_create_annotator(
            cognito_sub = user["sub"],
            name        = user["name"],
            email       = user["email"],
            role        = user["role"],
        )

    # 3. Load S3 image queue if not done yet (metadata only — no image bytes)
    if not st.session_state.get("ready"):
        _load_queue()
        return

    # 4. Ensure current image (and neighbours) are in memory
    cur_idx = st.session_state.get("idx", 0)
    _ensure_images(cur_idx)

    # 5. Sync any locally saved annotations → DB before rendering
    _sync_to_db()

    # 6. Sidebar: user info + sign-out
    with st.sidebar:
        st.markdown("---")
        name = user.get("name") or user.get("username", "Annotator")
        st.caption(f"Signed in as **{name}**")
        if st.button("Sign out", width="stretch"):
            _full_logout()

    # 7. Run the existing annotation UI (unchanged)
    annotation_view()


if __name__ == "__main__":
    main()
