
"""
Enterprise Workforce Analytics Platform
Streamlit application entry point.
"""

import logging

import streamlit as st

from app_pages.common import apply_theme, render_sidebar


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


# ---------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="Enterprise Workforce Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()


# ---------------------------------------------------------------------
# Navigation configuration
# ---------------------------------------------------------------------

# Register login explicitly. Streamlit can only switch to pages
# registered through st.navigation().

login_page = st.Page(
    "app_pages/login.py",
    title="Login",
    icon="🔐",
    url_path="login",
)

change_password_page = st.Page(
    "app_pages/change_password.py",
    title="Change Password",
    icon="🔑",
    url_path="change-password",
)

self_profile_page = st.Page(
    "app_pages/self_profile.py",
    title="My Profile",
    icon="👤",
    url_path="my-profile",
)

admin_page = st.Page(
    "app_pages/admin.py",
    title="Administration",
    icon="🛡️",
    url_path="admin",
)

department_dashboard_page = st.Page(
    "app_pages/department_dashboard.py",
    title="Department Dashboard",
    icon="📈",
    url_path="department-dashboard",
)


pages = {
    "ACCOUNT": [
        login_page,
        change_password_page,
        self_profile_page,
        admin_page,
    ],

    "OVERVIEW": [
        st.Page(
            "app_pages/home.py",
            title="Platform Overview",
            icon="🏠",
            default=True,
        ),
        st.Page(
            "app_pages/dashboard.py",
            title="Workforce Intelligence",
            icon="📊",
        ),
        department_dashboard_page,
    ],

    "WORKFORCE MANAGEMENT": [
        st.Page(
            "app_pages/onboard.py",
            title="Employee Onboarding",
            icon="👤",
        ),
        st.Page(
            "app_pages/manage_employee.py",
            title="Employee Lifecycle & SCD Type 2",
            icon="🔄",
        ),
        st.Page(
            "app_pages/projects.py",
            title="Project Portfolio",
            icon="📁",
        ),
        st.Page(
            "app_pages/reviews.py",
            title="Performance Management",
            icon="⭐",
        ),
    ],

    "DATA ENGINEERING": [
        st.Page(
            "app_pages/data_ops.py",
            title="Data Warehouse Operations",
            icon="⚙️",
        ),
    ],
}


# ---------------------------------------------------------------------
# Render navigation
# ---------------------------------------------------------------------

navigation = st.navigation(
    pages,
    position="sidebar",
)


# ---------------------------------------------------------------------
# Sidebar branding
# ---------------------------------------------------------------------

with st.sidebar:

    st.html("""
    <div style="
        padding: 15px 12px 18px 12px;
        margin: 8px 0 18px 0;
        border: 1px solid rgba(99, 203, 181, 0.25);
        border-radius: 15px;
        background: linear-gradient(
            135deg,
            rgba(99, 203, 181, 0.14),
            rgba(68, 102, 139, 0.12)
        );
        box-shadow: 0 8px 22px rgba(0, 0, 0, 0.14);
    ">
        <div style="
            display: flex;
            align-items: center;
            gap: 11px;
        ">
            <div style="
                width: 39px;
                height: 39px;
                min-width: 39px;
                border-radius: 13px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #63CBB5, #438F91);
                color: #10231F;
                font-size: 20px;
                font-weight: 800;
            ">W</div>

            <div>
                <div style="
                    color: #EDF4F8;
                    font-size: 13px;
                    font-weight: 750;
                    letter-spacing: 0.25px;
                ">WORKFORCE</div>

                <div style="
                    color: #9AABBA;
                    font-size: 10px;
                    font-weight: 600;
                    letter-spacing: 1.2px;
                ">ANALYTICS PLATFORM</div>
            </div>
        </div>

        <div style="
            margin-top: 13px;
            padding-top: 10px;
            border-top: 1px solid rgba(148, 170, 190, 0.16);
            color: #91A6B5;
            font-size: 10px;
            letter-spacing: 0.65px;
        ">
            ENTERPRISE DATA INTELLIGENCE
        </div>
    </div>
    """)

    st.html("""
    <div style="
        margin-top: 22px;
        padding: 12px 10px;
        border-top: 1px solid rgba(148, 170, 190, 0.15);
    ">
        <div style="
            display: flex;
            align-items: center;
            gap: 7px;
            color: #8EA4B4;
            font-size: 10px;
            font-weight: 650;
            letter-spacing: 0.8px;
        ">
            <span style="
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: #63CBB5;
                box-shadow: 0 0 9px rgba(99, 203, 181, 0.65);
                display: inline-block;
            "></span>
            ANALYTICS WORKSPACE
        </div>

        <div style="
            color: #718596;
            font-size: 10px;
            margin-top: 6px;
        ">
            Enterprise Workforce Data Platform
        </div>
    </div>
    """)


# ---------------------------------------------------------------------
# Run selected page
# ---------------------------------------------------------------------
if st.session_state.get("authenticated"):
    render_sidebar()
navigation.run()
