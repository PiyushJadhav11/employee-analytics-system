import streamlit as st
from app_pages.common import auth_manager, current_principal, logout, start_session

principal = current_principal()
st.title("Change your password")
if principal.must_change_password:
    st.warning("A password change is required before you can use the application.")
else:
    st.caption("Update your account passphrase.")
with st.form("required_password_change"):
    old = st.text_input("Current password", type="password")
    new1 = st.text_input("New passphrase (12+ characters)", type="password")
    new2 = st.text_input("Confirm new passphrase", type="password")
    submitted = st.form_submit_button("Update password", type="primary")
if submitted:
    if new1 != new2:
        st.error("The new passphrases do not match.")
    else:
        try:
            auth_manager().change_own_password(principal.user_id, old, new1)
            refreshed = auth_manager().load_principal(principal.user_id)
            start_session(refreshed)
            st.success("Password changed. Continue to the application.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
if st.button("Log out"):
    logout()
