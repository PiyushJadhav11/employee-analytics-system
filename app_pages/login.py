import streamlit as st
from app_pages.common import auth_manager

st.title("Employee Analytics")
st.caption("Sign in to continue")
auth = auth_manager()

if st.session_state.get("authenticated"):
    st.success(f"Already signed in as {st.session_state.get('display_name', 'user')}.")
    if st.button("Continue"):
        st.rerun()
    st.stop()

login_tab, register_tab = st.tabs(["Sign in", "Employee registration"])
with login_tab:
    with st.form("login_form"):
        email = st.text_input("Work email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        try:
            principal = auth.authenticate(email, password)
        except Exception as exc:
            st.error("Sign-in is temporarily unavailable. Check the database connection and security tables.")
            st.stop()
        if principal is None:
            st.error("Email or password is incorrect.")
        else:
            from app_pages.common import start_session
            start_session(principal)
            st.rerun()

with register_tab:
    st.caption("Self-registration is limited to existing employee records. It cannot create administrator or HR accounts. This local prototype does not verify mailbox ownership; do not expose registration publicly until email verification or SSO is configured.")
    with st.form("register_form"):
        reg_email = st.text_input("Company email", key="reg_email")
        display_name = st.text_input("Full name", key="reg_name")
        p1 = st.text_input("Create passphrase (12+ characters)", type="password", key="reg_p1")
        p2 = st.text_input("Confirm passphrase", type="password", key="reg_p2")
        reg = st.form_submit_button("Create employee account", use_container_width=True)
    if reg:
        if p1 != p2:
            st.error("The passwords do not match.")
        else:
            try:
                uid = auth.register_employee(reg_email, display_name, p1)
                st.success("Account created. Sign in with your company email and new passphrase.")
            except Exception as exc:
                st.error(str(exc))
