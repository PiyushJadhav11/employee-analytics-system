"""
Enterprise Employee Analytics — Streamlit entry point.

    streamlit run streamlit_app.py

Data entry pages write to hr_oltp; the dashboard reads only hr_dw.
"""
import logging

import streamlit as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

st.set_page_config(page_title="Employee Analytics DW", page_icon="📊", layout="wide")

pages = {
    "Overview": [
        st.Page("app_pages/home.py", title="Home", icon="🏠", default=True),
        st.Page("app_pages/dashboard.py", title="Analytics Dashboard", icon="📈"),
    ],
    "Data Entry (OLTP)": [
        st.Page("app_pages/onboard.py", title="Onboard Employee", icon="🧑‍💼"),
        st.Page("app_pages/manage_employee.py", title="Transfers & Promotions (SCD2)", icon="🔁"),
        st.Page("app_pages/projects.py", title="Projects & Assignments", icon="🗂️"),
        st.Page("app_pages/reviews.py", title="Performance Reviews", icon="📝"),
    ],
    "Operations": [
        st.Page("app_pages/data_ops.py", title="ETL & Data Ops", icon="⚙️"),
    ],
}

st.navigation(pages).run()
