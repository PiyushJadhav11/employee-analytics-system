
"""Enterprise Workforce Analytics - Platform Overview."""

from textwrap import dedent

import streamlit as st

from app_pages.common import get, run


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------

def format_number(value):
    """Format a numeric value with thousands separators."""
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "—"


def format_percentage(value):
    """Format percentage values consistently."""
    try:
        return f"{float(value or 0):.2f}%"
    except (TypeError, ValueError):
        return "—"


def format_performance(value):
    """Format average performance on a five-point scale."""
    try:
        return f"{float(value):.2f} / 5.00"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("Platform Overview")

st.caption(
    "Enterprise Workforce Analytics | Workforce intelligence, "
    "employee lifecycle management and dimensional reporting."
)

st.html(dedent("""
<div style="
    position: relative;
    overflow: hidden;
    padding: 28px 30px;
    margin: 12px 0 28px 0;
    border: 1px solid rgba(99, 203, 181, 0.28);
    border-radius: 18px;
    background:
        radial-gradient(
            circle at 95% 5%,
            rgba(99, 203, 181, 0.16),
            transparent 35%
        ),
        linear-gradient(
            120deg,
            rgba(30, 59, 67, 0.94),
            rgba(25, 43, 60, 0.93)
        );
    box-shadow:
        0 12px 35px rgba(0, 0, 0, 0.17),
        inset 0 1px 0 rgba(255, 255, 255, 0.04);
">
    <div style="
        color: #63CBB5;
        font-size: 11px;
        font-weight: 750;
        letter-spacing: 1.8px;
        margin-bottom: 12px;
    ">
        ENTERPRISE DATA INTELLIGENCE
    </div>

    <div style="
        color: #F1F6F8;
        font-size: clamp(21px, 2.2vw, 28px);
        font-weight: 750;
        letter-spacing: -0.7px;
        line-height: 1.3;
        margin-bottom: 10px;
    ">
        From workforce data to actionable intelligence.
    </div>

    <div style="
        color: #C0D0D9;
        font-size: 14px;
        line-height: 1.8;
        max-width: 900px;
    ">
        A centralized analytics platform to manage employee records,
        track workforce changes, monitor project performance and
        discover business insights through an integrated MySQL
        data warehouse.
    </div>

    <div style="
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 20px;
    ">
        <span style="
            padding: 6px 11px;
            border: 1px solid rgba(99, 203, 181, 0.25);
            border-radius: 20px;
            color: #A3E8D9;
            background: rgba(99, 203, 181, 0.08);
            font-size: 11px;
            font-weight: 650;
        ">WORKFORCE ANALYTICS</span>

        <span style="
            padding: 6px 11px;
            border: 1px solid rgba(130, 158, 208, 0.25);
            border-radius: 20px;
            color: #B7C9EB;
            background: rgba(130, 158, 208, 0.08);
            font-size: 11px;
            font-weight: 650;
        ">DIMENSIONAL DATA WAREHOUSE</span>

        <span style="
            padding: 6px 11px;
            border: 1px solid rgba(217, 180, 119, 0.25);
            border-radius: 20px;
            color: #E8C994;
            background: rgba(217, 180, 119, 0.08);
            font-size: 11px;
            font-weight: 650;
        ">ETL PIPELINE</span>
    </div>
</div>
"""))


# ---------------------------------------------------------------------
# Workforce KPIs
# ---------------------------------------------------------------------

st.subheader("Workforce Performance Indicators")

st.caption(
    "A consolidated snapshot of workforce size, attrition, "
    "performance and warehouse records."
)

kpi = run(lambda: get("analytics").kpis()) or {}

if kpi:

    metric_columns = st.columns(5, gap="medium")

    with metric_columns[0]:
        st.metric(
            "Active Headcount",
            format_number(kpi.get("active_headcount")),
            help="Number of currently active employees.",
        )

    with metric_columns[1]:
        st.metric(
            "Attrition Rate",
            format_percentage(kpi.get("attrition_rate_pct")),
            help="Attrition rate returned by the analytics manager.",
        )

    with metric_columns[2]:
        latest_year = kpi.get("latest_year") or "Latest"

        st.metric(
            "Avg. Review Score",
            format_performance(kpi.get("latest_avg_score")),
            help=(
                f"Average performance score for {latest_year}, "
                "measured on a five-point scale."
            ),
        )

    with metric_columns[3]:
        st.metric(
            "Fact Reviews",
            format_number(kpi.get("total_reviews")),
            help="Performance review records in the data warehouse.",
        )

    with metric_columns[4]:
        st.metric(
            "SCD2 Versions",
            format_number(kpi.get("historical_versions")),
            help=(
                "Historical employee dimension versions "
                "maintained through SCD Type 2."
            ),
        )

else:
    st.info(
        "Workforce performance indicators are currently unavailable. "
        "Check the analytics database connection."
    )


st.divider()


# ---------------------------------------------------------------------
# Data architecture
# ---------------------------------------------------------------------

st.subheader("Enterprise Data Architecture")

