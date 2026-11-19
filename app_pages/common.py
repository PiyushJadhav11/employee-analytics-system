
"""Shared helpers for Streamlit pages: managers, authorization, lookups and UI."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timedelta, timezone
from html import escape

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hr_analytics.db_manager import DatabaseError  # noqa: E402
from hr_analytics.managers import (  # noqa: E402
    AnalyticsManager, EmployeeManager, EtlManager, LookupManager, ManagerError,
    ProjectManager, ReconciliationManager, ReviewManager,
)
from hr_analytics.models import ValidationError  # noqa: E402
from hr_analytics.auth import AuthManager, Principal  # noqa: E402
from hr_analytics.permission import AuthorizationManager, AuthorizationError  # noqa: E402

PLOTLY_TEMPLATE = "plotly_dark"

DEPT_COLORS = {
    "Research & Development": "#63CBB5",
    "Sales": "#D9B477",
    "Human Resources": "#829ED0",
    "All departments": "#AAB7C4",
}


# ---------------------------------------------------------------------
# CACHED MANAGERS
# ---------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def managers() -> dict[str, Any]:
    """One instance of each manager per server process."""
    return {
        "lookup": LookupManager(),
        "employee": EmployeeManager(),
        "project": ProjectManager(),
        "review": ReviewManager(),
        "analytics": AnalyticsManager(),
        "etl": EtlManager(),
        "recon": ReconciliationManager(),
    }


@st.cache_resource(show_spinner=False)
def auth_manager() -> AuthManager:
    return AuthManager()


# ---------------------------------------------------------------------
# SESSION MANAGEMENT
# ---------------------------------------------------------------------

def start_session(principal: Principal) -> None:
    """Start a clean authenticated session."""
    for key in list(st.session_state.keys()):
        if key.startswith("auth_") or key in {
            "principal", "authenticated", "user_id", "email",
            "display_name", "employee_id", "roles", "permissions",
            "department_ids", "manageable_department_ids",
            "session_started_at", "last_activity_at",
        }:
            del st.session_state[key]

    now = datetime.now(timezone.utc)

    st.session_state.authenticated = True
    st.session_state.principal = principal
    st.session_state.user_id = principal.user_id
    st.session_state.email = principal.email
    st.session_state.display_name = principal.display_name
    st.session_state.employee_id = principal.employee_id
    st.session_state.roles = principal.roles
    st.session_state.permissions = principal.permissions
    st.session_state.department_ids = principal.department_ids
    st.session_state.manageable_department_ids = principal.manageable_department_ids
    st.session_state.session_started_at = now
    st.session_state.last_activity_at = now


def logout() -> None:
    uid = st.session_state.get("user_id")

    if uid:
        auth_manager().audit(
            int(uid), "LOGOUT", "SUCCESS", "user", str(uid)
        )

    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.rerun()


def current_principal(refresh: bool = True) -> Principal:
    """Return the authenticated principal and enforce session expiry."""
    if (
        not st.session_state.get("authenticated")
        or not st.session_state.get("user_id")
    ):
        st.switch_page("app_pages/login.py")

    now = datetime.now(timezone.utc)
    started = st.session_state.get("session_started_at")
    last = st.session_state.get("last_activity_at")

    if (
        not started
        or not last
        or now - started > timedelta(hours=8)
        or now - last > timedelta(minutes=30)
    ):
        logout()

    uid = int(st.session_state.user_id)

    principal = (
        auth_manager().load_principal(uid)
        if refresh
        else st.session_state.get("principal")
    )

    if principal is None:
        logout()

    st.session_state.principal = principal
    st.session_state.roles = principal.roles
    st.session_state.permissions = principal.permissions
    st.session_state.department_ids = principal.department_ids
    st.session_state.manageable_department_ids = (
        principal.manageable_department_ids
    )
    st.session_state.last_activity_at = now

    return principal


# ---------------------------------------------------------------------
# ACCESS DENIED UI
# ---------------------------------------------------------------------

def render_access_denied(
    required_permission: str | None = None,
    required_permissions: tuple[str, ...] | None = None,
    stop: bool = True,
) -> None:
    """
    Display a consistent access-denied screen.

    stop=True:
        Stop execution of a protected page.

    stop=False:
        Display the denial message but allow the rest of the page to remain.
        Used when a button/action is rejected.
    """
    permissions = []

    if required_permission:
        permissions.append(required_permission)

    if required_permissions:
        permissions.extend(required_permissions)

    permissions = list(dict.fromkeys(permissions))

    permission_html = "".join(
        f'<span class="access-permission">{escape(p)}</span>'
        for p in permissions
    )

    if not permission_html:
        permission_html = (
            '<span class="access-permission">Permission required</span>'
        )

    st.markdown(
        """
        <style>
        .access-denied-card {
            margin: 2.5rem auto;
            max-width: 780px;
            padding: 2.2rem;
            border: 1px solid rgba(255, 125, 115, 0.30);
            border-radius: 20px;
            background: linear-gradient(
                145deg,
                rgba(35, 49, 65, 0.96),
                rgba(20, 32, 47, 0.98)
            );
            box-shadow: 0 18px 55px rgba(0, 0, 0, 0.25);
            text-align: center;
        }

        .access-denied-icon {
            width: 76px;
            height: 76px;
            margin: 0 auto 1.2rem auto;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: rgba(239, 91, 83, 0.13);
            border: 1px solid rgba(255, 125, 115, 0.30);
            font-size: 2.2rem;
        }

        .access-denied-eyebrow {
            color: #FF9B91;
            font-size: 0.75rem;
            font-weight: 750;
            letter-spacing: 2px;
            margin-bottom: 0.65rem;
        }

        .access-denied-title {
            color: #F1F5F9;
            font-size: 2rem;
            font-weight: 760;
            margin-bottom: 0.65rem;
        }

        .access-denied-description {
            color: #AFC0CD;
            font-size: 1rem;
            line-height: 1.7;
            max-width: 570px;
            margin: 0 auto 1.5rem auto;
        }

        .access-permission-panel {
            text-align: left;
            padding: 1rem 1.2rem;
            border-radius: 12px;
            background: rgba(9, 19, 31, 0.50);
            border: 1px solid rgba(148, 170, 190, 0.17);
            margin-top: 1.2rem;
        }

        .access-permission-label {
            color: #91A7B7;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 1.3px;
            margin-bottom: 0.75rem;
        }

        .access-permission {
            display: inline-block;
            color: #8AE2D0;
            background: rgba(99, 203, 181, 0.10);
            border: 1px solid rgba(99, 203, 181, 0.24);
            border-radius: 7px;
            padding: 6px 10px;
            margin: 3px 5px 3px 0;
            font-family: monospace;
            font-size: 0.82rem;
            overflow-wrap: anywhere;
        }

        .access-denied-footer {
            color: #8296A7;
            font-size: 0.84rem;
            line-height: 1.6;
            margin-top: 1.4rem;
        }

        @media (max-width: 600px) {
            .access-denied-card {
                padding: 1.3rem;
                margin: 1rem auto;
            }
            .access-denied-title {
                font-size: 1.55rem;
            }
        }
        </style>

        <div class="access-denied-card">
            <div class="access-denied-icon">🔒</div>
            <div class="access-denied-eyebrow">
                403 · FORBIDDEN
            </div>
            <div class="access-denied-title">
                Access Denied
            </div>
            <div class="access-denied-description">
                Your account does not have the required permission
                to access this page or perform this operation.
                Your access restrictions are enforced by the
                platform's authorization system.
            </div>
            <div class="access-permission-panel">
                <div class="access-permission-label">
                    REQUIRED PERMISSION
                </div>
        """
        + permission_html
        + """
            </div>
            <div class="access-denied-footer">
                If you believe you should have access, contact your
                System Administrator to review your role and permissions.
                <br>
                No protected information has been displayed.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if stop:
        st.stop()


