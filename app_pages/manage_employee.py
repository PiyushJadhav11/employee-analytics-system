
from datetime import date
from textwrap import dedent

import streamlit as st

from app_pages.common import (
    department_picker,
    employee_picker,
    get,
    request_key,
    role_picker,
    run,
    show_write_result,
)


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("Employee Lifecycle Management")

st.caption(
    "Manage employee transfers, promotions, salary revisions "
    "and historical employment records."
)

st.markdown(
    dedent(
        """
        <div style="
            background:linear-gradient(110deg,#1D3540 0%,#1D2A35 100%);
            border:1px solid #34504F;
            border-left:4px solid #63CBB5;
            border-radius:12px;
            padding:20px 23px;
            margin:10px 0 24px 0;
        ">
            <div style="
                color:#63CBB5;
                font-size:11px;
                font-weight:700;
                letter-spacing:1.4px;
                margin-bottom:8px;
            ">
                SLOWLY CHANGING DIMENSION · TYPE 2
            </div>
            <div style="
                color:#F0F4F7;
                font-size:20px;
                font-weight:700;
                margin-bottom:7px;
            ">
                Employee lifecycle and historical tracking
            </div>
            <div style="
                color:#B8C7D1;
                font-size:13px;
                line-height:1.6;
            ">
                Manage workforce changes while preserving employee history.
                Each qualifying change closes the previous warehouse version
                and creates a new historical record.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Employee selection
# ---------------------------------------------------------------------

st.subheader("Find an employee")

st.caption(
    "Search by employee number, employee name or email address."
)

emp = employee_picker(key="mgr")

if not emp:
    st.info(
        "Select an employee to view their profile and manage employment changes."
    )
    st.stop()

emp_id = int(emp["employee_id"])

current = run(
    lambda: get("employee").get(emp_id)
)

if not current:
    st.stop()


# ---------------------------------------------------------------------
# Current employee profile
# ---------------------------------------------------------------------

st.divider()

st.subheader("Current employee profile")

st.markdown(
    dedent(
        f"""
        <div style="
            background:#1D2A35;
            border:1px solid #354656;
            border-radius:11px;
            padding:17px 20px;
            margin:8px 0 16px 0;
        ">
            <div style="
                color:#F0F4F7;
                font-size:19px;
                font-weight:700;
            ">
                {current['first_name']} {current['last_name']}
            </div>
            <div style="
                color:#9AAEBD;
                font-size:12px;
                margin-top:5px;
            ">
                EMPLOYEE NUMBER · {current['employee_number']}
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "Department",
    current["department_name"],
)

m2.metric(
    "Current role",
    current["job_role"],
)

m3.metric(
    "Job level",
    current["job_level"],
)

m4.metric(
    "Monthly income",
    f"{float(current['monthly_income']):,.0f}",
)


# ---------------------------------------------------------------------
# Employee management tabs
# ---------------------------------------------------------------------

tab_change, tab_history, tab_exit = st.tabs(
    [
        "Position Changes",
        "Version History",
        "Employee Exit",
    ]
)


# =====================================================================
# 1. CHANGE POSITION
# =====================================================================

with tab_change:

    st.subheader("Update employee position")

    st.caption(
        "Record a department transfer, promotion or salary revision."
    )

    reason_label = st.radio(
        "Type of change",
        [
            "Department transfer",
            "Promotion",
            "Salary revision",
        ],
        horizontal=True,
    )

    reason = {
        "Department transfer": "DEPARTMENT_TRANSFER",
        "Promotion": "PROMOTION",
        "Salary revision": "SALARY_REVISION",
    }[reason_label]

    if reason == "DEPARTMENT_TRANSFER":
        st.info(
            "Update the employee's department and organizational assignment."
        )

    elif reason == "PROMOTION":
        st.info(
            "Update the employee's role, job level and compensation as part "
            "of the promotion."
        )

    else:
        st.info(
            "Revise the employee's monthly income while retaining their "
            "employment history."
        )

    st.markdown("#### New organizational assignment")

    dept_col, role_col = st.columns(2)

    with dept_col:
        new_dept = department_picker(
            "New department",
            key="chg_dept",
            default_id=int(current["department_id"]),
        )

    with role_col:
        new_role = role_picker(
            "New role",
            new_dept,
            key="chg_role",
            default_id=int(current["job_role_id"]),
        )

    st.divider()

    st.markdown("#### Updated employment details")

    level_col, income_col, date_col = st.columns(3)

    default_level = min(
        int(current["job_level"]) + (
            1 if reason == "PROMOTION" else 0
        ),
        5,
    )

    with level_col:
        new_level = st.slider(
            "Job level",
            min_value=1,
            max_value=5,
            value=default_level,
        )

    bump = (
        1.15 if reason == "PROMOTION"
        else 1.08 if reason == "SALARY_REVISION"
        else 1.0
    )

    with income_col:
        new_income = st.number_input(
            "Monthly income",
            min_value=1000.0,
            max_value=100000.0,
            value=round(
                float(current["monthly_income"]) * bump,
                0,
            ),
            step=100.0,
        )

    with date_col:
        eff = st.date_input(
            "Effective date",
            value=date.today(),
        )

    st.divider()

    st.caption(
        "Review the updated details before applying the employee change."
    )

    if st.button(
        "Apply employee change",
        type="primary",
        use_container_width=True,
    ):

        # Include current employee state in the idempotency key.
        key = request_key(
            "change_position",
            {
                "emp": emp_id,
                "dept": new_dept,
                "role": new_role,
                "level": new_level,
                "income": new_income,
                "eff": eff,
                "reason": reason,
                "from": (
                    current["department_id"],
                    current["job_role_id"],
                    current["job_level"],
                    str(current["monthly_income"]),
                ),
            },
        )

        result = run(
            lambda: get("employee").change_position(
                emp_id,
                new_dept,
                new_role,
                eff,
                reason=reason,
                job_level=new_level,
                monthly_income=new_income,
                request_key=key,
            )
        )

        if result:
            show_write_result(result)
            st.cache_data.clear()


# =====================================================================
# 2. VERSION HISTORY
# =====================================================================

with tab_history:

    st.subheader("Employee version history")

    st.caption(
        "Review the employee's operational history, warehouse versions "
        "and performance review records."
    )

    # -------------------------------------------------------------
    # OLTP history
    # -------------------------------------------------------------

    st.markdown("#### 01 · Operational database history")

    st.caption(
        "The operational database maintains the employee's employment history."
    )

    oltp = run(
        lambda: get("employee").oltp_history(emp_id)
    )

    if oltp is not None:
        st.dataframe(
            oltp,
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    # -------------------------------------------------------------
    # Data warehouse history
    # -------------------------------------------------------------

    st.markdown("#### 02 · Data warehouse dimension versions")

    st.caption(
        "Each historical version has its own surrogate key, validity dates "
        "and current-version indicator."
    )

    dw = run(
        lambda: get("employee").dw_versions(emp_id)
    )

    if dw is not None and not dw.empty:

        st.dataframe(
            dw,
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            "is_current identifies the currently active dimension version. "
            "Previous versions remain available for historical analysis."
        )

    elif dw is not None:
        st.info(
            "No warehouse dimension versions were found for this employee."
        )

    st.divider()

    # -------------------------------------------------------------
    # Performance review history
    # -------------------------------------------------------------

    st.markdown("#### 03 · Performance review history")

    st.caption(
        "Review records retain the employee dimension version "
        "associated with the review date."
    )

    reviews = run(
        lambda: get("review").for_employee(emp_id)
    )

    if reviews is not None:
        st.dataframe(
            reviews,
            hide_index=True,
            use_container_width=True,
        )


# =====================================================================
# 3. RECORD EMPLOYEE EXIT
# =====================================================================

with tab_exit:

    st.subheader("Record employee exit")

    st.caption(
        "Record the employee's last working day and update their "
        "attrition status."
    )

    st.warning(
        "Recording an employee exit is a permanent operational change. "
        "Verify the selected employee and date before proceeding."
    )

    st.markdown("#### Selected employee")

    st.markdown(
        f"**{current['first_name']} {current['last_name']}**  \n"
        f"Employee number: {current['employee_number']}"
    )

    leave = st.date_input(
        "Last working day",
        value=date.today(),
        key="exit_date",
    )

    st.divider()

    if st.button(
        "Record employee exit",
        type="primary",
        use_container_width=True,
    ):

        result = run(
            lambda: get("employee").terminate(
                emp_id,
                leave,
                request_key=request_key(
                    "terminate",
                    {
                        "emp": emp_id,
                        "date": leave,
                    },
                ),
            )
        )

        show_write_result(result)
