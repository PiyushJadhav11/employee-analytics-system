from datetime import date

import streamlit as st

from app_pages.common import department_picker, get, request_key, role_picker, run, show_write_result
from hr_analytics.models import Employee, ValidationError

st.title("Onboard a new employee")
st.caption("Writes to hr_oltp.employees, employee_engagement and employee_history (version 1, reason HIRE), "
           "then loads the employee into hr_dw.dim_employee.")

# Department and role sit outside the form so the role list follows the department.
c1, c2 = st.columns(2)
with c1:
    dept_id = department_picker("Department", key="on_dept")
with c2:
    role_id = role_picker("Job role", dept_id, key="on_role")

with st.form("onboard", clear_on_submit=False):
    a, b, c = st.columns(3)
    first = a.text_input("First name")
    last = b.text_input("Last name")
    email = c.text_input("Work email", placeholder="name@greenfield-corp.com")

    a, b, c = st.columns(3)
    gender = a.selectbox("Gender", Employee.GENDERS)
    dob = b.date_input("Date of birth", value=date(1995, 1, 1), min_value=date(1950, 1, 1), max_value=date.today())
    hire = c.date_input("Hire date", value=date.today(), max_value=date.today())

    a, b, c = st.columns(3)
    level = a.slider("Job level", 1, 5, 1)
    income = b.number_input("Monthly income", min_value=1000.0, max_value=50000.0, value=4000.0, step=100.0)
    marital = c.selectbox("Marital status", Employee.MARITAL)

    a, b, c = st.columns(3)
    education = a.selectbox("Education (1 Below College – 5 Doctor)", [1, 2, 3, 4, 5], index=2)
    field = b.selectbox("Education field", ["Life Sciences", "Medical", "Marketing", "Technical Degree",
                                            "Human Resources", "Other"])
    city = c.text_input("City")

    a, b, c = st.columns(3)
    travel = a.selectbox("Business travel", Employee.TRAVEL, index=1)
    overtime = b.checkbox("Works overtime")
    distance = c.number_input("Distance from home (km)", 0, 200, 5)

    st.markdown("**Engagement survey** (1 = low, 4 = high)")
    s = st.columns(5)
    engagement = {
        "environment_satisfaction": s[0].select_slider("Environment", [1, 2, 3, 4], 3),
        "job_satisfaction": s[1].select_slider("Job", [1, 2, 3, 4], 3),
        "relationship_satisfaction": s[2].select_slider("Relationships", [1, 2, 3, 4], 3),
        "work_life_balance": s[3].select_slider("Work-life balance", [1, 2, 3, 4], 3),
        "job_involvement": s[4].select_slider("Involvement", [1, 2, 3, 4], 3),
    }
    submitted = st.form_submit_button("Onboard employee", type="primary")

if submitted:
    try:
        emp = Employee(first_name=first, last_name=last, email=email, gender=gender, date_of_birth=dob,
                       hire_date=hire, department_id=dept_id, job_role_id=role_id, job_level=level,
                       monthly_income=income, marital_status=marital, education=education,
                       education_field=field, city=city or None, business_travel=travel,
                       overtime=overtime, distance_from_home=int(distance))
    except ValidationError as exc:
        st.warning(str(exc))
    else:
        key = request_key("onboard", emp.to_record() | engagement)
        result = run(lambda: get("employee").onboard(emp, engagement, request_key=key))
        if result:
            show_write_result(result)
            st.markdown("**Warehouse row created (dim_employee):**")
            st.dataframe(run(lambda: get("employee").dw_versions(result.id)), hide_index=True)