# ---------------------------------------------------------------------
# PAGE-LEVEL PERMISSION CHECKS
# ---------------------------------------------------------------------

def require_permission(permission: str) -> Principal:
    """
    Require one permission.

    AuthorizationError is converted into a styled denial screen,
    rather than an uncaught Streamlit traceback.
    """
    principal = current_principal()

    try:
        AuthorizationManager(auth_manager()).require_permission(
            principal, permission
        )
    except AuthorizationError:
        render_access_denied(required_permission=permission, stop=True)

    return principal


def require_any_permission(*permissions: str) -> Principal:
    """Require at least one permission from the supplied list."""
    principal = current_principal()

    if not any(p in principal.permissions for p in permissions):
        auth_manager().audit(
            principal.user_id,
            "AUTHORIZATION_DENIED",
            "DENIED",
            "page",
            ",".join(permissions),
        )

        render_access_denied(
            required_permissions=permissions,
            stop=True,
        )

    return principal


# ---------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------

def render_sidebar() -> None:
    principal = current_principal()

    st.sidebar.caption(f"Signed in as **{principal.display_name}**")
    st.sidebar.caption(" · ".join(sorted(principal.roles)) or "No role assigned")

    if st.sidebar.button("Log out", use_container_width=True):
        logout()


# ---------------------------------------------------------------------
# AUTHORIZED MANAGER PROXY
# ---------------------------------------------------------------------

