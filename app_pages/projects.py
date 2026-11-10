from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from app_pages.common import PLOTLY_TEMPLATE, department_picker, employee_picker, get, request_key, run, show_write_result
from hr_analytics.models import Project, ValidationError

st.title("Projects & assignments")

tab_new, tab_assign, tab_list, tab_bottle = st.tabs(
    ["Create project", "Assign employee", "Browse projects", "Bottleneck analysis"])

with tab_new:
    dept = department_picker("Owning department", key="prj_dept")
    with st.form("new_project"):
        a, b = st.columns([1, 3])
        code = a.text_input("Project code", placeholder="PRJ-09001")
        name = b.text_input("Project name")
        a, b, c = st.columns(3)
        start = a.date_input("Start date", value=date.today())
        end = b.date_input("End date", value=date.today() + timedelta(days=180))
        budget = c.number_input("Budget", min_value=0.0, value=500000.0, step=10000.0)
        a, b, c = st.columns(3)
        status = a.selectbox("Status", Project.STATUSES)
        priority = b.selectbox("Priority", Project.PRIORITIES, index=1)
        client = c.text_input("Client")
        ok = st.form_submit_button("Create project", type="primary")
    if ok:
        try:
            project = Project(code, name, dept, start, end, budget, status, priority, client or None)
        except ValidationError as exc:
            st.warning(str(exc))
        else:
            key = request_key("create_project", project.to_record())
            show_write_result(run(lambda: get("project").create(project, request_key=key)))

with tab_assign:
    emp = employee_picker(key="asg")
    projects = run(lambda: get("project").list(status="Active", limit=1000))
    if emp and projects is not None and not projects.empty:
        labels = {int(r.project_id): f"{r.project_code} · {r.project_name} ({r.department_name})"
                  for r in projects.itertuples()}
        with st.form("assign"):
            pid = st.selectbox("Active project", list(labels), format_func=labels.get)
            a, b, c, d = st.columns(4)
            role = a.selectbox("Role", ["Contributor", "Analyst", "Developer", "Lead", "Reviewer", "Coordinator"])
            alloc = b.select_slider("Allocation %", [10, 25, 50, 75, 100], 50)
            s = c.date_input("From", value=date.today())
            e = d.date_input("To", value=date.today() + timedelta(days=90))
            if st.form_submit_button("Assign", type="primary"):
                key = request_key("assign", {"emp": int(emp["employee_id"]), "pid": pid, "role": role,
                                             "alloc": alloc, "s": s, "e": e})
                show_write_result(run(lambda: get("project").assign(int(emp["employee_id"]), pid, role, alloc, s, e,
                                                                    request_key=key)))

with tab_list:
    status = st.selectbox("Status", ["All", *Project.STATUSES])
    df = run(lambda: get("project").list(status=None if status == "All" else status))
    if df is not None:
        st.dataframe(df, hide_index=True, use_container_width=True)

with tab_bottle:
    st.caption("Active / on-hold projects ranked by: overdue first, then thinnest staffing (FTE), then budget. "
               "Computed from hr_oltp with a CTE and RANK().")
    as_of = st.date_input("As of", value=date(2025, 12, 31), key="bn_asof")
    bn = run(lambda: get("project").bottlenecks(as_of, limit=25))
    if bn is not None and not bn.empty:
        fig = px.scatter(bn, x="fte", y="days_overdue", size="budget", color="department_name",
                         hover_data=["project_code", "project_name", "people", "priority"],
                         template=PLOTLY_TEMPLATE, labels={"fte": "Staffed FTE", "days_overdue": "Days overdue"})
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(bn, hide_index=True, use_container_width=True)
