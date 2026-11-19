import streamlit as st
from app_pages.common import current_principal, require_permission, auth_manager

principal = current_principal()
require_permission("analytics.view_department")
st.title("Department dashboard")
if not principal.department_ids:
    st.warning("No department access is assigned to your account. Contact a System Admin.")
    st.stop()
auth = auth_manager()
ids = sorted(principal.department_ids)
marks = ",".join(["%s"] * len(ids))
params = tuple(ids)
headcount = auth.fetch_one(f"SELECT COUNT(*) AS n FROM hr_oltp.employees WHERE termination_date IS NULL AND department_id IN ({marks})", params)["n"]
projects = auth.fetch_one(f"SELECT COUNT(*) AS n FROM hr_oltp.projects WHERE department_id IN ({marks})", params)["n"]
reviews = auth.fetch_one(f"""SELECT COUNT(*) AS n FROM hr_oltp.reviews r
    JOIN hr_oltp.employee_history h ON h.employee_id=r.employee_id
      AND r.review_date BETWEEN h.effective_start AND h.effective_end
    WHERE h.department_id IN ({marks})""", params)["n"]
a,b,c = st.columns(3)
a.metric("Active employees", f"{headcount:,}")
b.metric("Projects", f"{projects:,}")
c.metric("Reviews", f"{reviews:,}")
st.subheader("Employees in your departments")
st.dataframe(auth.fetch_df(f"""SELECT e.employee_number,CONCAT(e.first_name,' ',e.last_name) AS employee,
    d.department_name,j.role_name,e.job_level,e.hire_date FROM hr_oltp.employees e
    JOIN hr_oltp.departments d USING(department_id) JOIN hr_oltp.job_roles j USING(job_role_id)
    WHERE e.department_id IN ({marks}) ORDER BY d.department_name,e.employee_number""", params), hide_index=True)
st.subheader("Department projects")
st.dataframe(auth.fetch_df(f"""SELECT p.project_code,p.project_name,d.department_name,p.status,p.priority,p.start_date,p.end_date
    FROM hr_oltp.projects p JOIN hr_oltp.departments d USING(department_id)
    WHERE p.department_id IN ({marks}) ORDER BY p.start_date DESC""", params), hide_index=True)
