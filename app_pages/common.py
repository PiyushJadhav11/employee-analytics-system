"""Shared helpers for the Streamlit pages: cached managers, cached lookups, error display."""
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
    AnalyticsManager, EmployeeManager, EtlManager, LookupManager, ManagerError,
    ProjectManager, ReconciliationManager, ReviewManager,
)
from hr_analytics.models import ValidationError  # noqa: E402

PLOTLY_TEMPLATE = "plotly_white"
DEPT_COLORS = {
    "Research & Development": "#2a6fdb",
    "Sales": "#e8833a",
    "Human Resources": "#3aa876",
    "All departments": "#444444",
}


@st.cache_resource(show_spinner=False)
def managers() -> dict[str, Any]:
    """One instance of each manager per server process (they are singletons anyway;
    caching keeps Streamlit from re-running __init__ on every rerun)."""
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
        st.info("Check the connection settings in `.env` (local) or `.streamlit/secrets.toml` / app secrets (cloud).")
        st.stop()


def run(action: Callable[[], Any], success: str | None = None) -> Any:
    """Call a manager method and show validation/database errors instead of a traceback."""
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


@st.cache_data(ttl=600, show_spinner=False)
def departments() -> pd.DataFrame:
    return get("lookup").departments()


@st.cache_data(ttl=600, show_spinner=False)
def roles() -> pd.DataFrame:
    return get("lookup").roles()


def department_picker(label: str, key: str, default_id: int | None = None) -> int:
    d = departments()
    ids = d["department_id"].tolist()
    idx = ids.index(default_id) if default_id in ids else 0
    return st.selectbox(label, ids, index=idx, key=key,
                        format_func=lambda i: d.set_index("department_id").loc[i, "department_name"])


def role_picker(label: str, department_id: int, key: str, default_id: int | None = None) -> int:
    r = roles()
    r = r[r["department_id"] == department_id]
    ids = r["job_role_id"].tolist()
    idx = ids.index(default_id) if default_id in ids else 0
    return st.selectbox(label, ids, index=idx, key=key,
                        format_func=lambda i: r.set_index("job_role_id").loc[i, "role_name"])


def employee_picker(label: str = "Find employee (number, name or email)", key: str = "emp",
                    active_only: bool = True) -> dict | None:
    term = st.text_input(label, key=f"{key}_term", placeholder="e.g. 100042 or priya")
    if not term:
        return None
    found = run(lambda: get("lookup").search_employees(term, active_only=active_only, limit=25))
    if found is None or found.empty:
        st.info("No matching employees.")
        return None
    labels = {int(r.employee_id): f"#{r.employee_number} · {r.full_name} · {r.department_name} · {r.job_role}"
              for r in found.itertuples()}
    chosen = st.selectbox("Select", list(labels), format_func=labels.get, key=f"{key}_select")
    return found.set_index("employee_id").loc[chosen].to_dict() | {"employee_id": chosen}


def request_key(operation: str, payload: dict) -> str:
    """Idempotency key for a form submission.

    Derived from this browser session + the operation + exactly what was submitted.
    A double-click, a re-run or a refresh that re-submits the same form produces the
    same key, so the manager returns the first result instead of writing again. A
    genuinely different submission (any field changed) gets a new key. Including
    the current state (e.g. the employee's current history version) in the payload
    lets the same values be submitted again once the state has moved on.
    """
    nonce = st.session_state.setdefault("_session_nonce", str(uuid.uuid4()))
    body = json.dumps(payload, sort_keys=True, default=str)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{nonce}|{operation}|{body}"))


def show_write_result(result) -> None:
    """Success message, plus a note when nothing new was written or the DW sync failed."""
    if result is None:
        return
    if result.replayed:
        st.info(f"Already done — {result.message} (duplicate submission ignored, nothing written twice)")
    else:
        st.success(result.message)
    dw_sync_note(result)


def dw_sync_note(result) -> None:
    if result is not None and not result.dw_synced:
        st.warning("Saved to OLTP, but the warehouse sync failed. Run the ETL from **ETL & Data Ops** to catch up.")