st.caption(
    "A layered data architecture separating raw ingestion, "
    "transactional processing and analytical reporting."
)

architecture_columns = st.columns(3, gap="medium")

architecture = [
    {
        "layer": "LAYER 01 · DATA INGESTION",
        "title": "Staging Database",
        "database": "hr_staging",
        "color": "#D9B477",
        "description": (
            "Receives source CSV files and maintains raw staging "
            "records before operational processing."
        ),
        "features": [
            "CSV data ingestion",
            "Initial data validation",
            "Rejected-row tracking",
        ],
    },
    {
        "layer": "LAYER 02 · TRANSACTIONAL",
        "title": "Operational Database",
        "database": "hr_oltp",
        "color": "#829ED0",
        "description": (
            "Maintains normalized operational records and supports "
            "employee and project transactions."
        ),
        "features": [
            "Normalized relational tables",
            "Employee lifecycle operations",
            "Project and review transactions",
        ],
    },
    {
        "layer": "LAYER 03 · ANALYTICAL",
        "title": "Data Warehouse",
        "database": "hr_dw",
        "color": "#63CBB5",
        "description": (
            "Stores dimensional data and historical records for "
            "reporting and workforce analytics."
        ),
        "features": [
            "Star-schema dimensional model",
            "SCD Type 2 history",
            "Fact-based analytical reporting",
        ],
    },
]

for column, item in zip(architecture_columns, architecture):
    with column:
        feature_html = "".join(
            f'<div style="margin-top:7px;color:#B9C9D3;'
            f'font-size:12px;line-height:1.5;">'
            f'<span style="color:{item["color"]};">●</span> '
            f'{feature}</div>'
            for feature in item["features"]
        )

        st.html(dedent(f"""
        <div style="
            min-height: 270px;
            height: 100%;
            padding: 21px 19px;
            border: 1px solid rgba(148, 170, 190, 0.19);
            border-top: 3px solid {item["color"]};
            border-radius: 15px;
            background: linear-gradient(
                145deg,
                rgba(34, 51, 69, 0.88),
                rgba(21, 36, 52, 0.90)
            );
            box-shadow:
                0 9px 25px rgba(0, 0, 0, 0.13),
                inset 0 1px 0 rgba(255, 255, 255, 0.03);
        ">
            <div style="
                color: {item["color"]};
                font-size: 10px;
                font-weight: 750;
                letter-spacing: 1.1px;
            ">{item["layer"]}</div>

            <div style="
                margin-top: 12px;
                color: #F0F5F8;
                font-size: 19px;
                font-weight: 720;
            ">{item["title"]}</div>

            <div style="
                display: inline-block;
                margin-top: 9px;
                padding: 5px 9px;
                border-radius: 6px;
                background: rgba(255, 255, 255, 0.055);
                color: {item["color"]};
                font-family: monospace;
                font-size: 12px;
            ">{item["database"]}</div>

            <div style="
                margin-top: 14px;
                color: #AFC0CC;
                font-size: 12px;
                line-height: 1.65;
            ">{item["description"]}</div>

            <div style="
                margin-top: 13px;
                padding-top: 11px;
                border-top: 1px solid rgba(148, 170, 190, 0.13);
            ">
                {feature_html}
            </div>
        </div>
        """))


# ---------------------------------------------------------------------
# ETL flow
# ---------------------------------------------------------------------

st.html(dedent("""
<div style="
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: 12px;
    margin: 17px 0 25px 0;
    padding: 15px;
    border: 1px solid rgba(148, 170, 190, 0.14);
    border-radius: 12px;
    background: rgba(24, 39, 57, 0.48);
">
    <span style="color:#D9B477;font-size:12px;font-weight:700;">
        STAGING
    </span>
    <span style="color:#8296A7;font-size:17px;">→</span>
    <span style="color:#829ED0;font-size:12px;font-weight:700;">
        OLTP
    </span>
    <span style="color:#8296A7;font-size:17px;">→</span>
    <span style="color:#63CBB5;font-size:12px;font-weight:700;">
        DATA WAREHOUSE
    </span>
    <span style="
        margin-left: 7px;
        color: #8296A7;
        font-size: 10px;
    ">ETL DATA FLOW</span>
</div>
"""))


st.divider()


# ---------------------------------------------------------------------
# Platform capabilities
# ---------------------------------------------------------------------

st.subheader("Platform Capabilities")

st.caption(
    "Core functional modules supporting employee management, "
    "project operations, workforce intelligence and data engineering."
)

capability_columns = st.columns(2, gap="medium")

