
from datetime import date
from textwrap import dedent

import streamlit as st

from app_pages.common import (
    department_picker,
    get,
    request_key,
    role_picker,
    run,
    show_write_result,
)
from hr_analytics.models import Employee, ValidationError


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("Employee Onboarding")

st.caption(
    "Create an employee profile and register the initial employee "
    "record in the operational database."
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
            margin:10px 0 25px 0;
        ">
            <div style="
                color:#63CBB5;
                font-size:11px;
                font-weight:700;
                letter-spacing:1.4px;
                margin-bottom:8px;
            ">
                EMPLOYEE LIFECYCLE MANAGEMENT
            </div>
            <div style="
                color:#F0F4F7;
                font-size:21px;
                font-weight:700;
                margin-bottom:7px;
            ">
                Create a new employee profile
            </div>
            <div style="
                color:#B8C7D1;
                font-size:13px;
                line-height:1.6;
            ">
                Enter the employee's information, assign an initial
                department and job role, and record their engagement
                ratings. The system will create the employee record
                and its initial historical version.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Organizational assignment
# ---------------------------------------------------------------------

st.subheader("Organizational assignment")

st.caption(
    "Choose the department first. The available job roles will depend "
    "on the selected department."
)

with st.container(border=True):
    dept_col, role_col = st.columns(2)

    with dept_col:
        dept_id = department_picker(
            "Department",
            key="on_dept",
        )

    with role_col:
        role_id = role_picker(
            "Job role",
            dept_id,
            key="on_role",
        )


# ---------------------------------------------------------------------
# Employee onboarding form
# ---------------------------------------------------------------------

st.subheader("Employee information")

st.caption(
    "Complete the sections below. Fields and their existing validation "
    "rules are retained."
)

with st.form("onboard", clear_on_submit=False):

    # -----------------------------------------------------------------
    # Section 1: Personal information
    # -----------------------------------------------------------------

    st.markdown("#### 01  Personal information")

    st.caption("Basic information used to identify the employee.")

    first_col, last_col, email_col = st.columns(3)

    with first_col:
        first = st.text_input(
            "First name",
            placeholder="Enter first name",
        )

    with last_col:
        last = st.text_input(
            "Last name",
            placeholder="Enter last name",
        )

    with email_col:
        email = st.text_input(
            "Work email",
            placeholder="name@company.com",
        )

    gender_col, dob_col, hire_col = st.columns(3)

    with gender_col:
        gender = st.selectbox(
            "Gender",
            Employee.GENDERS,
        )

    with dob_col:
        dob = st.date_input(
            "Date of birth",
            value=date(1995, 1, 1),
            min_value=date(1950, 1, 1),
            max_value=date.today(),
        )

    with hire_col:
        hire = st.date_input(
            "Hire date",
            value=date.today(),
            max_value=date.today(),
        )

    st.divider()

    # -----------------------------------------------------------------
    # Section 2: Employment details
    # -----------------------------------------------------------------

    st.markdown("#### 02  Employment details")

    st.caption(
        "Specify the employee's initial employment and compensation details."
    )

    level_col, income_col, marital_col = st.columns(3)

    with level_col:
        level = st.slider(
            "Job level",
            min_value=1,
            max_value=5,
            value=1,
        )

    with income_col:
        income = st.number_input(
            "Monthly income",
            min_value=1000.0,
            max_value=50000.0,
            value=4000.0,
            step=100.0,
        )

    with marital_col:
        marital = st.selectbox(
            "Marital status",
            Employee.MARITAL,
        )

    travel_col, overtime_col, distance_col = st.columns(3)

    with travel_col:
        travel = st.selectbox(
            "Business travel",
            Employee.TRAVEL,
            index=1,
        )

    with overtime_col:
        st.markdown("##### Work schedule")
        overtime = st.checkbox("Works overtime")

    with distance_col:
        distance = st.number_input(
            "Distance from home (km)",
            min_value=0,
            max_value=200,
            value=5,
        )

    st.divider()

    # -----------------------------------------------------------------
    # Section 3: Education and additional information
    # -----------------------------------------------------------------

    st.markdown("#### 03  Education and additional information")

    st.caption(
        "Provide the employee's education background and location."
    )

    education_col, field_col, city_col = st.columns(3)

    with education_col:
        education = st.selectbox(
            "Education level (1–5)",
            [1, 2, 3, 4, 5],
            index=2,
            help=(
                "1 = Below College, 2 = College, "
                "3 = Bachelor, 4 = Master, 5 = Doctor"
            ),
        )

    with field_col:
        field = st.selectbox(
            "Education field",
            [
                "Life Sciences",
                "Medical",
                "Marketing",
                "Technical Degree",
                "Human Resources",
                "Other",
            ],
        )

    with city_col:
        city = st.text_input(
            "City",
            placeholder="Enter city",
        )

    st.divider()

    # -----------------------------------------------------------------
    # Section 4: Engagement survey
    # -----------------------------------------------------------------

    st.markdown("#### 04  Employee engagement survey")

    st.caption(
        "Record initial employee satisfaction and involvement ratings. "
        "A rating of 1 indicates low satisfaction and 4 indicates high satisfaction."
    )

    survey_cols = st.columns(5)

    engagement = {
        "environment_satisfaction": survey_cols[0].select_slider(
            "Environment",
            options=[1, 2, 3, 4],
            value=3,
        ),
        "job_satisfaction": survey_cols[1].select_slider(
            "Job",
            options=[1, 2, 3, 4],
            value=3,
        ),
        "relationship_satisfaction": survey_cols[2].select_slider(
            "Relationships",
            options=[1, 2, 3, 4],
            value=3,
        ),
        "work_life_balance": survey_cols[3].select_slider(
            "Work-life balance",
            options=[1, 2, 3, 4],
            value=3,
        ),
        "job_involvement": survey_cols[4].select_slider(
            "Involvement",
            options=[1, 2, 3, 4],
            value=3,
        ),
    }

    st.divider()

    submitted = st.form_submit_button(
        "Create employee profile",
        type="primary",
        use_container_width=True,
    )


# ---------------------------------------------------------------------
# Form submission and validation
# ---------------------------------------------------------------------

if submitted:

    try:
        emp = Employee(
            first_name=first,
            last_name=last,
            email=email,
            gender=gender,
            date_of_birth=dob,
            hire_date=hire,
            department_id=dept_id,
            job_role_id=role_id,
            job_level=level,
            monthly_income=income,
            marital_status=marital,
            education=education,
            education_field=field,
            city=city or None,
            business_travel=travel,
            overtime=overtime,
            distance_from_home=int(distance),
        )

    except ValidationError as exc:
        st.warning(str(exc))

    else:
        key = request_key(
            "onboard",
            emp.to_record() | engagement,
        )

        result = run(
            lambda: get("employee").onboard(
                emp,
                engagement,
                request_key=key,
            )
        )

        if result:
            show_write_result(result)

            st.divider()

            st.subheader("Warehouse record")

            st.caption(
                "Initial employee version stored in hr_dw.dim_employee."
            )

            dw = run(
                lambda: get("employee").dw_versions(result.id)
            )

            if dw is not None:
                st.dataframe(
                    dw,
                    hide_index=True,
                    use_container_width=True,
                )
