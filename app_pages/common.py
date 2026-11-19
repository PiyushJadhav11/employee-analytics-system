
"""Shared helpers and visual theme for the Streamlit application."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hr_analytics.db_manager import DatabaseError  # noqa: E402
from hr_analytics.managers import (  # noqa: E402
    AnalyticsManager,
    EmployeeManager,
    EtlManager,
    LookupManager,
    ManagerError,
    ProjectManager,
    ReconciliationManager,
    ReviewManager,
)
from hr_analytics.models import ValidationError  # noqa: E402


# ---------------------------------------------------------------------
# Shared chart palette
# ---------------------------------------------------------------------

PLOTLY_TEMPLATE = "plotly_dark"

COLORS = {
    "background": "#0B1220",
    "background_alt": "#111C2C",
    "surface": "rgba(24, 39, 57, 0.76)",
    "surface_hover": "rgba(35, 54, 74, 0.88)",
    "border": "rgba(148, 170, 190, 0.17)",
    "border_active": "rgba(99, 203, 181, 0.55)",
    "text": "#EDF4F8",
    "muted": "#9AABBA",
    "teal": "#63CBB5",
    "teal_light": "#8AE2D0",
    "blue": "#829ED0",
    "amber": "#D9B477",
    "red": "#E58C91",
}

DEPT_COLORS = {
    "Research & Development": COLORS["teal"],
    "Sales": COLORS["amber"],
    "Human Resources": COLORS["blue"],
    "All departments": "#AAB7C4",
}


# ---------------------------------------------------------------------
# Shared application styling
# ---------------------------------------------------------------------

def apply_theme() -> None:
    """Apply the shared glass-inspired enterprise application theme."""

    st.markdown(
        """
        <style>
        /* =========================================================
           GLOBAL FOUNDATION
        ========================================================= */

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
                radial-gradient(
                    ellipse at 8% 5%,
                    rgba(50, 112, 116, 0.17),
                    transparent 34%
                ),
                radial-gradient(
                    ellipse at 92% 16%,
                    rgba(77, 103, 153, 0.14),
                    transparent 32%
                ),
                linear-gradient(
                    145deg,
                    #0B1220 0%,
                    #101C2B 52%,
                    #0B1421 100%
                );
            color: var(--text-primary);
        }

        [data-testid="stAppViewContainer"] {
            background: transparent;
        }

        [data-testid="stHeader"] {
            background: rgba(11, 18, 32, 0.60);
            backdrop-filter: blur(14px);
        }

        .block-container {
            max-width: 1500px;
            padding-top: 2.2rem;
            padding-bottom: 3.5rem;
        }

        /* =========================================================
           TYPOGRAPHY
        ========================================================= */

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
            background: rgba(99, 203, 181, 0.09) !important;
            border-radius: 5px;
        }

        /* =========================================================
           GLASS SIDEBAR
        ========================================================= */

        [data-testid="stSidebar"] {
            background:
                linear-gradient(
                    180deg,
                    rgba(21, 34, 49, 0.97),
                    rgba(13, 24, 38, 0.98)
                ) !important;
            border-right: 1px solid var(--glass-border);
            box-shadow: 10px 0 40px rgba(0, 0, 0, 0.16);
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

        /* Sidebar section labels */
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
            color: #8FA3B3 !important;
        }

        /* Streamlit navigation links */
        [data-testid="stSidebarNavLink"] {
            position: relative;
            border-radius: 11px !important;
            padding: 0.58rem 0.72rem !important;
            margin: 3px 0 !important;
            border: 1px solid transparent !important;
            color: #C7D4DE !important;
            transition:
                background 180ms ease,
                border-color 180ms ease,
                transform 180ms ease,
                box-shadow 180ms ease;
        }

        [data-testid="stSidebarNavLink"]:hover {
            background: rgba(99, 203, 181, 0.09) !important;
            border-color: rgba(99, 203, 181, 0.20) !important;
            color: #F2FAF8 !important;
            transform: translateX(2px);
        }

        [data-testid="stSidebarNavLink"][aria-current="page"] {
            background:
                linear-gradient(
                    105deg,
                    rgba(99, 203, 181, 0.19),
                    rgba(99, 203, 181, 0.06)
                ) !important;
            border: 1px solid rgba(99, 203, 181, 0.34) !important;
            color: #A3EBDD !important;
            box-shadow: 0 4px 18px rgba(35, 133, 116, 0.10);
        }

        /* Circular accent indicator for sidebar navigation */
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
            box-shadow: 0 0 0 3px rgba(148, 170, 190, 0.08);
            transition: all 180ms ease;
        }

        [data-testid="stSidebarNavLink"]:hover::before {
            background: var(--accent-light);
            box-shadow: 0 0 0 4px rgba(99, 203, 181, 0.13);
        }

        [data-testid="stSidebarNavLink"][aria-current="page"]::before {
            width: 8px;
            height: 8px;
            background: var(--accent);
            box-shadow:
                0 0 0 4px rgba(99, 203, 181, 0.15),
                0 0 12px rgba(99, 203, 181, 0.55);
        }

        /* =========================================================
           GLASS METRIC CARDS
        ========================================================= */

        [data-testid="stMetric"] {
            position: relative;
            overflow: hidden;
            background:
                linear-gradient(
                    145deg,
                    rgba(37, 57, 76, 0.82),
                    rgba(23, 39, 56, 0.78)
                ) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            padding: 19px 20px !important;
            box-shadow:
                0 9px 26px rgba(0, 0, 0, 0.16),
                inset 0 1px 0 rgba(255, 255, 255, 0.035);
            backdrop-filter: blur(15px);
            transition:
                transform 180ms ease,
                border-color 180ms ease,
                box-shadow 180ms ease;
        }

        [data-testid="stMetric"]:hover {
            transform: translateY(-3px);
            border-color: var(--glass-border-hover) !important;
            box-shadow:
                0 13px 30px rgba(0, 0, 0, 0.22),
                0 0 20px rgba(99, 203, 181, 0.055);
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

        [data-testid="stMetricDelta"] {
            font-weight: 600 !important;
        }

        /* =========================================================
           CONTAINERS AND GLASS PANELS
        ========================================================= */

        [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            background:
                linear-gradient(
                    145deg,
                    rgba(29, 46, 65, 0.70),
                    rgba(19, 33, 49, 0.72)
                ) !important;
            box-shadow:
                0 10px 30px rgba(0, 0, 0, 0.12),
                inset 0 1px 0 rgba(255, 255, 255, 0.025);
            backdrop-filter: blur(14px);
        }

        /* =========================================================
           BUTTONS
        ========================================================= */

        .stButton > button,
        .stFormSubmitButton > button,
        [data-testid="stDownloadButton"] > button {
            min-height: 2.65rem;
            border-radius: 10px !important;
            font-weight: 650 !important;
            border: 1px solid rgba(148, 170, 190, 0.24);
            transition: all 180ms ease;
        }

        .stButton > button:hover,
        .stFormSubmitButton > button:hover,
        [data-testid="stDownloadButton"] > button:hover {
            border-color: var(--accent) !important;
            transform: translateY(-1px);
            box-shadow: 0 6px 18px rgba(0, 0, 0, 0.17);
        }

        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background:
                linear-gradient(110deg, #63CBB5, #72D4C0) !important;
            color: #10231F !important;
            border: 1px solid #72D4C0 !important;
            font-weight: 720 !important;
            box-shadow: 0 5px 17px rgba(65, 184, 158, 0.16);
        }

        .stButton > button[kind="primary"]:hover,
        .stFormSubmitButton > button[kind="primary"]:hover {
            background:
                linear-gradient(110deg, #7ADAC5, #91E6D3) !important;
            color: #10231F !important;
            box-shadow: 0 8px 22px rgba(65, 184, 158, 0.24);
        }

        /* =========================================================
           INPUTS AND SELECTORS
        ========================================================= */

        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"] > div {
            background: rgba(28, 44, 61, 0.86) !important;
            border: 1px solid rgba(148, 170, 190, 0.23) !important;
            border-radius: 10px !important;
            transition: border-color 160ms ease, box-shadow 160ms ease;
        }

        div[data-baseweb="input"] > div:focus-within,
        div[data-baseweb="select"] > div:focus-within,
        div[data-baseweb="textarea"] > div:focus-within {
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px rgba(99, 203, 181, 0.12) !important;
        }

        input, textarea {
            color: var(--text-primary) !important;
        }

        [data-baseweb="select"] span {
            color: #E6EEF3 !important;
        }

        /* =========================================================
           TABS
        ========================================================= */

        button[data-baseweb="tab"] {
            color: #AABBC8 !important;
            font-weight: 620 !important;
            padding: 0.65rem 0.95rem !important;
            transition: color 150ms ease;
        }

        button[data-baseweb="tab"]:hover {
            color: var(--accent-light) !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--accent-light) !important;
            border-bottom-color: var(--accent) !important;
        }

        [data-baseweb="tab-highlight"] {
            background-color: var(--accent) !important;
        }

        /* =========================================================
           FORMS
        ========================================================= */

        [data-testid="stForm"] {
            background:
                linear-gradient(
                    145deg,
                    rgba(28, 45, 63, 0.74),
                    rgba(18, 32, 47, 0.78)
                ) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 16px !important;
            padding: 1.35rem !important;
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.13);
            backdrop-filter: blur(12px);
        }

        /* =========================================================
           EXPANDERS
        ========================================================= */

        [data-testid="stExpander"] {
            background: rgba(25, 41, 58, 0.72) !important;
            border: 1px solid var(--glass-border) !important;
            border-radius: 13px !important;
            overflow: hidden;
        }

        [data-testid="stExpander"] summary {
            color: #DCE7ED !important;
            font-weight: 600;
        }

        [data-testid="stExpander"] summary:hover {
            color: var(--accent-light) !important;
        }

        /* =========================================================
           DATAFRAMES AND TABLES
        ========================================================= */

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid var(--glass-border) !important;
            border-radius: 12px !important;
            overflow: hidden;
        }

        /* =========================================================
           ALERTS AND STATUS MESSAGES
        ========================================================= */

        [data-testid="stAlert"] {
            border-radius: 11px !important;
            border: 1px solid var(--glass-border) !important;
            backdrop-filter: blur(10px);
        }

        /* =========================================================
           CHECKBOXES AND RADIO CONTROLS
        ========================================================= */

        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label {
            color: #D5E0E8 !important;
        }

        /* =========================================================
           LINKS, DIVIDERS AND SCROLLBARS
        ========================================================= */

        a {
            color: var(--accent-light) !important;
        }

        hr {
            border-color: rgba(148, 170, 190, 0.17) !important;
        }

        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: rgba(10, 18, 29, 0.45);
        }

        ::-webkit-scrollbar-thumb {
            background: rgba(117, 145, 163, 0.38);
            border-radius: 20px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: rgba(99, 203, 181, 0.58);
        }

        /* =========================================================
           RESPONSIVE ADJUSTMENTS
        ========================================================= */

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


