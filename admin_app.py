"""
admin_app.py — Admin dashboard for Bean Annotator.
Run:  streamlit run admin_app.py --server.port 8502
"""

import os, io, csv, json, secrets, string, re
from html import escape

from dotenv import load_dotenv
load_dotenv()  # MUST be before any local imports — storage/db read env vars at import time

import boto3
import streamlit as st

st.set_page_config(
    page_title="Bean Annotator — Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)

from auth import require_login, logout
from db import (
    get_or_create_annotator,
    get_all_annotators,
    get_annotator_by_username,
    deactivate_annotator,
    get_or_create_batch,
    get_assigned_s3_keys,
    get_all_assigned_s3_keys,
    get_annotator_assignment_summary,
    get_full_assignment_report,
    register_and_assign_images,
    ensure_shuffle_order,
    get_unassigned_images_in_shuffle_order,
    get_assignment_status_counts,
    reduce_pending_assignments,
    get_progress_summary,
    get_all_jobs,
    get_all_annotations_for_job,
)
from storage import (
    list_all_images, save_assignment_report, save_annotator_assignment_report,
    download_assignment_report,
    CROP_BANK_PREFIX, _bucket,
)
from annotation import CSS

# ── Cognito ───────────────────────────────────────────────────────────────────

def _cognito():
    return boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))

_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")

# ── CSS ───────────────────────────────────────────────────────────────────────

ADMIN_CSS = """
<style>
/* page titles */
.adm-title{font-size:1.6rem;font-weight:800;color:#0f172a;letter-spacing:-.03em;margin-bottom:2px}
.adm-sub{font-size:.8rem;color:#6b7280;margin-bottom:20px}
/* cards */
.adm-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:18px 22px;margin-bottom:10px}
/* section headings */
.adm-section{font-size:.62rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
             color:#94a3b8;margin:20px 0 10px}
/* badges */
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.68rem;font-weight:700;
       letter-spacing:.05em;text-transform:uppercase}
.badge-admin{background:#dbeafe;color:#1e40af}
.badge-ann{background:#f0fdf4;color:#166534}
</style>
"""

# ── Cached S3 + DB calls ──────────────────────────────────────────────────────
# Cache expensive calls so they don't re-run on every Streamlit interaction.

@st.cache_data(ttl=300, show_spinner=False)
def _all_images() -> list[dict]:
    """All images in S3 — refreshes every 5 minutes."""
    return list_all_images(prefix=CROP_BANK_PREFIX)


@st.cache_data(ttl=30, show_spinner=False)
def _globally_assigned() -> set:
    return get_all_assigned_s3_keys()


@st.cache_data(ttl=30, show_spinner=False)
def _assignment_summary(admin_id: str | None = None) -> list[dict]:
    return get_annotator_assignment_summary(admin_id)


@st.cache_data(ttl=30, show_spinner=False)
def _progress(admin_id: str | None = None) -> list[dict]:
    return get_progress_summary(admin_id)


def _bust_cache():
    """Call after any write operation to force fresh data on next render."""
    _globally_assigned.clear()
    _assignment_summary.clear()
    _progress.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _html(content: str) -> None:
    st.markdown(content, unsafe_allow_html=True)


def _metric(col, value, label: str, color="#0f172a", bg="#fff", border="#e2e8f0") -> None:
    col.markdown(
        f'<div style="background:{bg};border:1px solid {border};border-radius:12px;'
        f'padding:18px 20px;text-align:center;">'
        f'<div style="font-size:2.1rem;font-weight:800;color:{color};line-height:1;">{value}</div>'
        f'<div style="font-size:.63rem;font-weight:700;letter-spacing:.09em;'
        f'text-transform:uppercase;color:#94a3b8;margin-top:6px;">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _gen_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pwd) and any(c.islower() for c in pwd)
                and any(c.isdigit() for c in pwd) and any(c in "!@#$%" for c in pwd)):
            return pwd


def _clean_username(username: str) -> str:
    return username.strip().lower()


def _valid_username(username: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_.-]{3,64}", username))


def _disable_cognito_user(username: str) -> None:
    _cognito().admin_disable_user(
        UserPoolId=_USER_POOL_ID,
        Username=username,
    )


