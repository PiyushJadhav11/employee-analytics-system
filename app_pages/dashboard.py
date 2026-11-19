
import plotly.express as px
import streamlit as st

from app_pages.common import DEPT_COLORS, PLOTLY_TEMPLATE, get


# =====================================================================
# SHARED ANALYTICS HELPERS
# =====================================================================

an = get("analytics")


@st.cache_data(ttl=300, show_spinner="Querying the warehouse...")
def q(method: str, *args):
    return getattr(an, method)(*args)


def section_header(title, description):
    """Render a styled section heading without Markdown code-block issues."""
    st.html(
        f"""
        <div style="
            margin: 8px 0 18px 0;
            padding-bottom: 12px;
            border-bottom: 1px solid #304252;
        ">
            <div style="
                color: #E7EDF2;
                font-size: 21px;
                font-weight: 700;
            ">{title}</div>

            <div style="
                color: #91A6B5;
                font-size: 13px;
                margin-top: 5px;
                line-height: 1.5;
            ">{description}</div>
        </div>
        """
    )


def panel_title(title, subtitle=None):
    """Render a compact heading above charts and data panels."""
    subtitle_html = ""

    if subtitle:
        subtitle_html = f"""
            <div style="
                color: #91A6B5;
                font-size: 12px;
                margin-top: 4px;
                line-height: 1.5;
            ">{subtitle}</div>
        """

    st.html(
        f"""
        <div style="margin-bottom: 12px;">
            <div style="
                color: #E7EDF2;
                font-size: 15px;
                font-weight: 650;
            ">{title}</div>
            {subtitle_html}
        </div>
        """
    )


def chart_layout(fig, height=370):
    """Apply the shared dark theme to Plotly charts."""
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        height=height,
        margin=dict(l=18, r=18, t=35, b=18),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            color="#DCE5EC",
            family="Arial, sans-serif",
            size=12,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
        ),
        hoverlabel=dict(
            bgcolor="#1D2A35",
            font_color="#F0F4F7",
        ),
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(145,166,181,0.13)",
        zeroline=False,
    )

    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(145,166,181,0.13)",
        zeroline=False,
    )

    return fig


# =====================================================================
# DASHBOARD HEADER
# =====================================================================

st.title("Workforce Intelligence")

st.caption(
    "Enterprise workforce analytics | Performance, attrition "
    "and project intelligence."
)

st.html(
    """
    <div style="
        background: linear-gradient(110deg, #1D3540, #1D2A35 70%, #26313E);
        border: 1px solid #34504F;
        border-radius: 13px;
        padding: 20px 23px;
        margin: 10px 0 25px 0;
    ">
        <div style="
            color: #63CBB5;
            font-size: 11px;
            font-weight: 750;
            letter-spacing: 1.5px;
        ">
            WORKFORCE ANALYTICS WORKSPACE
        </div>

        <div style="
            color: #F0F4F7;
            font-size: 22px;
            font-weight: 700;
            margin-top: 8px;
        ">
            Turn workforce data into meaningful insights.
        </div>

        <div style="
            color: #B8C7D1;
            font-size: 13px;
            line-height: 1.6;
            margin-top: 7px;
        ">
            Analyze employee performance, identify attrition patterns,
            evaluate project outcomes and explore historical workforce
            data through the hr_dw dimensional warehouse.
        </div>
    </div>
    """
)


# =====================================================================
# WAREHOUSE DATA AVAILABILITY
# =====================================================================

try:
    years = q("review_years")
except Exception as exc:
    st.error(
        f"Unable to retrieve review years from the warehouse: {exc}"
    )
    st.stop()

if not years:
    st.info(
        "No performance review data is currently available. "
        "Run the ETL process from ETL & Data Ops first."
    )
    st.stop()


# =====================================================================
# ANALYTICS NAVIGATION
# =====================================================================

tab_perf, tab_top, tab_attr, tab_proj = st.tabs(
    [
        "Performance Trends",
        "Top Performers",
        "Attrition Analysis",
        "Project Health",
    ]
)


# =====================================================================
# 1. PERFORMANCE TRENDS
# =====================================================================