class AuthorizedManagerProxy:
    """Bind app-layer manager calls to the authenticated principal."""

    def __init__(self, name: str, manager: Any, principal: Principal):
        self.name = name
        self.manager = manager
        self.principal = principal
        self.authz = AuthorizationManager(auth_manager())

    def __getattr__(self, method_name: str):
        method = getattr(self.manager, method_name)

        if not callable(method):
            return method

        def authorized(*args, **kwargs):
            p = self.principal

            audit_action = {
                ("employee", "onboard"): "EMPLOYEE_ONBOARD",
                ("employee", "change_position"): "EMPLOYEE_TRANSFER_OR_PROMOTION",
                ("employee", "terminate"): "EMPLOYEE_TERMINATE",
                ("project", "create"): "PROJECT_CREATE",
                ("project", "assign"): "PROJECT_ASSIGN",
                ("review", "submit"): "REVIEW_CREATE",
                ("etl", "run_full_etl"): "ETL_RUN",
                ("recon", "run"): "RECONCILIATION_RUN",
            }.get((self.name, method_name))

            def invoke():
                try:
                    result = method(*args, **kwargs)
                except Exception as exc:
                    if audit_action:
                        auth_manager().audit(
                            p.user_id,
                            audit_action,
                            "FAILED",
                            self.name,
                            details=f"error_type={type(exc).__name__}",
                        )
                    raise

                if audit_action:
                    resource_id = getattr(result, "id", None)
                    auth_manager().audit(
                        p.user_id,
                        audit_action,
                        "SUCCESS",
                        self.name,
                        str(resource_id) if resource_id is not None else None,
                    )

                return result

            if self.name == "lookup":
                if method_name == "search_employees":
                    if (
                        "employee.view_all" not in p.permissions
                        and "employee.view_self" not in p.permissions
                    ):
                        kwargs.setdefault(
                            "department_ids", sorted(p.department_ids)
                        )
                    elif (
                        "employee.view_self" in p.permissions
                        and "employee.view_all" not in p.permissions
                    ):
                        kwargs.setdefault("department_ids", [])
                        kwargs.setdefault("employee_id", p.employee_id)

                return invoke()

            if self.name == "employee":
                permission = {
                    "onboard": "employee.create",
                    "change_position": "employee.transfer",
                    "terminate": "employee.terminate",
                }.get(method_name)

                if permission:
                    self.authz.require_permission(p, permission)

                if method_name in {"get", "oltp_history", "dw_versions"} and args:
                    self.authz.require_employee(
                        p, int(args[0]), write=False
                    )

                elif method_name in {"change_position", "terminate"} and args:
                    self.authz.require_employee(
                        p, int(args[0]), write=True
                    )

                    if method_name == "change_position":
                        self.authz.require_department(
                            p, int(args[1]), manage=True
                        )

                elif method_name == "onboard" and args:
                    self.authz.require_department(
                        p, int(args[0].department_id), manage=True
                    )

                return invoke()

            if self.name == "project":
                if method_name == "create" and args:
                    self.authz.require_permission(p, "project.create")
                    self.authz.require_department(
                        p, int(args[0].department_id), manage=True
                    )

                elif method_name == "assign" and len(args) >= 2:
                    self.authz.require_permission(p, "project.assign")
                    self.authz.require_employee(
                        p, int(args[0]), write=True
                    )
                    self.authz.require_project(
                        p, int(args[1]), manage=True
                    )

                elif method_name == "list":
                    if (
                        "employee.view_all" not in p.permissions
                        and "analytics.view_all" not in p.permissions
                    ):
                        if not p.department_ids:
                            return pd.DataFrame()

                        kwargs.setdefault(
                            "department_ids", sorted(p.department_ids)
                        )

                elif method_name == "bottlenecks":
                    self.authz.require_permission(
                        p, "analytics.view_all"
                    )

                return invoke()

            if self.name == "review":
                if method_name == "submit" and args:
                    self.authz.require_permission(p, "review.create")
                    self.authz.require_employee(
                        p, int(args[0].employee_id), write=True
                    )

                elif method_name == "for_employee" and args:
                    self.authz.require_employee(
                        p, int(args[0]), write=False
                    )

                return invoke()

            if self.name == "analytics":
                self.authz.require_permission(
                    p, "analytics.view_all"
                )
                return invoke()

            if self.name == "etl":
                self.authz.require_permission(p, "etl.run")
                return invoke()

            if self.name == "recon":
                self.authz.require_permission(
                    p, "reconciliation.run"
                )
                return invoke()

            return invoke()

        return authorized


