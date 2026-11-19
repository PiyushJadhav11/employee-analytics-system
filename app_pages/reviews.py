
from datetime import date

import streamlit as st

from app_pages.common import (
    employee_picker,
    get,
    request_key,
    run,
    show_write_result,
)
from hr_analytics.models import Review, ValidationError


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("Performance Management")

st.caption(
    "Evaluate employee performance, record review outcomes "
    "and maintain historical performance records."
)

st.markdown(
    """
    <div style="
        background:linear-gradient(110deg,#1D3540 0%,#1D2A35 70%,#26313E 100%);
        border:1px solid #34504F;
        border-left:4px solid #D9B477;
        border-radius:11px;
        padding:19px 22px;
        margin:10px 0 24px 0;
    ">
        <div style="
            color:#D9B477;
            font-size:11px;
            font-weight:700;
            letter-spacing:1.2px;
        ">
            EMPLOYEE PERFORMANCE WORKSPACE
        </div>
        <div style="
            color:#F0F4F7;
            font-size:20px;
            font-weight:650;
            margin-top:7px;
        ">
            Measure performance and track employee progress.
        </div>
        <div style="
            color:#B8C7D1;
            font-size:13px;
            line-height:1.6;
            margin-top:6px;
        ">
            Record performance scores, evaluate goal achievement
            and preserve employee review history for workforce analytics.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Employee selection
# ---------------------------------------------------------------------

st.subheader("Select employee")

st.caption(
    "Search using an employee number, name or email address."
)

emp = employee_picker(key="rev")

if not emp:
    st.info(
        "Select an employee to submit a performance review "
        "or view their review history."
    )
    st.stop()


# ---------------------------------------------------------------------
# Selected employee profile
# ---------------------------------------------------------------------

st.divider()

st.subheader("Employee profile")

with st.container(border=True):

    st.markdown(
        f"""
        <div style="
            color:#63CBB5;
            font-size:11px;
            font-weight:700;
            letter-spacing:1px;
        ">
            SELECTED EMPLOYEE
        </div>
        <div style="
            color:#F0F4F7;
            font-size:21px;
            font-weight:650;
            margin-top:7px;
        ">
            {emp['full_name']}
        </div>
        <div style="
            color:#AAB9C6;
            font-size:13px;
            margin-top:4px;
        ">
            Employee #{emp['employee_number']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    c1, c2 = st.columns(2)

    c1.markdown("**Department**")
    c1.write(emp["department_name"])

    c2.markdown("**Job role**")
    c2.write(emp["job_role"])


# ---------------------------------------------------------------------
# Review submission
# ---------------------------------------------------------------------

st.divider()

st.subheader("Submit performance review")

st.caption(
    "Complete the evaluation below to create a new employee review record."
)

with st.container(border=True):

    with st.form("review", clear_on_submit=False):

        st.markdown("### 01 · Review information")

        a, b = st.columns(2)

        review_date = a.date_input(
            "Review date",
            value=date.today(),
            max_value=date.today(),
        )

        score = b.slider(
            "Performance score",
            min_value=1.0,
            max_value=5.0,
            value=3.5,
            step=0.05,
            help="Rate employee performance on a scale of 1 to 5.",
        )

        st.divider()

        st.markdown("### 02 · Performance assessment")

        st.caption(
            "Evaluate how effectively the employee achieved their assigned goals."
        )

        goals = st.slider(
            "Goals met",
            min_value=0,
            max_value=100,
            value=75,
            format="%d%%",
        )

        reviewer = st.number_input(
            "Reviewer employee ID",
            min_value=0,
            value=0,
            step=1,
            help="Enter 0 if no reviewer ID is available.",
        )

        st.divider()

        st.markdown("### 03 · Review comments")

        comments = st.text_area(
            "Performance feedback",
            max_chars=255,
            placeholder=(
                "Enter observations, achievements or areas for improvement..."
            ),
            height=120,
        )

        st.caption(
            "Maximum 255 characters."
        )

        st.divider()

        ok = st.form_submit_button(
            "Submit performance review",
            type="primary",
            use_container_width=True,
        )


# ---------------------------------------------------------------------
# Review submission and validation
# ---------------------------------------------------------------------

if ok:

    try:

        review = Review(
            employee_id=int(emp["employee_id"]),
            review_date=review_date,
            performance_score=score,
            goals_met_pct=goals,
            comments=comments,
            reviewer_id=int(reviewer) or None,
        )

    except ValidationError as exc:

        st.warning(str(exc))

    else:

        key = request_key(
            "submit_review",
            review.to_record(),
        )

        result = run(
            lambda: get("review").submit(
                review,
                request_key=key,
            )
        )

        show_write_result(result)


# ---------------------------------------------------------------------
# Historical review records
# ---------------------------------------------------------------------

st.divider()

st.subheader("Performance review history")

st.caption(
    "Review records previously submitted for the selected employee."
)

history = run(
    lambda: get("review").for_employee(
        int(emp["employee_id"])
    )
)


if history is not None:

    if history.empty:

        st.info(
            "No performance reviews have been recorded for this employee yet."
        )

    else:

        # -------------------------------------------------------------
        # Review summary
        # -------------------------------------------------------------

        st.markdown("### Review overview")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Total reviews",
            f"{len(history):,}",
        )

        if "performance_score" in history.columns:

            avg_score = history["performance_score"].mean()

            c2.metric(
                "Average performance score",
                f"{avg_score:.2f} / 5.00",
            )

        if "goals_met_pct" in history.columns:

            avg_goals = history["goals_met_pct"].mean()

            c3.metric(
                "Average goals achieved",
                f"{avg_goals:.1f}%",
            )

        st.divider()

        # -------------------------------------------------------------
        # Review table
        # -------------------------------------------------------------

        st.markdown("### Review records")

        st.dataframe(
            history,
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            "These records are retrieved from the existing review manager."
        )
