from datetime import date

import streamlit as st

from app_pages.common import department_picker, employee_picker, get, request_key, role_picker, run, show_write_result

st.title("Transfers, promotions & salary changes")
st.caption("Each change closes the current version in hr_oltp.employee_history and opens a new one. "
           "hr_dw.sp_load_dim_employee then expires the current dim_employee row and inserts a new one "
           "(SCD Type 2).")

emp = employee_picker(key="mgr")
if not emp:
    st.stop()

emp_id = int(emp["employee_id"])
current = run(lambda: get("employee").get(emp_id))
if not current:
    st.stop()

st.markdown(f"### {current['first_name']} {current['last_name']} · #{current['employee_number']}")
m = st.columns(4)
m[0].metric("Department", current["department_name"])
m[1].metric("Role", current["job_role"])
m[2].metric("Level", current["job_level"])
m[3].metric("Monthly income", f"{float(current['monthly_income']):,.0f}")

tab_change, tab_history, tab_exit = st.tabs(["Change position", "Version history", "Record exit"])

with tab_change:
    reason_label = st.radio("Type of change", ["Department transfer", "Promotion", "Salary revision"], horizontal=True)
    reason = {"Department transfer": "DEPARTMENT_TRANSFER", "Promotion": "PROMOTION",
              "Salary revision": "SALARY_REVISION"}[reason_label]
    c1, c2 = st.columns(2)
    with c1:
        new_dept = department_picker("New department", key="chg_dept", default_id=int(current["department_id"]))
    with c2:
        new_role = role_picker("New role", new_dept, key="chg_role", default_id=int(current["job_role_id"]))
    c1, c2, c3 = st.columns(3)
    default_level = min(int(current["job_level"]) + (1 if reason == "PROMOTION" else 0), 5)
    new_level = c1.slider("Job level", 1, 5, default_level)
    bump = 1.15 if reason == "PROMOTION" else 1.08 if reason == "SALARY_REVISION" else 1.0
    new_income = c2.number_input("Monthly income", min_value=1000.0, max_value=100000.0,
                                 value=round(float(current["monthly_income"]) * bump, 0), step=100.0)
    eff = c3.date_input("Effective date", value=date.today())

    if st.button("Apply change", type="primary"):
        # current state is part of the key: once this change lands, the same values can be
        # submitted again later (e.g. a transfer back) without being mistaken for a duplicate
        key = request_key("change_position", {"emp": emp_id, "dept": new_dept, "role": new_role, "level": new_level,
                                              "income": new_income, "eff": eff, "reason": reason,
                                              "from": (current["department_id"], current["job_role_id"],
                                                       current["job_level"], str(current["monthly_income"]))})
        result = run(lambda: get("employee").change_position(
            emp_id, new_dept, new_role, eff, reason=reason, job_level=new_level, monthly_income=new_income,
            request_key=key))
        if result:
            show_write_result(result)
            st.cache_data.clear()

with tab_history:
    st.markdown("**OLTP — `hr_oltp.employee_history`** (system of record)")
    st.dataframe(run(lambda: get("employee").oltp_history(emp_id)), hide_index=True, use_container_width=True)
    st.markdown("**Warehouse — `hr_dw.dim_employee`** (one surrogate key per version)")
    dw = run(lambda: get("employee").dw_versions(emp_id))
    if dw is not None and not dw.empty:
        st.dataframe(
            dw.style.apply(lambda r: ["background-color: #e7f5ec" if r["is_current"] else "" for _ in r], axis=1),
            hide_index=True, use_container_width=True)
    st.markdown("**Reviews** — each fact row keeps the version that was current on its review date")
    st.dataframe(run(lambda: get("review").for_employee(emp_id)), hide_index=True, use_container_width=True)

with tab_exit:
    st.caption("Attrition is a Type 1 attribute: it overwrites every version instead of creating a new one.")
    leave = st.date_input("Last working day", value=date.today(), key="exit_date")
    if st.button("Record exit"):
        result = run(lambda: get("employee").terminate(
            emp_id, leave, request_key=request_key("terminate", {"emp": emp_id, "date": leave})))
        show_write_result(result)
