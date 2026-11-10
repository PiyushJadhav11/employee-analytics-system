import plotly.express as px
import streamlit as st

from app_pages.common import DEPT_COLORS, PLOTLY_TEMPLATE, get

st.title("Analytics dashboard")
st.caption("Reads only the hr_dw star schema. Department on each review is the one the employee "
           "belonged to on the review date (SCD Type 2).")

an = get("analytics")


@st.cache_data(ttl=300, show_spinner="Querying the warehouse…")
def q(method: str, *args):
    return getattr(an, method)(*args)


try:
    years = q("review_years")
except Exception as exc:  # ManagerError
    st.error(str(exc))
    st.stop()
if not years:
    st.info("The warehouse is empty. Run the ETL from **ETL & Data Ops** first.")
    st.stop()

tab_perf, tab_top, tab_attr, tab_proj = st.tabs(
    ["Year-over-year performance", "Top performers", "Attrition risk", "Project health"])

# ------------------------------------------------------------------ YoY
with tab_perf:
    yoy = q("yoy_performance")
    depts = sorted(d for d in yoy["department_name"].unique() if d != "All departments")
    chosen = st.multiselect("Departments", ["All departments", *depts], default=["All departments", *depts])
    view = yoy[yoy["department_name"].isin(chosen)]

    c1, c2 = st.columns(2)
    fig = px.line(view, x="review_year", y="avg_score", color="department_name", markers=True,
                  color_discrete_map=DEPT_COLORS, template=PLOTLY_TEMPLATE,
                  labels={"review_year": "Review year", "avg_score": "Average score (1–5)", "department_name": ""})
    fig.update_xaxes(dtick=1)
    c1.plotly_chart(fig, use_container_width=True)

    fig = px.bar(view.dropna(subset=["yoy_change_pct"]), x="review_year", y="yoy_change_pct",
                 color="department_name", barmode="group", color_discrete_map=DEPT_COLORS,
                 template=PLOTLY_TEMPLATE,
                 labels={"review_year": "Review year", "yoy_change_pct": "YoY change in avg score (%)",
                         "department_name": ""})
    fig.update_xaxes(dtick=1)
    c2.plotly_chart(fig, use_container_width=True)

    year = st.select_slider("Rating distribution for year", options=sorted(years), value=max(years))
    dist = q("rating_distribution", year)
    dist["rating"] = dist["rating"].map({1: "1 Low", 2: "2 Good", 3: "3 Excellent", 4: "4 Outstanding"})
    fig = px.bar(dist, x="department_name", y="reviews", color="rating", template=PLOTLY_TEMPLATE,
                 color_discrete_sequence=["#d64545", "#f0a35e", "#7fb3e6", "#2a6fdb"],
                 labels={"department_name": "", "reviews": "Reviews"})
    fig.update_layout(barnorm="percent", yaxis_title="% of reviews")
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("Data (vw_yoy_performance)"):
        st.dataframe(view, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ top performers
with tab_top:
    c1, c2, c3 = st.columns(3)
    y = c1.selectbox("Review year", years)
    dept = c2.selectbox("Department", ["All", *sorted(DEPT_COLORS.keys() - {"All departments"})])
    n = c3.slider("Top N ranks", 3, 25, 10)
    top = q("top_performers", y, None if dept == "All" else dept, n)
    st.caption("`DENSE_RANK() OVER (PARTITION BY department ORDER BY avg_score DESC, goals_met DESC)` — "
               "employees with identical score and goals share a rank.")
    if top.empty:
        st.info("No reviews for that selection.")
    else:
        fig = px.bar(top.groupby("department_name").head(15), x="score", y="full_name", color="department_name",
                     orientation="h", color_discrete_map=DEPT_COLORS, template=PLOTLY_TEMPLATE,
                     hover_data=["dept_rank", "employee_number", "current_role", "goals_met_pct"],
                     labels={"score": "Average score", "full_name": "", "department_name": ""})
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=max(400, 22 * min(len(top), 45)))
        fig.update_xaxes(range=[top["score"].min() - 0.1, 5.0])
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(top, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ attrition
with tab_attr:
    val = q("risk_score_validation")
    st.markdown("**Does the risk score mean anything?** Historical leavers vs. stayers:")
    cols = st.columns(len(val) or 1)
    for col, r in zip(cols, val.itertuples()):
        col.metric(f"{r.outcome} ({int(r.employees):,})", f"avg risk {r.avg_risk_score}",
                   f"{r.pct_high_tier}% in High tier", delta_color="off")

    c1, c2 = st.columns(2)
    by_dept = q("attrition_risk_by_department")
    fig = px.bar(by_dept, x="department_name", y="employees", color="risk_tier", template=PLOTLY_TEMPLATE,
                 category_orders={"risk_tier": ["High", "Medium", "Low"]},
                 color_discrete_map={"High": "#d64545", "Medium": "#f0a35e", "Low": "#3aa876"},
                 labels={"department_name": "", "employees": "Active employees", "risk_tier": "Risk tier"},
                 title="Active employees by risk tier")
    c1.plotly_chart(fig, use_container_width=True)

    driver_label = c2.selectbox("Attrition rate by driver", {
        "Overtime": "overtime_flag", "Job satisfaction": "job_satisfaction",
        "Work-life balance": "work_life_balance", "Environment satisfaction": "environment_satisfaction",
        "Job level": "job_level", "Salary band": "salary_band", "Age band": "age_band",
        "Business travel": "business_travel"}.items(), format_func=lambda kv: kv[0])
    drv = q("attrition_by_driver", driver_label[1])
    drv["bucket"] = drv["bucket"].astype(str)
    fig = px.bar(drv, x="bucket", y="attrition_rate_pct", text="attrition_rate_pct", template=PLOTLY_TEMPLATE,
                 hover_data=["employees"], labels={"bucket": driver_label[0], "attrition_rate_pct": "Attrition %"},
                 color_discrete_sequence=["#2a6fdb"])
    c2.plotly_chart(fig, use_container_width=True)

    st.subheader("Highest-risk active employees")
    dept_f = st.selectbox("Department filter", ["All", *sorted(by_dept["department_name"].unique())], key="risk_dept")
    st.dataframe(q("at_risk_employees", None if dept_f == "All" else dept_f, 100),
                 hide_index=True, use_container_width=True)
    st.dataframe(q("department_attrition"), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ projects
with tab_proj:
    st.caption("Projects whose reviewed staff score lowest (vw_project_performance, ≥5 reviews). "
               "For staffing bottlenecks see **Projects & Assignments → Bottleneck analysis**.")
    weak = q("weakest_projects", 20)
    if not weak.empty:
        fig = px.bar(weak, x="avg_score", y="project_code", color="department_name", orientation="h",
                     color_discrete_map=DEPT_COLORS, template=PLOTLY_TEMPLATE,
                     hover_data=["project_name", "reviews", "status"],
                     labels={"avg_score": "Average score", "project_code": "", "department_name": ""})
        fig.update_layout(yaxis={"categoryorder": "total descending"})
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(weak, hide_index=True, use_container_width=True)
