import streamlit as st

from app_pages.common import get, run

st.title("Enterprise Employee Analytics & Data Warehouse")
st.caption("Greenfield HR platform · MySQL OLTP + star-schema warehouse · SCD Type 2 employee history")

kpi = run(lambda: get("analytics").kpis()) or {}
if kpi:
    c = st.columns(5)
    c[0].metric("Active headcount", f"{int(kpi.get('active_headcount') or 0):,}")
    c[1].metric("Attrition rate", f"{kpi.get('attrition_rate_pct') or 0}%")
    c[2].metric(f"Avg score {kpi.get('latest_year') or ''}", kpi.get("latest_avg_score") or "–")
    c[3].metric("Reviews in warehouse", f"{int(kpi.get('total_reviews') or 0):,}")
    c[4].metric("Expired SCD2 versions", f"{int(kpi.get('historical_versions') or 0):,}")

st.divider()
left, right = st.columns([3, 2])
with left:
    st.subheader("How data flows")
    st.markdown(
        """
1. **Synthesizer** (`scripts/data_synthesizer.py`) scales the IBM HR snapshot to 100k+ employees and
   engineers prior versions (transfers, promotions, salary revisions).
2. **Staging** (`hr_staging`) receives the raw CSVs, duplicates and messy values included.
3. **OLTP** (`hr_oltp`) is the cleaned, normalized system of record. The forms in this app write here.
4. **Warehouse** (`hr_dw`) is a star schema loaded by stored procedures. `dim_employee` keeps every
   version of an employee's department, role, level and salary (SCD Type 2).
5. **Dashboard** reads only the warehouse.
        """
    )
with right:
    st.subheader("Try the SCD2 flow")
    st.markdown(
        """
- Open **Transfers & Promotions**, pick an employee and move them to another department.
- The page shows the OLTP history row that was closed and the new `dim_employee` version
  the warehouse created, with `start_date`, `end_date` and `is_current`.
- Submit a review for them afterwards: the fact row points at the **new** version, while
  their older reviews stay on the old one.
        """
    )

with st.expander("Database connection"):
    info = run(lambda: get("etl").health_check())
    if info:
        st.write(f"MySQL **{info['version']}** · server time {info['server_time']}")