def get(name: str) -> Any:
    try:
        principal = current_principal()
        return AuthorizedManagerProxy(
            name, managers()[name], principal
        )

    except DatabaseError as exc:
        st.error(f"**Database unavailable.** {exc}")
        st.info(
            "Check the connection settings in `.env` (local) or "
            "`.streamlit/secrets.toml` / app secrets (cloud)."
        )
        st.stop()


# ---------------------------------------------------------------------
# STANDARDIZED OPERATION ERROR HANDLING
# ---------------------------------------------------------------------

def run(
    action: Callable[[], Any],
    success: str | None = None,
) -> Any:
    """
    Execute a manager operation and display expected errors cleanly.

    Authorization errors do not produce Python tracebacks.
    """
    try:
        result = action()

    except ValidationError as exc:
        st.warning(str(exc))
        return None

    except ManagerError as exc:
        st.error(str(exc))
        return None

    except AuthorizationError:
        render_access_denied(stop=False)
        return None

    if success:
        st.success(success)

    return result


# ---------------------------------------------------------------------
# LOOKUPS AND PICKERS
# ---------------------------------------------------------------------

def departments() -> pd.DataFrame:
    df = get("lookup").departments()

    if st.session_state.get("authenticated"):
        principal = current_principal()

        if (
            "employee.view_all" not in principal.permissions
            and "analytics.view_all" not in principal.permissions
        ):
            df = df[
                df.department_id.isin(principal.department_ids)
            ]

    return df


def roles() -> pd.DataFrame:
    return get("lookup").roles()


def department_picker(
    label: str,
    key: str,
    default_id: int | None = None,
) -> int:
    d = departments()
    ids = d["department_id"].tolist()

    if not ids:
        st.error(
            "No department access is assigned to your account. "
            "Contact a System Admin."
        )
        st.stop()

    idx = ids.index(default_id) if default_id in ids else 0

    return st.selectbox(
        label,
        ids,
        index=idx,
        key=key,
        format_func=lambda i: d.set_index("department_id").loc[
            i, "department_name"
        ],
    )


