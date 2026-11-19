
"""
Enterprise Workforce Analytics Platform
Streamlit application entry point.
"""

import logging

import streamlit as st

from app_pages.common import apply_theme


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

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

pages = {
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


    # Sidebar footer
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

navigation.run()