# ---------------------------------------------------------------------
# Cached database managers
# ---------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def managers() -> dict[str, Any]:
    """Create one instance of each manager per server process."""
    return {
        "lookup": LookupManager(),
        "employee": EmployeeManager(),
        "project": ProjectManager(),
        "review": ReviewManager(),
        "analytics": AnalyticsManager(),
        "etl": EtlManager(),
        "recon": ReconciliationManager(),
    }


def get(name: str) -> Any:
    try:
        return managers()[name]
    except DatabaseError as exc:
        st.error(f"**Database unavailable.** {exc}")
        st.info(
            "Check the connection settings in `.env` (local) or "
            "`.streamlit/secrets.toml` / app secrets (cloud)."
        )
        st.stop()


# ---------------------------------------------------------------------
# Shared error handling
# ---------------------------------------------------------------------

def run(action: Callable[[], Any], success: str | None = None) -> Any:
    """Run a manager operation and display expected errors cleanly."""
    try:
        result = action()
    except ValidationError as exc:
        st.warning(str(exc))
        return None
    except ManagerError as exc:
        st.error(str(exc))
        return None

    if success:
        st.success(success)

    return result


# ---------------------------------------------------------------------
# Cached lookup data
# ---------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def departments() -> pd.DataFrame:
    return get("lookup").departments()