def role_picker(
    label: str,
    department_id: int,
    key: str,
    default_id: int | None = None,
) -> int:
    r = roles()
    r = r[r["department_id"] == department_id]
    ids = r["job_role_id"].tolist()

    idx = ids.index(default_id) if default_id in ids else 0

    return st.selectbox(
        label,
        ids,
        index=idx,
        key=key,
        format_func=lambda i: r.set_index("job_role_id").loc[
            i, "role_name"
        ],
    )


def employee_picker(
    label: str = "Find employee (number, name or email)",
    key: str = "emp",
    active_only: bool = True,
) -> dict | None:
    term = st.text_input(
        label,
        key=f"{key}_term",
        placeholder="e.g. 100042 or priya",
    )

    if not term:
        return None

    principal = current_principal()

    if "employee.view_all" in principal.permissions:
        scope_ids = None
        self_id = None

    elif (
        "employee.view_self" in principal.permissions
        and principal.employee_id is not None
    ):
        scope_ids = []
        self_id = principal.employee_id

    else:
        scope_ids = sorted(principal.department_ids)
        self_id = None

    found = run(
        lambda: get("lookup").search_employees(
            term,
            active_only=active_only,
            limit=25,
            department_ids=scope_ids,
            employee_id=self_id,
        )
    )

    if found is None or found.empty:
        st.info("No matching employees.")
        return None

    labels = {
        int(r.employee_id):
            f"#{r.employee_number} · {r.full_name} · "
            f"{r.department_name} · {r.job_role}"
        for r in found.itertuples()
    }

    chosen = st.selectbox(
        "Select",
        list(labels),
        format_func=labels.get,
        key=f"{key}_select",
    )

    return (
        found.set_index("employee_id").loc[chosen].to_dict()
        | {"employee_id": chosen}
    )


# ---------------------------------------------------------------------
# IDEMPOTENCY
# ---------------------------------------------------------------------

def request_key(operation: str, payload: dict) -> str:
    """Generate a stable idempotency key for a form submission."""
    nonce = st.session_state.setdefault(
        "_session_nonce", str(uuid.uuid4())
    )

    body = json.dumps(payload, sort_keys=True, default=str)

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{nonce}|{operation}|{body}",
        )
    )


# ---------------------------------------------------------------------
# WRITE RESULT DISPLAY
# ---------------------------------------------------------------------

def show_write_result(result) -> None:
    """Display write result and warehouse sync status."""
    if result is None:
        return

    if result.replayed:
        st.info(
            f"Already done — {result.message} "
            "(duplicate submission ignored, nothing written twice)"
        )
    else:
        st.success(result.message)

    dw_sync_note(result)


def dw_sync_note(result) -> None:
    if result is not None and not result.dw_synced:
        st.warning(
            "Saved to OLTP, but the warehouse sync failed. "
            "Run the ETL from **ETL & Data Ops** to catch up."
        )


# ---------------------------------------------------------------------
# SHARED APPLICATION THEME
# ---------------------------------------------------------------------