def _enable_cognito_user(username: str) -> None:
    _cognito().admin_enable_user(
        UserPoolId=_USER_POOL_ID,
        Username=username,
    )


def _set_cognito_password(username: str, password: str) -> None:
    _cognito().admin_set_user_password(
        UserPoolId=_USER_POOL_ID,
        Username=username,
        Password=password,
        Permanent=True,
    )


# ── Auth guard ────────────────────────────────────────────────────────────────

def _require_admin() -> dict:
    st.session_state["login_title"] = "Admin Dashboard"
    user = require_login()
    if user.get("role") != "admin":
        st.error("Access denied — admins only.")
        if st.button("Sign out"):
            logout()
        st.stop()
    db_user = st.session_state.get("db_annotator")
    if not db_user or db_user.get("cognito_sub") != user["sub"]:
        st.session_state["db_annotator"] = get_or_create_annotator(
            cognito_sub=user["sub"],
            name=user["name"],
            email=user.get("email", ""),
            role="admin",
            username=user.get("username", user["sub"]),
        )
    return user


# ── Sidebar ───────────────────────────────────────────────────────────────────

NAV = ["Progress", "Team", "Assign Images", "Export"]


def _sidebar(user: dict) -> str:
    with st.sidebar:
        _html(
            '<div style="padding:20px 0 16px;">'
            '<div style="font-size:.58rem;font-weight:700;letter-spacing:.14em;'
            'text-transform:uppercase;color:#94a3b8;">MSU Bean Lab</div>'
            '<div style="font-size:1.15rem;font-weight:800;color:#0f172a;'
            'margin-top:3px;letter-spacing:-.02em;">Admin Dashboard</div>'
            '</div>'
        )

        name  = escape(user.get("name") or user.get("username", "Admin"))
        email = escape(user.get("email", ""))
        _html(
            f'<div style="background:#f1f5f9;border-radius:10px;padding:12px 14px;margin-bottom:16px;">'
            f'<div style="font-size:.82rem;font-weight:700;color:#0f172a;">{name}</div>'
            f'<div style="font-size:.7rem;color:#64748b;margin-top:2px;">{email}</div>'
            f'<span class="badge badge-admin" style="margin-top:8px;display:inline-block;">Admin</span>'
            f'</div>'
        )

        _html('<div class="adm-section" style="margin-top:4px;">Navigation</div>')
        page = st.radio("nav", NAV, label_visibility="collapsed")

        _html('<div style="height:1px;background:#e2e8f0;margin:16px 0;"></div>')

        if st.button("Sign out", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            logout()

    return page


# ── Page: Progress ────────────────────────────────────────────────────────────

def page_progress(admin: dict) -> None:
    _html('<div class="adm-title">Progress</div>'
          '<div class="adm-sub">Live annotation status across all annotators.</div>')

    rows = _progress(None)
    if not rows:
        st.info("Nobody has been assigned images yet. Go to **Assign Images** to get started.")
        return

    total_all  = sum(r["total"]       for r in rows)
    done       = sum(r["done"]        for r in rows)
    in_prog    = sum(r["in_progress"] for r in rows)
    skipped    = sum(r["skipped"]     for r in rows)
    pending    = sum(r["pending"]     for r in rows)
    pct        = round(100 * done / total_all) if total_all else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    _metric(c1, total_all, "Total Assigned", "#0f172a")
    _metric(c2, done,      "Done",           "#1d4ed8", "#eff6ff", "#bfdbfe")
    _metric(c3, in_prog,   "In Progress",    "#d97706", "#fffbeb", "#fde68a")
    _metric(c4, skipped,   "Skipped",        "#6b7280", "#f9fafb", "#e5e7eb")
    _metric(c5, pending,   "Pending",        "#854d0e", "#fefce8", "#fef08a")

    st.markdown("<br>", unsafe_allow_html=True)

    _html(
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">'
        f'<span style="font-size:.75rem;font-weight:600;color:#374151;">Overall completion</span>'
        f'<span style="font-size:1.1rem;font-weight:800;color:#0f172a;">{pct}%</span>'
        f'</div>'
        f'<div style="height:10px;background:#e5e7eb;border-radius:5px;overflow:hidden;margin-bottom:24px;">'
        f'<div style="width:{pct}%;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:5px;"></div>'
        f'</div>'
    )

    st.divider()
    _html('<div class="adm-section">Per annotator</div>')

    for r in rows:
        t    = r["total"] or 1
        p    = round(100 * r["done"] / t)
        last = str(r["last_active"])[:16] if r.get("last_active") else "Never"
        username = escape(r.get("username") or "")
        owner = escape(r.get("created_by_admin_name") or "Unknown admin")
        _html(
            f'<div class="adm-card">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
            f'<div style="font-size:.92rem;font-weight:700;color:#0f172a;">{escape(r["name"])}</div>'
            f'<div style="font-size:.78rem;color:#334155;background:#f1f5f9;'
            f'border:1px solid #e2e8f0;border-radius:6px;padding:3px 8px;">'
            f'<b>Username:</b> {username}</div>'
            f'<div style="font-size:.78rem;color:#334155;background:#f8fafc;'
            f'border:1px solid #e2e8f0;border-radius:6px;padding:3px 8px;">'
            f'<b>Owner:</b> {owner}</div>'
            f'<div style="margin-left:auto;font-size:.68rem;color:#9ca3af;">Last active: {last}</div>'
            f'</div>'
            f'<div style="display:flex;gap:20px;margin-bottom:10px;flex-wrap:wrap;">'
            f'<span style="font-size:.8rem;"><b style="color:#0f172a;">{r["done"]}</b>'
            f' <span style="color:#6b7280;">done</span></span>'
            f'<span style="font-size:.8rem;"><b style="color:#d97706;">{r["in_progress"]}</b>'
            f' <span style="color:#6b7280;">in progress</span></span>'
            f'<span style="font-size:.8rem;"><b style="color:#6b7280;">{r["skipped"]}</b>'
            f' <span style="color:#6b7280;">skipped</span></span>'
            f'<span style="font-size:.8rem;"><b style="color:#854d0e;">{r["pending"]}</b>'
            f' <span style="color:#6b7280;">pending</span></span>'
            f'<span style="margin-left:auto;font-size:.95rem;font-weight:800;color:#0f172a;">{p}%</span>'
            f'</div>'
            f'<div style="height:7px;background:#e5e7eb;border-radius:4px;overflow:hidden;">'
            f'<div style="width:{p}%;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:4px;"></div>'
            f'</div>'
            f'</div>'
        )


# ── Page: Team ────────────────────────────────────────────────────────────────

def page_team(admin: dict) -> None:
    _html('<div class="adm-title">Team</div>'
          '<div class="adm-sub">View all annotators. Manage only the accounts you created.</div>')

    _html(
        '<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;'
        'padding:14px 18px;margin-bottom:20px;font-size:.8rem;color:#0369a1;line-height:1.8;">'
        '<b>How to add someone</b><br>'
        '1. Enter their <b>full name</b> and choose a <b>username</b> for them.<br>'
        '2. A secure password is created automatically.<br>'
        '3. Usernames are permanent; even deactivated accounts keep their username for audit history.<br>'
        '4. Share the <b>username</b> and <b>password</b> shown on screen; they can log in immediately.<br>'
        '5. Then go to <b>Assign Images</b> to give them images to annotate.'
        '</div>'
    )

    with st.expander("Add a new team member", expanded=False):
        with st.form("add_annotator"):
            c1, c2 = st.columns(2)
            new_name     = c1.text_input("Full name",      placeholder="Parimal Nath")
            new_username = c2.text_input("Login username", placeholder="parimal",
                                         help="Use letters, numbers, dots, underscores, or hyphens.")
            submitted = st.form_submit_button("Create account", type="primary")

        if submitted:
            username = _clean_username(new_username)
            if not all([new_name.strip(), username]):
                st.error("Both fields are required.")
            elif not _valid_username(username):
                st.error("Use 3-64 characters: letters, numbers, dots, underscores, or hyphens.")
            else:
                temp_pwd = _gen_password()
                try:
                    existing_user = get_annotator_by_username(username)
                    if existing_user:
                        state = "active" if existing_user.get("is_active") else "deactivated"
                        st.error(
                            f'Username "{username}" is already reserved by a {state} account. '
                            "Use a different username so old assignments, annotations, and progress records remain clear."
                        )
                        return

                    cog  = _cognito()
                    try:
                        resp = cog.admin_create_user(
                            UserPoolId=_USER_POOL_ID,
                            Username=username,
                            UserAttributes=[{"Name": "name", "Value": new_name.strip()}],
                            TemporaryPassword=temp_pwd,
                            MessageAction="SUPPRESS",
                        )
                    except Exception as exc:
                        if "UsernameExistsException" not in str(exc):
                            raise
                        st.error(
                            f'Username "{username}" already exists in the login system. '
                            "Use a different username to keep historical records unambiguous."
                        )
                        return
                    cog.admin_set_user_password(
                        UserPoolId=_USER_POOL_ID,
                        Username=username,
                        Password=temp_pwd,
                        Permanent=True,
                    )
                    try:
                        cog.admin_add_user_to_group(
                            UserPoolId=_USER_POOL_ID,
                            Username=username,
                            GroupName="annotators",
                        )
                    except Exception:
                        pass

                    attr_rows = resp.get("User", {}).get("Attributes", resp.get("UserAttributes", []))
                    attrs = {a["Name"]: a["Value"] for a in attr_rows}
                    try:
                        get_or_create_annotator(
                            cognito_sub=attrs.get("sub", username),
                            name=new_name.strip(),
                            email=attrs.get("email", f"{username}@beanlab.local"),
                            role="annotator",
                            username=username,
                            created_by_admin=admin["id"],
                            admin_visible_password=temp_pwd,
                        )
                    except Exception:
                        # Roll back the Cognito identity so the username isn't
                        # permanently orphaned/squatted and the admin can retry cleanly.
                        try:
                            cog.admin_delete_user(UserPoolId=_USER_POOL_ID, Username=username)
                        except Exception:
                            pass
                        raise
                    _bust_cache()

                    safe_name = escape(new_name.strip())
                    safe_username = escape(username)
                    safe_pwd = escape(temp_pwd)
                    _html(
                        f'<div style="background:#f0fdf4;border:1.5px solid #86efac;'
                        f'border-radius:10px;padding:18px 22px;margin-top:12px;">'
                        f'<div style="font-size:.88rem;font-weight:700;color:#166534;margin-bottom:14px;">'
                        f'Account created for <b>{safe_name}</b></div>'
                        f'<div style="display:flex;gap:48px;flex-wrap:wrap;margin-bottom:14px;">'
                        f'<div><div style="font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;'
                        f'color:#6b7280;margin-bottom:5px;">Login username</div>'
                        f'<code style="font-size:1rem;background:#dcfce7;padding:4px 10px;'
                        f'border-radius:5px;color:#0f172a;">{safe_username}</code></div>'
                        f'<div><div style="font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;'
                        f'color:#6b7280;margin-bottom:5px;">Password</div>'
                        f'<code style="font-size:1rem;background:#dcfce7;padding:4px 10px;'
                        f'border-radius:5px;color:#0f172a;">{safe_pwd}</code></div>'
                        f'</div>'
                        f'<div style="font-size:.75rem;color:#374151;">'
                        f'Share these with <b>{safe_name}</b>. '
                        f'They can sign in to the annotator app straight away.</div>'
                        f'</div>'
                    )
                except Exception as exc:
                    st.error(f"Could not create account: {exc}")

    st.divider()
    _html('<div class="adm-section">All annotators</div>')

    annotators = get_all_annotators()
    if not annotators:
        st.info("No team members yet. Add someone above.")
        return

    prog = {str(r["id"]): r for r in _progress(None)}

    for a in annotators:
        is_owner = str(a.get("created_by_admin")) == str(admin["id"])
        pr    = prog.get(str(a["id"]), {})
        total = pr.get("total", 0)
        done  = pr.get("done",  0)
        pct   = round(100 * done / total) if total else 0
        last  = str(pr.get("last_active", ""))[:16] or "Never logged in"
        identity = a.get("username") or a.get("email", "")
        saved_pwd = a.get("admin_visible_password") if is_owner else None
        if is_owner:
            password_display = saved_pwd or "Not available"
            password_color = "#166534" if saved_pwd else "#991b1b"
            password_bg = "#dcfce7" if saved_pwd else "#fee2e2"
        else:
            owner_name = a.get("created_by_admin_name") or "another admin"
            password_display = f"Hidden — managed by {owner_name}"
            password_color = "#475569"
            password_bg = "#e2e8f0"
        with st.container(border=True):
            cols = st.columns([1, 0.18, 0.18, 0.18])
            with cols[0]:
                st.markdown(f"**{escape(a['name'])}**")
                st.markdown(
                    f'<div style="background:#f8fafc;border:1px solid #e2e8f0;'
                    f'border-radius:8px;padding:10px 12px;margin-top:6px;">'
                    f'<div style="font-size:.65rem;font-weight:800;letter-spacing:.08em;'
                    f'text-transform:uppercase;color:#64748b;margin-bottom:4px;">Credentials</div>'
                    f'<div style="font-size:.9rem;color:#0f172a;"><b>Username:</b> '
                    f'<code style="font-weight:800;">{escape(identity)}</code></div>'
                    f'<div style="font-size:.9rem;color:#0f172a;margin-top:6px;"><b>Password:</b> '
                    f'<code style="font-weight:900;color:{password_color};background:{password_bg};'
                    f'padding:3px 7px;border-radius:5px;">{escape(password_display)}</code></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.caption(f"Last active: {last}")
                owner = a.get("created_by_admin_name") or "Unknown admin"
                st.caption(f"Created by: {owner}" + (" · You can manage this account" if is_owner else " · View only"))
            cols[1].metric("Assigned", total)
            cols[2].metric("Done", done)
            cols[3].metric("Complete", f"{pct}%")

            if is_owner:
                with st.expander("Deactivate account", expanded=False):
                    st.caption(
                        "This removes the team member from active admin lists and disables their Cognito login. "
                        "Existing assignments, progress, annotation results, and the username are kept for audit/export."
                    )
                    confirm = st.checkbox(
                        f"I understand and want to deactivate {a['name']}",
                        key=f"confirm_deactivate_{a['id']}",
                    )
                    if st.button(
                        f"Deactivate {a['name']}",
                        key=f"deactivate_{a['id']}",
                        disabled=not confirm,
                        use_container_width=True,
                    ):
                        try:
                            username = a.get("username") or a.get("cognito_sub")
                            if username:
                                _disable_cognito_user(username)
                            ok = deactivate_annotator(a["id"], admin["id"])
                            _bust_cache()
                            if ok:
                                st.success(f"{a['name']} was deactivated.")
                                st.rerun()
                            else:
                                st.warning("No matching active team member was found.")
                        except Exception as exc:
                            st.error(f"Could not deactivate account: {exc}")
            else:
                st.info("View only. Only the admin who created this annotator can deactivate or manage the account.")

# ── Page: Assign Images ───────────────────────────────────────────────────────

def page_assign(admin: dict) -> None:
    _html('<div class="adm-title">Assign Images</div>'
          '<div class="adm-sub">Give images to annotators you created. '
          'Everything stays in the cloud — nothing is downloaded.</div>')

    notice = st.session_state.pop("assignment_notice", None)
    if notice:
        kind, message = notice
        if kind == "success":
            st.success(message)
        else:
            st.warning(message)

    all_annotators = get_all_annotators()
    owned_annotators = get_all_annotators(admin["id"])
    if not owned_annotators:
        st.warning("Add a team member first on the **Team** page.")
        return

    # ── Load data (cached) ────────────────────────────────────────────────────
    with st.spinner("Loading…"):
        all_imgs   = _all_images()
        g_assigned = _globally_assigned()
        summary    = _assignment_summary(None)

    if not all_imgs:
        st.error(
            f"No images found in bucket `{_bucket()}` under `{CROP_BANK_PREFIX}`. "
            "Check your S3 bucket name and folder structure."
        )
        return

    db_ann = st.session_state["db_annotator"]
    batch = get_or_create_batch("Default", db_ann["id"])
    shuffle_info = ensure_shuffle_order(batch["id"], all_imgs, admin["id"])

    # Warn loudly if any images are absent from the shuffle order — they can
    # never be reached by count-based assignment and would silently be skipped.
    if shuffle_info.get("missing_from_shuffle", 0) > 0:
        st.error(
            f"⚠️ {shuffle_info['missing_from_shuffle']} image(s) are missing from the "
            "shuffle order and cannot be assigned by count. Please contact the developer."
        )

    all_keys  = {img["key"] for img in all_imgs}
    unassigned_count = len([k for k in all_keys if k not in g_assigned])

    # ── Global stats ──────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    _metric(m1, len(all_imgs),                    "Total images",         "#0f172a")
    _metric(m2, unassigned_count,                  "Not assigned to anyone","#d97706", "#fffbeb", "#fde68a")
    _metric(m3, len(all_keys) - unassigned_count,  "Given to someone",    "#1d4ed8", "#eff6ff", "#bfdbfe")

    # ── Who has what ──────────────────────────────────────────────────────────
    st.divider()
    _html('<div class="adm-section">Images given to each person</div>')

    summary_by_annotator = {str(row["annotator_id"]): row for row in summary}
    if not all_annotators:
        _html('<div style="color:#6b7280;font-size:.82rem;padding:4px 0 12px;">'
              'Nobody has been assigned images yet.</div>')
    else:
        for ann in all_annotators:
            row = summary_by_annotator.get(str(ann["id"]), {
                "annotator_name": ann["name"],
                "image_count": 0,
                "assigned_by": [],
            })
            admins_str = ", ".join(row["assigned_by"]) if row["assigned_by"] else "—"
            owner = ann.get("created_by_admin_name") or "Unknown admin"
            _html(
                f'<div class="adm-card" style="display:flex;align-items:center;gap:20px;">'
                f'<div style="flex:1;">'
                f'<div style="font-size:.92rem;font-weight:700;color:#0f172a;">{escape(row["annotator_name"])}</div>'
                f'<div style="font-size:.72rem;color:#9ca3af;margin-top:3px;">'
                f'Created by {escape(owner)} · Assigned by {escape(admins_str)}</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<span style="font-size:1.7rem;font-weight:800;color:#1d4ed8;">{row["image_count"]}</span>'
                f'<span style="font-size:.68rem;color:#94a3b8;margin-left:6px;">images</span>'
                f'</div>'
                f'</div>'
            )

    # ── Assign form ───────────────────────────────────────────────────────────
    st.divider()
    _html('<div class="adm-section">Give images to a team member</div>')
    st.caption("You can assign and adjust work only for annotators you created. Everyone remains visible above.")
    seed_text = shuffle_info.get("seed") or "not created yet"
    st.caption(
        f"Count-based assignments use a saved shuffled image order "
        f"({shuffle_info.get('count', 0)} images, seed `{seed_text}`)."
    )

    def _annotator_label(a: dict) -> str:
        username = a.get("username") or a.get("email") or str(a["id"])[:8]
        return f"{a['name']} ({username})"

    annotator = st.selectbox(
        "Who should annotate?",
        owned_annotators,
        format_func=_annotator_label,
    )

    already_this  = get_assigned_s3_keys(annotator["id"])
    available     = [img for img in all_imgs if img["key"] not in g_assigned]
    counts_this   = get_assignment_status_counts(annotator["id"], admin["id"])

    with st.expander("Adjust this team member's assignments", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Assigned", counts_this["total"])
        c2.metric("Pending", counts_this["pending"])
        c3.metric("In progress", counts_this["in_progress"])
        c4.metric("Done", counts_this["done"])
        c5.metric("Skipped", counts_this["skipped"])

        min_safe_total = counts_this["total"] - counts_this["pending"]
        st.caption(
            "Reduction removes newest pending assignments only. "
            "Started, done, and skipped work is preserved."
        )
        target_total = st.number_input(
            "Target assigned count",
            min_value=min_safe_total,
            max_value=counts_this["total"],
            value=counts_this["total"],
            step=50,
            help=f"Minimum is {min_safe_total} because non-pending assignments are protected.",
        )
        if st.button(
            f"Reduce to {int(target_total)}",
            disabled=int(target_total) >= counts_this["total"],
            use_container_width=True,
        ):
            _do_reduce_assignments(annotator, admin, int(target_total))

    if not available:
        st.success(
            f"**{annotator['name']}** already has all {len(all_imgs)} images. "
            "Nothing left to assign."
        )
    else:
        st.caption(
            f"{len(available)} images available for {annotator['name']} "
            f"({len(already_this)} already assigned to this team member)"
        )

        tab_count, tab_pick = st.tabs(["Assign by count", "Pick specific images"])

        # ── Tab 1: assign N images from saved shuffled order ──────────────
        with tab_count:
            st.markdown(
                "Enter how many images to assign. They will be taken from the next "
                "unassigned positions in the saved shuffled image order."
            )
            col_n, col_btn = st.columns([2, 1])
            n = col_n.number_input(
                "Number of images to assign",
                min_value=1, max_value=len(available),
                value=min(500, len(available)),
                step=50,
            )
            col_btn.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if col_btn.button(f"Assign {int(n)}", type="primary", use_container_width=True):
                chosen = get_unassigned_images_in_shuffle_order(batch["id"], int(n))
                if not chosen:
                    st.warning("No unassigned images are available in the shuffled pool.")
                else:
                    _do_assign(chosen, annotator, admin)

        # ── Tab 2: search & pick specific images ──────────────────────────
        with tab_pick:
            search = st.text_input("Search by filename", placeholder="e.g. mask_0042")
            filtered = [img for img in available
                        if not search or search.lower() in img["filename"].lower()]
            st.caption(f"{len(filtered)} matching")

            label_to_img = {
                f'{img["filename"]} — {img["key"]}': img
                for img in filtered
            }
            sel_labels = st.multiselect(
                "Images",
                options=list(label_to_img.keys()),
                placeholder="Search and select…",
                label_visibility="collapsed",
            )

            if sel_labels:
                chosen = [label_to_img[lbl] for lbl in sel_labels]
                if st.button(
                    f"Assign {len(chosen)} selected image(s) to {annotator['name']}",
                    type="primary", use_container_width=True,
                ):
                    _do_assign(chosen, annotator, admin)

    # ── Assignment record ──────────────────────────────────────────────────────
    st.divider()
    _html('<div class="adm-section">Assignment record</div>')
    _html(
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:14px 18px;font-size:.8rem;color:#374151;margin-bottom:12px;line-height:1.7;">'
        'A spreadsheet is saved automatically every time you assign images. '
        'It records every image, its shuffle position, who it was given to, who assigned it, and its current status. '
        'Download the shared audit record anytime.'
        '</div>'
    )
    report_bytes = download_assignment_report()
    if report_bytes:
        st.download_button(
            "Download shared assignment record (CSV)",
            data=report_bytes,
            file_name="assignment_report.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.caption("The record will appear here once you assign your first image.")


def _do_assign(chosen: list[dict], annotator: dict, admin: dict) -> None:
    """Register and assign a list of image dicts to an annotator."""
    db_ann    = st.session_state["db_annotator"]
    batch     = get_or_create_batch("Default", db_ann["id"])

    with st.spinner(f"Assigning {len(chosen)} image(s) to {annotator['name']}..."):
        count = register_and_assign_images(
            image_rows=chosen,
            job_id=batch["id"],
            uploaded_by=db_ann["id"],
            annotator_id=annotator["id"],
            assigned_by_admin=admin["id"],
        )
        global_report_rows = get_full_assignment_report()
        save_assignment_report(global_report_rows)
        admin_report_rows = [r for r in global_report_rows if str(r.get("assigned_by_admin_id")) == str(admin["id"])]
        save_assignment_report(admin_report_rows, admin["id"])
        annotator_rows = [r for r in global_report_rows if str(r.get("annotator_id")) == str(annotator["id"])]
        save_annotator_assignment_report(annotator_rows, annotator)
    _bust_cache()

    if count < len(chosen):
        st.session_state["assignment_notice"] = (
            "warning",
            f"Assigned {count} of {len(chosen)} selected image(s). "
            "The rest were already assigned by another admin or session."
        )
    else:
        st.session_state["assignment_notice"] = (
            "success",
            f"Done! {count} image(s) assigned to {annotator['name']}. "
            "They will see them the next time they open the annotator app."
        )
    st.rerun()


def _refresh_assignment_reports(admin: dict, annotator: dict) -> None:
    report_rows = get_full_assignment_report()
    save_assignment_report(report_rows)
    admin_rows = [r for r in report_rows if str(r.get("assigned_by_admin_id")) == str(admin["id"])]
    save_assignment_report(admin_rows, admin["id"])
    annotator_rows = [r for r in report_rows if str(r.get("annotator_id")) == str(annotator["id"])]
    save_annotator_assignment_report(annotator_rows, annotator)


def _do_reduce_assignments(annotator: dict, admin: dict, target_total: int) -> None:
    counts_before = get_assignment_status_counts(annotator["id"], admin["id"])
    removed = reduce_pending_assignments(annotator["id"], admin["id"], target_total)
    _refresh_assignment_reports(admin, annotator)
    _bust_cache()

    wanted_remove = max(0, counts_before["total"] - target_total)
    if removed == wanted_remove:
        st.session_state["assignment_notice"] = (
            "success",
            f"Reduced {annotator['name']} to {target_total} assignment(s). Removed {removed} pending assignment(s)."
        )
    else:
        protected = wanted_remove - removed
        st.session_state["assignment_notice"] = (
            "warning",
            f"Removed {removed} pending assignment(s). {protected} assignment(s) were already started, done, or skipped, so they were preserved."
        )
    st.rerun()


# ── Page: Export ──────────────────────────────────────────────────────────────

_SEV = {1: "Good", 2: "Bad"}


def page_export(admin: dict) -> None:
    _html('<div class="adm-title">Export</div>'
          '<div class="adm-sub">Download completed annotation results.</div>')

    jobs = get_all_jobs()
    if not jobs:
        st.info("No annotations saved yet.")
        return

    job = st.selectbox(
        "Batch",
        jobs,
        format_func=lambda j: f'{j["name"]} ({str(j["id"])[:8]})',
    )

    rows = get_all_annotations_for_job(job["id"], None)
    if not rows:
        st.info("No completed annotations in this batch yet.")
        return

    n_good    = sum(1 for r in rows if r["overall_severity"] == 1)
    n_bad     = sum(1 for r in rows if r["overall_severity"] == 2)
    n_skipped = sum(1 for r in rows if r.get("skip_reason"))
    c1, c2, c3, c4 = st.columns(4)
    _metric(c1, len(rows), "Total",   "#0f172a")
    _metric(c2, n_good,    "Good",    "#166534", "#f0fdf4", "#bbf7d0")
    _metric(c3, n_bad,     "Bad",     "#991b1b", "#fef2f2", "#fecaca")
    _metric(c4, n_skipped, "Skipped", "#6b7280", "#f9fafb", "#e5e7eb")

    st.divider()
    _html('<div class="adm-section">Preview</div>')

    st.dataframe(
        [{"Filename":  r["filename"],
          "Annotator": r["annotator_name"],
          "Rating":    _SEV.get(r["overall_severity"], "—"),
          "Defects":   len(r["defects"] or []),
          "Status":    r["status"],
          "Saved at":  str(r["saved_at"])[:16] if r.get("saved_at") else "—"}
         for r in rows],
        use_container_width=True, hide_index=True,
    )

    st.divider()
    _html('<div class="adm-section">Download</div>')
    c1, c2 = st.columns(2)

    buf    = io.StringIO()
    fields = ["image_id", "filename", "s3_key", "annotator_id", "annotator_name",
              "assigned_by_admin_id", "assigned_by_admin", "batch_id", "batch_name",
              "status", "overall_severity", "skip_reason", "saved_at", "defect_count"]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        r2 = dict(r)
        r2["defect_count"] = len(r2.get("defects") or [])
        w.writerow(r2)

    slug = job["name"].replace(" ", "_")
    c1.download_button("Download CSV",  data=buf.getvalue().encode(),
                       file_name=f"{slug}_annotations.csv", mime="text/csv",
                       use_container_width=True)
    c2.download_button("Download JSON", data=json.dumps(rows, default=str, indent=2).encode(),
                       file_name=f"{slug}_annotations.json", mime="application/json",
                       use_container_width=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(CSS,       unsafe_allow_html=True)
    st.markdown(ADMIN_CSS, unsafe_allow_html=True)

    user = _require_admin()
    admin = st.session_state["db_annotator"]
    page = _sidebar(user)

    if page == "Progress":
        page_progress(admin)
    elif page == "Team":
        page_team(admin)
    elif page == "Assign Images":
        page_assign(admin)
    elif page == "Export":
        page_export(admin)


if __name__ == "__main__":
    main()
