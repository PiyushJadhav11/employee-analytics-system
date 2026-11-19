import streamlit as st
from app_pages.common import current_principal, require_permission, auth_manager

principal = current_principal()
require_permission("employee.view_self")
require_permission("review.view_self")
st.title("My profile")
if principal.employee_id is None:
    st.warning("Your account is not linked to an employee record. Contact HR.")
    st.stop()
auth = auth_manager()
profile = auth.fetch_one("""SELECT e.employee_number, e.first_name, e.last_name, e.email, e.hire_date,
    e.termination_date, d.department_name, j.role_name, e.job_level, e.monthly_income
    FROM hr_oltp.employees e JOIN hr_oltp.departments d USING(department_id)
    JOIN hr_oltp.job_roles j USING(job_role_id) WHERE e.employee_id=%s""", (principal.employee_id,))
if profile:
    c = st.columns(3)
    c[0].metric("Employee number", profile["employee_number"])
    c[1].metric("Department", profile["department_name"])
    c[2].metric("Job role", profile["role_name"])
    st.dataframe([profile], hide_index=True, use_container_width=True)
    st.subheader("My projects")
    st.dataframe(auth.fetch_df("""SELECT p.project_code,p.project_name,a.role_on_project,a.allocation_pct,a.start_date,a.end_date
        FROM hr_oltp.assignments a JOIN hr_oltp.projects p USING(project_id)
        WHERE a.employee_id=%s ORDER BY a.start_date DESC""", (principal.employee_id,)), hide_index=True)
    st.subheader("My reviews")
    st.dataframe(auth.fetch_df("""SELECT review_date,review_year,performance_score,rating,goals_met_pct,comments
        FROM hr_oltp.reviews WHERE employee_id=%s ORDER BY review_date DESC""", (principal.employee_id,)), hide_index=True)