@st.cache_data(ttl=600, show_spinner=False)
def roles() -> pd.DataFrame:
    return get("lookup").roles()


# ---------------------------------------------------------------------
# Department and role selectors
# ---------------------------------------------------------------------

def department_picker(
    label: str,
    key: str,
    default_id: int | None = None,
) -> int:
    d = departments()
    ids = d["department_id"].tolist()
    idx = ids.index(default_id) if default_id in ids else 0

    names = d.set_index("department_id")["department_name"]

    return st.selectbox(
        label,
        ids,
        index=idx,
        key=key,
        format_func=lambda i: names.loc[i],
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

    names = r.set_index("job_role_id")["role_name"]

    return st.selectbox(
        label,
        ids,
        index=idx,
        key=key,
        format_func=lambda i: names.loc[i],
    )


# ---------------------------------------------------------------------
# Employee search selector
# ---------------------------------------------------------------------

def employee_picker(
    label: str = "Find employee (number, name or email)",
    key: str = "emp",
    active_only: bool = True,
) -> dict | None:

    term = st.text_input(
        label,
        key=f"{key}_term",
        placeholder="e.g. 100042 or Priya",
    )

    if not term:
        return None

    found = run(
        lambda: get("lookup").search_employees(
            term,
            active_only=active_only,
            limit=25,
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
        "Select employee",
        list(labels),
        format_func=labels.get,
        key=f"{key}_select",
    )

    return (
        found.set_index("employee_id")
        .loc[chosen]
        .to_dict()
        | {"employee_id": chosen}
    )


# ---------------------------------------------------------------------
# Idempotency key generation
# ---------------------------------------------------------------------

def request_key(operation: str, payload: dict) -> str:
    """Generate a stable key for duplicate-submission protection."""

    nonce = st.session_state.setdefault(
        "_session_nonce",
        str(uuid.uuid4()),
    )

    body = json.dumps(
        payload,
        sort_keys=True,
        default=str,
    )

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{nonce}|{operation}|{body}",
        )
    )


# ---------------------------------------------------------------------
# Write result messages
# ---------------------------------------------------------------------

def show_write_result(result) -> None:
    """Display write results and warehouse synchronization status."""

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