with tab_perf:

    section_header(
        "Performance overview",
        "Compare employee review scores, annual performance changes "
        "and rating distributions.",
    )

    yoy = q("yoy_performance")

    if yoy.empty:
        st.info("No year-over-year performance data is available.")
    else:
        depts = sorted(
            department
            for department in yoy["department_name"].dropna().unique()
            if department != "All departments"
        )

        with st.container(border=True):
            st.markdown("**Analysis filters**")

            chosen = st.multiselect(
                "Select departments",
                ["All departments", *depts],
                default=["All departments", *depts],
                key="performance_departments",
            )

        view = yoy[
            yoy["department_name"].isin(chosen)
        ]

        if view.empty:
            st.info("No data matches the selected departments.")
        else:
            c1, c2 = st.columns(2)

            with c1:
                panel_title(
                    "Average performance trend",
                    "Average review score across selected departments.",
                )

                fig = px.line(
                    view,
                    x="review_year",
                    y="avg_score",
                    color="department_name",
                    markers=True,
                    color_discrete_map=DEPT_COLORS,
                    template=PLOTLY_TEMPLATE,
                    labels={
                        "review_year": "Review year",
                        "avg_score": "Average score (1–5)",
                        "department_name": "Department",
                    },
                )

                fig.update_xaxes(dtick=1)
                fig.update_yaxes(range=[0, 5.2])

                chart_layout(fig)

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                )

            with c2:
                panel_title(
                    "Year-over-year performance change",
                    "Percentage change in average review scores.",
                )

                change_data = view.dropna(
                    subset=["yoy_change_pct"]
                )

                if change_data.empty:
                    st.info("No year-over-year changes are available.")
                else:
                    fig = px.bar(
                        change_data,
                        x="review_year",
                        y="yoy_change_pct",
                        color="department_name",
                        barmode="group",
                        color_discrete_map=DEPT_COLORS,
                        template=PLOTLY_TEMPLATE,
                        labels={
                            "review_year": "Review year",
                            "yoy_change_pct": "YoY change (%)",
                            "department_name": "Department",
                        },
                    )

                    fig.update_xaxes(dtick=1)

                    chart_layout(fig)

                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                    )

        st.divider()

        section_header(
            "Performance rating distribution",
            "Understand how employee review ratings are distributed "
            "across departments.",
        )

        year = st.select_slider(
            "Select review year",
            options=sorted(years),
            value=max(years),
            key="performance_review_year",
        )

        dist = q("rating_distribution", year)

        if dist.empty:
            st.info(
                "No rating distribution is available for this year."
            )
        else:
            dist = dist.copy()

            dist["rating"] = dist["rating"].map(
                {
                    1: "1 Low",
                    2: "2 Good",
                    3: "3 Excellent",
                    4: "4 Outstanding",
                }
            )

            fig = px.bar(
                dist,
                x="department_name",
                y="reviews",
                color="rating",
                template=PLOTLY_TEMPLATE,
                color_discrete_map={
                    "1 Low": "#D97979",
                    "2 Good": "#D9B477",
                    "3 Excellent": "#829ED0",
                    "4 Outstanding": "#63CBB5",
                },
                labels={
                    "department_name": "Department",
                    "reviews": "Number of reviews",
                    "rating": "Rating",
                },
            )

            fig.update_layout(
                barmode="stack",
                barnorm="percent",
                yaxis_title="% of reviews",
            )

            chart_layout(fig)

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

        with st.expander("View performance data"):
            st.dataframe(
                view,
                hide_index=True,
                use_container_width=True,
            )


# =====================================================================
# 2. TOP PERFORMERS
# =====================================================================

