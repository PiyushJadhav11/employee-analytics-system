import streamlit as st
import pandas as pd
from app_pages.common import auth_manager, current_principal, require_permission, departments

st.title("Security administration")
principal = current_principal()
require_permission("user.manage")
require_permission("audit.view")
require_permission("role.manage")
auth = auth_manager()
admin_count = auth.fetch_one("""SELECT COUNT(DISTINCT u.user_id) AS n FROM hr_oltp.users u
    JOIN hr_oltp.user_roles ur USING(user_id) JOIN hr_oltp.roles r USING(role_id)
    WHERE u.is_active=TRUE AND r.role_name='SYSTEM_ADMIN'""")
if admin_count and int(admin_count["n"]) < 2:
    st.warning("There is only one active System Admin. Create a second independent admin account before relying on this application operationally.")

users = auth.users()
st.subheader("User accounts")
if users.empty:
    st.info("No user accounts yet.")
else:
    st.dataframe(users, hide_index=True, use_container_width=True)

with st.expander("Create an account", expanded=True):
    with st.form("create_user"):
        email = st.text_input("Email")
        name = st.text_input("Display name")
        password = st.text_input("Temporary password (12+ characters)", type="password")
        role = st.selectbox("Role", ["SYSTEM_ADMIN", "HR_ADMIN", "HR_MANAGER", "DEPARTMENT_MANAGER", "EMPLOYEE"])
        employee_id_input = st.number_input("Linked employee ID (0 = no link)", min_value=0, value=0, step=1)
        employee_id = int(employee_id_input) or None
        dept_df = departments()
        selected_depts = st.multiselect("Department access", dept_df.department_id.tolist(),
            format_func=lambda x: dept_df.set_index('department_id').loc[x,'department_name'])
        can_manage = st.checkbox("Allow management actions in assigned departments", value=(role == "DEPARTMENT_MANAGER"))
        create = st.form_submit_button("Create user", type="primary")
    if create:
        try:
            uid = auth.create_user(email, name, password, role, employee_id, selected_depts, can_manage, principal.user_id)
            st.success(f"Created user ID {uid} with role {role}.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

st.subheader("Grant / revoke role")
if not users.empty:
    with st.form("grant_role"):
        target = st.selectbox("User", users.user_id.tolist(), format_func=lambda x: f"{users.set_index('user_id').loc[x,'email']} (#{x})")
        role_name = st.selectbox("Role", ["SYSTEM_ADMIN", "HR_ADMIN", "HR_MANAGER", "DEPARTMENT_MANAGER", "EMPLOYEE"])
        operation = st.radio("Action", ["Grant", "Revoke"], horizontal=True)
        confirm_password = st.text_input("Confirm your admin password", type="password")
        grant = st.form_submit_button("Apply role change")
    if grant:
        try:
            if not auth.verify_actor_password(principal.user_id, confirm_password):
                raise ValueError("Admin password confirmation failed.")
            if operation == "Grant":
                auth.grant_role(int(target), role_name, principal.user_id)
            else:
                auth.revoke_role(int(target), role_name, principal.user_id)
            st.success("Role granted." if operation == "Grant" else "Role revoked.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

st.subheader("Department access")
if not users.empty:
    with st.form("dept_grant"):
        target_dept_user = st.selectbox("User account", users.user_id.tolist(), key="dept_user", format_func=lambda x: f"{users.set_index('user_id').loc[x,'email']} (#{x})")
        dept_df = departments()
        dept_id = st.selectbox("Department", dept_df.department_id.tolist(), format_func=lambda x: dept_df.set_index('department_id').loc[x,'department_name'])
        manage = st.checkbox("Can manage department records")
        dept_action = st.radio("Action", ["Grant / update", "Revoke"], horizontal=True)
        dept_submit = st.form_submit_button("Apply department access")
    if dept_submit:
        try:
            if dept_action == "Revoke":
                auth.revoke_department(int(target_dept_user), int(dept_id), principal.user_id)
            else:
                auth.assign_department(int(target_dept_user), int(dept_id), manage, principal.user_id)
            st.success("Department access updated.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

st.subheader("Activate / deactivate account")
if not users.empty:
    with st.form("user_status"):
        target_status = st.selectbox("Account", users.user_id.tolist(), key="status_user", format_func=lambda x: f"{users.set_index('user_id').loc[x,'email']} (#{x})")
        active = st.selectbox("Status", [True, False], format_func=lambda x: "Active" if x else "Inactive")
        status_submit = st.form_submit_button("Update status")
    if status_submit:
        try:
            auth.set_user_active(int(target_status), bool(active), principal.user_id)
            st.success("Account status updated.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

st.subheader("Security audit trail")
st.dataframe(auth.audit_events(200), hide_index=True, use_container_width=True)


st.subheader("Reset a user's password")
if not users.empty:
    with st.form("reset_password"):
        reset_user = st.selectbox("Account", users.user_id.tolist(), key="reset_user",
            format_func=lambda x: f"{users.set_index('user_id').loc[x,'email']} (#{x})")
        new_password = st.text_input("New temporary passphrase (12+ characters)", type="password")
        reset_submit = st.form_submit_button("Reset password")
    if reset_submit:
        try:
            auth.reset_password(int(reset_user), new_password, principal.user_id)
            st.success("Password reset. Deliver the temporary passphrase to the user through a secure channel.")
        except Exception as exc:
            st.error(str(exc))
