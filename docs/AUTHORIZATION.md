# Authentication And Authorization

## Identity Provider

Authentication uses AWS Cognito.

Environment variables:

- `AWS_REGION`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `COGNITO_CLIENT_SECRET`

## Login Flow

1. User enters username/password in the Streamlit login form.
2. `auth.py` calls Cognito `USER_PASSWORD_AUTH`.
3. Cognito returns tokens.
4. The ID token is verified against the Cognito JWKS endpoint.
5. App role is derived from Cognito groups.
6. Tokens are stored in Streamlit session state.
7. Refresh token is stored in a secure browser cookie.

## Refresh Behavior

Streamlit loses `st.session_state` on hard refresh. To avoid forcing users back
to login, `auth.py` stores the Cognito refresh token in a cookie and restores the
session silently when possible.

If refresh fails, the cookie is cleared and the user is shown the login form.

## Roles

| Cognito Group | App Role | App |
| --- | --- | --- |
| `admins` | `admin` | Admin dashboard |
| `annotators` or no admin group | `annotator` | Annotator dashboard |

The admin app calls `_require_admin`; non-admin users are denied.

## Admin Permissions

All admins can view:

- all active annotators
- global progress
- global assignment summaries
- global exports

Only the owner admin can:

- manage an annotator they created
- view that annotator's stored generated password
- deactivate that annotator
- assign work to that annotator
- reduce pending assignments for that annotator

Ownership is stored in `annotators.created_by_admin`.

## Annotator Permissions

Annotators see only their own queue:

```sql
WHERE assignments.annotator_id = <current annotator id>
```

Annotators cannot assign images, create users, export global data, or view other
annotators' progress.

## Password Visibility Note

The current prototype stores generated annotator passwords in
`annotators.admin_visible_password` so the owning admin can view and share them.
This is convenient for a controlled research workflow but should be replaced
with a reset/invite flow for a stricter security posture.