with tab_top:

    section_header(
        "Top-performing employees",
        "Explore employee rankings based on average review scores. "
        "Rankings are calculated using SQL DENSE_RANK().",
    )

    st.caption(
        "Employees with identical ranking values share the same rank."
    )

    c1, c2, c3 = st.columns([1, 1.3, 1])

    with c1:
        y = st.selectbox(
            "Review year",
            years,
            key="top_review_year",
        )

    with c2:
        dept = st.selectbox(
            "Department",
            [
                "All",
                *sorted(
                    set(DEPT_COLORS.keys()) - {"All departments"}
                ),
            ],
            key="top_department",
        )

    with c3:
        n = st.slider(
            "Top N ranks",
            3,
            25,
            10,
            key="top_n",
        )

    top = q(
        "top_performers",
        y,
        None if dept == "All" else dept,
        n,
    )

    if top.empty:
        st.info(
            "No employee review records match the selected filters."
        )
    else:
        st.divider()

        panel_title(
            "Employee performance ranking",
            "Average employee scores grouped by department.",
        )

        chart_data = top.groupby(
            "department_name"
        ).head(15)

        fig = px.bar(
            chart_data,
            x="score",
            y="full_name",
            color="department_name",
            orientation="h",
            color_discrete_map=DEPT_COLORS,
            template=PLOTLY_TEMPLATE,
            hover_data=[
                "dept_rank",
                "employee_number",
                "current_role",
                "goals_met_pct",
            ],
            labels={
                "score": "Average score",
                "full_name": "Employee",
                "department_name": "Department",
            },
        )

        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            xaxis_title="Average review score",
        )

        fig.update_xaxes(
            range=[
                max(0, float(top["score"].min()) - 0.1),
                5.0,
            ]
        )

        chart_layout(
            fig,
            height=max(420, 22 * min(len(top), 45)),
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        with st.expander(
            "Employee ranking details",
            expanded=True,
        ):
            st.dataframe(
                top,
                hide_index=True,
                use_container_width=True,
            )


# =====================================================================
# 3. ATTRITION ANALYSIS
# =====================================================================

with tab_attr:

    section_header(
        "Employee attrition analysis",
        "Examine historical attrition risk scores, department-level "
        "patterns and factors associated with employee exits.",
    )

    val = q("risk_score_validation")

    panel_title(
        "Historical risk-score validation",
        "Comparison of risk scores across historical employee outcomes.",
    )

    if val.empty:
        st.info(
            "No historical risk validation data is available."
        )
    else:
        cols = st.columns(len(val))

        for col, r in zip(cols, val.itertuples()):
            col.metric(
                f"{r.outcome} ({int(r.employees):,})",
                f"Avg. risk {r.avg_risk_score}",
                f"{r.pct_high_tier}% in High tier",
                delta_color="off",
            )

    st.divider()

    c1, c2 = st.columns(2)

    by_dept = q("attrition_risk_by_department")

    with c1:
        panel_title(
            "Active employees by risk tier",
            "Distribution of active employees across risk categories.",
        )

        if by_dept.empty:
            st.info(
                "No department risk data is available."
            )
        else:
            fig = px.bar(
                by_dept,
                x="department_name",
                y="employees",
                color="risk_tier",
                template=PLOTLY_TEMPLATE,
                category_orders={
                    "risk_tier": ["High", "Medium", "Low"],
                },
                color_discrete_map={
                    "High": "#D97979",
                    "Medium": "#D9B477",
                    "Low": "#63CBB5",
                },
                labels={
                    "department_name": "Department",
                    "employees": "Active employees",
                    "risk_tier": "Risk tier",
                },
            )

            chart_layout(fig)

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

    with c2:
        panel_title(
            "Attrition rate by contributing factor",
            "Compare attrition rates across different employee attributes.",
        )

        driver_options = {
            "Overtime": "overtime_flag",
            "Job satisfaction": "job_satisfaction",
            "Work-life balance": "work_life_balance",
            "Environment satisfaction": "environment_satisfaction",
            "Job level": "job_level",
            "Salary band": "salary_band",
            "Age band": "age_band",
            "Business travel": "business_travel",
        }

        driver_label = st.selectbox(
            "Select contributing factor",
            list(driver_options.keys()),
            key="attrition_driver",
        )

        drv = q(
            "attrition_by_driver",
            driver_options[driver_label],
        )

        if drv.empty:
            st.info(
                "No attrition data is available for this factor."
            )
        else:
            drv = drv.copy()
            drv["bucket"] = drv["bucket"].astype(str)

            fig = px.bar(
                drv,
                x="bucket",
                y="attrition_rate_pct",
                text="attrition_rate_pct",
                template=PLOTLY_TEMPLATE,
                hover_data=["employees"],
                labels={
                    "bucket": driver_label,
                    "attrition_rate_pct": "Attrition rate (%)",
                    "employees": "Employees",
                },
                color_discrete_sequence=["#63CBB5"],
            )

            fig.update_traces(
                texttemplate="%{text:.1f}%",
                textposition="outside",
                cliponaxis=False,
            )

            chart_layout(fig)

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

    st.divider()

    section_header(
        "Highest-risk active employees",
        "Review employees with the highest calculated attrition risk scores.",
    )

    if by_dept.empty:
        st.info(
            "No active employee risk records are available."
        )
    else:
        dept_f = st.selectbox(
            "Department filter",
            [
                "All",
                *sorted(
                    by_dept["department_name"].dropna().unique()
                ),
            ],
            key="risk_dept",
        )

        risk = q(
            "at_risk_employees",
            None if dept_f == "All" else dept_f,
            100,
        )

        if risk.empty:
            st.info(
                "No employees match the selected department."
            )
        else:
            st.dataframe(
                risk,
                hide_index=True,
                use_container_width=True,
            )

    with st.expander("Department attrition summary"):
        department_summary = q("department_attrition")

        st.dataframe(
            department_summary,
            hide_index=True,
            use_container_width=True,
        )


# =====================================================================
# 4. PROJECT HEALTH
# =====================================================================

with tab_proj:

    section_header(
        "Project performance and health",
        "Identify projects with comparatively lower average employee "
        "review scores and explore their performance details.",
    )

    st.info(
        "This section highlights project performance using employee "
        "review data. For staffing bottlenecks and assignment details, "
        "visit Projects & Assignments."
    )

    weak = q(
        "weakest_projects",
        20,
    )

    if weak.empty:
        st.info(
            "No project performance data is available yet."
        )
    else:
        panel_title(
            "Projects with the lowest average scores",
            "Projects are displayed using their average employee review scores.",
        )

        fig = px.bar(
            weak,
            x="avg_score",
            y="project_code",
            color="department_name",
            orientation="h",
            color_discrete_map=DEPT_COLORS,
            template=PLOTLY_TEMPLATE,
            hover_data=[
                "project_name",
                "reviews",
                "status",
            ],
            labels={
                "avg_score": "Average score",
                "project_code": "Project code",
                "department_name": "Department",
            },
        )

        fig.update_layout(
            yaxis={"categoryorder": "total descending"},
            xaxis_title="Average review score",
        )

        chart_layout(
            fig,
            height=480,
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        with st.expander(
            "Project performance details",
            expanded=True,
        ):
            st.dataframe(
                weak,
                hide_index=True,
                use_container_width=True,
            )