capabilities = [
    {
        "number": "01",
        "title": "Employee Lifecycle Management",
        "color": "#63CBB5",
        "description": (
            "Manage employee records and organizational changes "
            "throughout the employment lifecycle."
        ),
        "items": [
            "Employee onboarding and profile management",
            "Department transfers and promotions",
            "Salary revisions and employee exits",
            "SCD Type 2 historical tracking",
        ],
    },
    {
        "number": "02",
        "title": "Project Portfolio Management",
        "color": "#D9B477",
        "description": (
            "Manage project information, assignments and "
            "workforce allocation."
        ),
        "items": [
            "Project creation and status tracking",
            "Employee allocation and assignments",
            "Staffing and utilization analysis",
            "Project bottleneck identification",
        ],
    },
    {
        "number": "03",
        "title": "Workforce Intelligence",
        "color": "#829ED0",
        "description": (
            "Analyze employee performance, organizational trends "
            "and workforce attrition."
        ),
        "items": [
            "Year-over-year performance trends",
            "Department-wise performance comparison",
            "Top employee rankings using SQL window functions",
            "Attrition risk and contributing factors",
        ],
    },
    {
        "number": "04",
        "title": "Data Engineering & Quality",
        "color": "#C49BD9",
        "description": (
            "Maintain warehouse synchronization, data quality "
            "and operational traceability."
        ),
        "items": [
            "OLTP-to-warehouse ETL processing",
            "Data reconciliation and validation",
            "Staging loads and rejected-row tracking",
            "ETL audit logs and SCD Type 2 verification",
        ],
    },
]

for index, item in enumerate(capabilities):
    column = capability_columns[index % 2]

    with column:
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="
                    color:{item['color']};
                    font-size:11px;
                    font-weight:750;
                    letter-spacing:1px;
                ">
                    MODULE {item['number']}
                </div>
                <div style="
                    color:#EDF4F8;
                    font-size:18px;
                    font-weight:700;
                    margin-top:7px;
                ">
                    {item['title']}
                </div>
                <div style="
                    color:#9AABBA;
                    font-size:12px;
                    margin-top:7px;
                    line-height:1.6;
                ">
                    {item['description']}
                </div>
                """,
                unsafe_allow_html=True,
            )

            for feature in item["items"]:
                st.markdown(
                    f"<span style='color:{item['color']};'>●</span> "
                    f"{feature}",
                    unsafe_allow_html=True,
                )


st.divider()


# ---------------------------------------------------------------------
# SCD Type 2 explanation
# ---------------------------------------------------------------------

st.subheader("Slowly Changing Dimension · Type 2")

st.caption(
    "SCD Type 2 preserves employee history by expiring the previous "
    "dimension record and inserting a new version when tracked "
    "attributes change."
)

with st.container(border=True):

    previous_column, transition_column, current_column = st.columns(
        [5, 1, 5],
        gap="medium",
    )

    with previous_column:
        st.html(dedent("""
        <div style="
            padding: 18px;
            border: 1px solid rgba(130, 158, 208, 0.35);
            border-radius: 12px;
            background: rgba(49, 68, 96, 0.25);
        ">
            <div style="
                color: #829ED0;
                font-size: 10px;
                font-weight: 750;
                letter-spacing: 1px;
            ">HISTORICAL VERSION</div>

            <div style="
                color: #EDF4F8;
                font-size: 16px;
                font-weight: 700;
                margin-top: 12px;
            ">Previous employee attributes</div>

            <div style="
                color: #AAB9C6;
                font-size: 12px;
                margin-top: 8px;
            ">Previous department / job role</div>

            <div style="
                margin-top: 15px;
                padding-top: 10px;
                border-top: 1px solid rgba(130, 158, 208, 0.20);
                color: #A9C0E6;
                font-family: monospace;
                font-size: 12px;
            ">is_current = 0</div>
        </div>
        """))

    with transition_column:
        st.markdown(
            "<div style='text-align:center;padding-top:55px;"
            "color:#63CBB5;font-size:26px;font-weight:700;'>→</div>",
            unsafe_allow_html=True,
        )

    with current_column:
        st.html(dedent("""
        <div style="
            padding: 18px;
            border: 1px solid rgba(99, 203, 181, 0.38);
            border-radius: 12px;
            background: rgba(36, 87, 76, 0.25);
        ">
            <div style="
                color: #63CBB5;
                font-size: 10px;
                font-weight: 750;
                letter-spacing: 1px;
            ">CURRENT VERSION</div>

            <div style="
                color: #EDF4F8;
                font-size: 16px;
                font-weight: 700;
                margin-top: 12px;
            ">Updated employee attributes</div>

            <div style="
                color: #AAB9C6;
                font-size: 12px;
                margin-top: 8px;
            ">Updated department / job role</div>

            <div style="
                margin-top: 15px;
                padding-top: 10px;
                border-top: 1px solid rgba(99, 203, 181, 0.20);
                color: #8AE2D0;
                font-family: monospace;
                font-size: 12px;
            ">is_current = 1</div>
        </div>
        """))

    st.caption(
        "Each new version has its own surrogate key and validity period. "
        "The previous record remains available for historical analysis."
    )


# ---------------------------------------------------------------------
# Database health
# ---------------------------------------------------------------------

with st.expander("Database Connectivity & Server Information"):

    info = run(lambda: get("etl").health_check())

    if info:
        st.success("Database connection established.")

        health_columns = st.columns(2)

        health_columns[0].metric(
            "MySQL Server Version",
            str(info["version"]),
        )

        health_columns[1].write(
            f"**Database Server Time**\n\n{info['server_time']}"
        )
