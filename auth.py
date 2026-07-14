"""
auth.py — Cognito login UI and JWT verification for Bean Annotator.
"""

import json
import os
import time
import hmac
import hashlib
import base64
import urllib.request
from typing import Any

import boto3
import streamlit as st
from jose import jwk, jwt
from jose.utils import base64url_decode
from streamlit_cookies_controller import CookieController

# ── Config ────────────────────────────────────────────────────────────────────

REGION        = os.environ.get("AWS_REGION",             "us-east-1")
USER_POOL_ID  = os.environ.get("COGNITO_USER_POOL_ID",   "")
CLIENT_ID     = os.environ.get("COGNITO_CLIENT_ID",      "")
CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET",  "")
JWKS_URL      = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"

_AUTH_COOKIE_NAME = "bean_auth"
_AUTH_COOKIE_MAX_AGE = 29 * 24 * 3600  # just under Cognito's default 30-day refresh-token validity


def _secret_hash(username: str) -> str:
    """Compute SECRET_HASH required when the app client has a secret."""
    msg = (username + CLIENT_ID).encode()
    key = CLIENT_SECRET.encode()
    return base64.b64encode(hmac.new(key, msg, digestmod=hashlib.sha256).digest()).decode()

_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0
JWKS_TTL = 3600  # seconds


# ── JWKS helpers ──────────────────────────────────────────────────────────────

def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or (time.time() - _jwks_fetched_at) > JWKS_TTL:
        with urllib.request.urlopen(JWKS_URL) as resp:
            _jwks_cache = json.loads(resp.read())
        _jwks_fetched_at = time.time()
    return _jwks_cache


def verify_token(id_token: str) -> dict:
    """Verify a Cognito ID token and return its claims. Raises on invalid."""
    headers = jwt.get_unverified_headers(id_token)
    kid = headers["kid"]

    jwks = _get_jwks()
    key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if key_data is None:
        raise ValueError("Public key not found in JWKS")

    public_key = jwk.construct(key_data)
    message, encoded_sig = id_token.rsplit(".", 1)
    decoded_sig = base64url_decode(encoded_sig.encode())
    if not public_key.verify(message.encode(), decoded_sig):
        raise ValueError("Token signature verification failed")

    claims = jwt.get_unverified_claims(id_token)
    if claims.get("iss") != f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}":
        raise ValueError("Token issuer mismatch")
    if claims.get("token_use") != "id":
        raise ValueError("Expected id token")
    if claims.get("exp", 0) < time.time():
        raise ValueError("Token expired")

    return claims


# ── Cognito auth call ─────────────────────────────────────────────────────────

def _cognito_login(username: str, password: str) -> dict:
    """Call Cognito USER_PASSWORD_AUTH. Returns token dict or raises."""
    client = boto3.client("cognito-idp", region_name=REGION)
    auth_params = {"USERNAME": username, "PASSWORD": password}
    if CLIENT_SECRET:
        auth_params["SECRET_HASH"] = _secret_hash(username)
    resp = client.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters=auth_params,
        ClientId=CLIENT_ID,
    )
    return resp["AuthenticationResult"]


def _cognito_refresh(refresh_token: str, username: str) -> dict:
    client = boto3.client("cognito-idp", region_name=REGION)
    auth_params = {"REFRESH_TOKEN": refresh_token}
    if CLIENT_SECRET:
        auth_params["SECRET_HASH"] = _secret_hash(username)
    resp = client.initiate_auth(
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters=auth_params,
        ClientId=CLIENT_ID,
    )
    tokens = resp["AuthenticationResult"]
    tokens["RefreshToken"] = refresh_token
    return tokens


def _cookie_controller() -> CookieController:
    return CookieController(key="auth_cookies")


def _set_auth_cookie(tokens: dict, user: dict) -> None:
    refresh_token = tokens.get("RefreshToken")
    if not refresh_token:
        print(f"[AUTH_DEBUG] _set_auth_cookie: no RefreshToken in tokens dict for {user.get('username')!r}", flush=True)
        return
    payload = json.dumps({"refresh_token": refresh_token, "username": user["username"]})
    _cookie_controller().set(
        _AUTH_COOKIE_NAME,
        payload,
        max_age=_AUTH_COOKIE_MAX_AGE,
        same_site="lax",
        secure=True,
    )
    print(f"[AUTH_DEBUG] _set_auth_cookie: wrote cookie for {user['username']!r}", flush=True)


def _clear_auth_cookie() -> None:
    try:
        _cookie_controller().remove(_AUTH_COOKIE_NAME)
    except Exception:
        pass


def _user_from_claims(claims: dict, username: str) -> dict:
    groups = claims.get("cognito:groups", [])
    role = "admin" if "admins" in groups else "annotator"
    return {
        "sub":      claims["sub"],
        "name":     claims.get("name", username),
        "email":    claims.get("email", ""),
        "role":     role,
        "groups":   groups,
        "username": username,
    }


# ── Session helpers ───────────────────────────────────────────────────────────