def apply_theme() -> None:
    """Apply the shared dark navy, teal and glass-inspired theme."""

    st.markdown(
        """
        <style>
        :root {
            --app-bg: #0B1220;
            --app-bg-soft: #111C2C;
            --glass: rgba(24, 39, 57, 0.76);
            --glass-strong: rgba(29, 46, 65, 0.90);
            --glass-border: rgba(148, 170, 190, 0.17);
            --glass-border-hover: rgba(99, 203, 181, 0.48);
            --text-primary: #EDF4F8;
            --text-secondary: #9AABBA;
            --accent: #63CBB5;
            --accent-light: #8AE2D0;
            --accent-blue: #829ED0;
            --accent-amber: #D9B477;
        }

        .stApp {
            background:
                radial-gradient(ellipse at 8% 5%,
                    rgba(50,112,116,0.17), transparent 34%),
                radial-gradient(ellipse at 92% 16%,
                    rgba(77,103,153,0.14), transparent 32%),
                linear-gradient(145deg,
                    #0B1220 0%, #101C2B 52%, #0B1421 100%);
            color: var(--text-primary);
        }

        [data-testid="stAppViewContainer"] {
            background: transparent;
        }

        [data-testid="stHeader"] {
            background: rgba(11,18,32,0.60);
            backdrop-filter: blur(14px);
        }

        .block-container {
            max-width: 1500px;
            padding-top: 2.2rem;
            padding-bottom: 3.5rem;
        }

        h1 {
            color: var(--text-primary) !important;
            font-weight: 750 !important;
            letter-spacing: -1.15px;
            line-height: 1.15 !important;
        }

        h2 {
            color: #E8F0F5 !important;
            font-weight: 680 !important;
            letter-spacing: -0.45px;
        }

        h3 {
            color: #DDE8EF !important;
            font-weight: 630 !important;
        }

        p, label, li {
            color: #D1DCE5;
        }

        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            color: var(--text-secondary) !important;
        }

        [data-testid="stMarkdownContainer"] strong {
            color: #F0F5F8;
        }

        code {
            color: var(--accent-light) !important;
            background: rgba(99,203,181,0.09) !important;
            border-radius: 5px;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(
                180deg,
                rgba(21,34,49,0.97),
                rgba(13,24,38,0.98)
            ) !important;
            border-right: 1px solid var(--glass-border);
            box-shadow: 10px 0 40px rgba(0,0,0,0.16);
        }

        [data-testid="stSidebar"] > div:first-child {
            background: transparent;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: #C2D0DA;
        }

        [data-testid="stSidebar"] hr {
            border-color: var(--glass-border);
        }

        [data-testid="stSidebarNavLink"] {
            position: relative;
            border-radius: 11px !important;
            padding: 0.58rem 0.72rem !important;
            margin: 3px 0 !important;
            border: 1px solid transparent !important;
            color: #C7D4DE !important;
            transition: all 180ms ease;
        }

        [data-testid="stSidebarNavLink"]:hover {
            background: rgba(99,203,181,0.09) !important;
            border-color: rgba(99,203,181,0.20) !important;
            color: #F2FAF8 !important;
            transform: translateX(2px);
        }

        [data-testid="stSidebarNavLink"][aria-current="page"] {
            background: linear-gradient(
                105deg,
                rgba(99,203,181,0.19),
                rgba(99,203,181,0.06)
            ) !important;
            border: 1px solid rgba(99,203,181,0.34) !important;
            color: #A3EBDD !important;
            box-shadow: 0 4px 18px rgba(35,133,116,0.10);
        }

        [data-testid="stSidebarNavLink"]::before {
            content: "";
            display: inline-block;
            width: 7px;
            height: 7px;
            min-width: 7px;
            border-radius: 50%;
            background: #64798A;
            margin-right: 10px;
            vertical-align: middle;
            box-shadow: 0 0 0 3px rgba(148,170,190,0.08);
            transition: all 180ms ease;
        }

        [data-testid="stSidebarNavLink"]:hover::before {
            background: var(--accent-light);
            box-shadow: 0 0 0 4px rgba(99,203,181,0.13);
        }

        [data-testid="stSidebarNavLink"][aria-current="page"]::before {
            width: 8px;
            height: 8px;
            background: var(--accent);
            box-shadow:
                0 0 0 4px rgba(99,203,181,0.15),
                0 0 12px rgba(99,203,181,0.55);
        }

        [data-testid="stMetric"] {
            position: relative;
            overflow: hidden;
            background: linear-gradient(
                145deg,
                rgba(37,57,76,0.82),
                rgba(23,39,56,0.78)
            ) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            padding: 19px 20px !important;
            box-shadow:
                0 9px 26px rgba(0,0,0,0.16),
                inset 0 1px 0 rgba(255,255,255,0.035);
            backdrop-filter: blur(15px);
            transition: all 180ms ease;
        }

        [data-testid="stMetric"]:hover {
            transform: translateY(-3px);
            border-color: var(--glass-border-hover) !important;
            box-shadow: 0 13px 30px rgba(0,0,0,0.22);
        }

        [data-testid="stMetricLabel"] {
            color: #A9BAC7 !important;
            font-size: 0.88rem !important;
            font-weight: 550 !important;
        }

        [data-testid="stMetricValue"] {
            color: #F0F6F8 !important;
            font-size: 1.85rem !important;
            font-weight: 740 !important;
            letter-spacing: -0.8px;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            background: linear-gradient(
                145deg,
                rgba(29,46,65,0.70),
                rgba(19,33,49,0.72)
            ) !important;
            box-shadow: 0 10px 30px rgba(0,0,0,0.12);
            backdrop-filter: blur(14px);
        }

        .stButton > button,
        .stFormSubmitButton > button,
        [data-testid="stDownloadButton"] > button {
            min-height: 2.65rem;
            border-radius: 10px !important;
            font-weight: 650 !important;
            border: 1px solid rgba(148,170,190,0.24);
            transition: all 180ms ease;
        }

        .stButton > button:hover,
        .stFormSubmitButton > button:hover,
        [data-testid="stDownloadButton"] > button:hover {
            border-color: var(--accent) !important;
            transform: translateY(-1px);
            box-shadow: 0 6px 18px rgba(0,0,0,0.17);
        }

        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: linear-gradient(
                110deg, #63CBB5, #72D4C0
            ) !important;
            color: #10231F !important;
            border: 1px solid #72D4C0 !important;
            font-weight: 720 !important;
            box-shadow: 0 5px 17px rgba(65,184,158,0.16);
        }

        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"] > div {
            background: rgba(28,44,61,0.86) !important;
            border: 1px solid rgba(148,170,190,0.23) !important;
            border-radius: 10px !important;
        }

        div[data-baseweb="input"] > div:focus-within,
        div[data-baseweb="select"] > div:focus-within,
        div[data-baseweb="textarea"] > div:focus-within {
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px rgba(99,203,181,0.12) !important;
        }

        input, textarea {
            color: var(--text-primary) !important;
        }

        [data-baseweb="select"] span {
            color: #E6EEF3 !important;
        }

        button[data-baseweb="tab"] {
            color: #AABBC8 !important;
            font-weight: 620 !important;
            padding: 0.65rem 0.95rem !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--accent-light) !important;
            border-bottom-color: var(--accent) !important;
        }

        [data-testid="stForm"] {
            background: linear-gradient(
                145deg,
                rgba(28,45,63,0.74),
                rgba(18,32,47,0.78)
            ) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            padding: 1.35rem !important;
            box-shadow: 0 10px 28px rgba(0,0,0,0.13);
        }

        [data-testid="stExpander"] {
            background: rgba(25,41,58,0.72) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 13px !important;
            overflow: hidden;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid var(--glass-border) !important;
            border-radius: 12px !important;
            overflow: hidden;
        }

        [data-testid="stAlert"] {
            border-radius: 11px !important;
            border: 1px solid var(--glass-border) !important;
            backdrop-filter: blur(10px);
        }

        a {
            color: var(--accent-light) !important;
        }

        hr {
            border-color: rgba(148,170,190,0.17) !important;
        }

        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: rgba(10,18,29,0.45);
        }

        ::-webkit-scrollbar-thumb {
            background: rgba(117,145,163,0.38);
            border-radius: 20px;
        }

        @media (max-width: 768px) {
            .block-container {
                padding-top: 1.25rem;
                padding-left: 1rem;
                padding-right: 1rem;
            }

            h1 {
                font-size: 1.9rem !important;
            }

            [data-testid="stMetric"] {
                padding: 14px !important;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.5rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