def get_current_user() -> dict | None:
    """Return the logged-in user dict from session state, or None."""
    user = st.session_state.get("auth_user")
    if user:
        return user
    return None


def logout():
    for key in ("auth_user", "auth_tokens"):
        st.session_state.pop(key, None)
    _clear_auth_cookie()
    st.rerun()


# ── Login UI ──────────────────────────────────────────────────────────────────

def _try_restore_session() -> dict | None:
    """Silently re-authenticate from the refresh token in the auth cookie.

    On a hard page refresh, Streamlit opens a brand-new session and
    session_state is empty, even though the user is still validly logged
    in from Cognito's point of view. This rebuilds that session from the
    cookie instead of forcing a fresh login.
    """
    try:
        raw = _cookie_controller().get(_AUTH_COOKIE_NAME)
    except TypeError:
        # CookieController.__cookies is None on the very first script run before
        # the browser component has responded — treat as no cookie present.
        return None
    print(f"[AUTH_DEBUG] _try_restore_session: cookie raw = {raw!r}", flush=True)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        refresh_token = data["refresh_token"]
        username = data["username"]
    except Exception as exc:
        print(f"[AUTH_DEBUG] _try_restore_session: cookie payload parse failed: {exc!r}", flush=True)
        return None

    try:
        tokens = _cognito_refresh(refresh_token, username)
        claims = verify_token(tokens["IdToken"])
        user = _user_from_claims(claims, username)
    except Exception as exc:
        print(f"[AUTH_DEBUG] _try_restore_session: refresh/verify failed for {username!r}: {exc!r}", flush=True)
        _clear_auth_cookie()
        return None

    print(f"[AUTH_DEBUG] _try_restore_session: restored session for {username!r}", flush=True)
    st.session_state["auth_tokens"] = tokens
    st.session_state["auth_user"] = user
    _set_auth_cookie(tokens, user)
    return user


def require_login(login_title: str | None = None) -> dict:
    """
    Call at the top of every page. If not logged in, shows the login form
    and stops execution (st.stop()). Returns the user dict if already logged in.
    """
    user = get_current_user()
    if user:
        return user

    user = _try_restore_session()
    if user:
        return user

    login_title = login_title or st.session_state.get("login_title")
    _render_login_form(login_title=login_title)
    st.stop()


_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "Lab Logo white.jpg")


def _logo_b64() -> str:
    with open(_LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _render_login_form(login_title: str | None = None):
    try:
        logo_b64  = _logo_b64()
        logo_data = f"data:image/jpeg;base64,{logo_b64}"
    except FileNotFoundError:
        logo_data = None

    st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background: #f1f5f0 !important; }
    [data-testid="stHeader"] { background: transparent !important; }
    .block-container { padding-top: 4rem !important; }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        # Green header with white logo
        logo_html = (
            f'<img src="{logo_data}" style="height:100px;object-fit:contain;" />'
            if logo_data else
            '<div style="font-size:1.2rem;font-weight:800;color:#fff;">MSU Bean Lab</div>'
        )
        st.markdown(
            f'<div style="background:#18453b;border-radius:12px 12px 0 0;'
            f'padding:32px 24px 28px;text-align:center;">'
            f'{logo_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

        title_html = ""
        if login_title:
            title_html = (
                '<div style="font-size:1.05rem;color:#18453b;font-weight:900;'
                'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:10px;">'
                f'{login_title}</div>'
            )

        # White card body
        st.markdown(
            '<div style="background:#fff;border-radius:0 0 12px 12px;'
            'box-shadow:0 4px 24px rgba(0,0,0,0.10);padding:28px 36px 32px;">'
            '<div style="text-align:center;margin-bottom:24px;">'
            f'{title_html}'
            '<div style="font-size:1.35rem;font-weight:900;color:#0f172a;letter-spacing:-0.02em;">'
            'Bean Annotation</div>'
            '<div style="font-size:0.82rem;color:#6b7280;margin-top:6px;font-weight:500;">'
            'Sign in to continue</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        with st.form("login_form"):
            username = st.text_input("Username or email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", width="stretch")

        if submitted:
            if not username or not password:
                st.error("Enter both username and password.")
                return

            with st.spinner("Signing in…"):
                try:
                    tokens  = _cognito_login(username, password)
                    claims  = verify_token(tokens["IdToken"])
                    user = _user_from_claims(claims, username)
                    st.session_state["auth_tokens"] = tokens
                    st.session_state["auth_user"] = user
                    _set_auth_cookie(tokens, user)
                    st.rerun()
                except Exception as exc:
                    msg = str(exc)
                    if "NotAuthorizedException" in msg or "UserNotFoundException" in msg:
                        st.error("Incorrect username or password.")
                    elif "UserNotConfirmedException" in msg:
                        st.error("Account not confirmed. Contact your admin.")
                    elif "PasswordResetRequiredException" in msg:
                        st.error("Password reset required. Contact your admin.")
                    else:
                        st.error(f"Login failed: {msg}")
