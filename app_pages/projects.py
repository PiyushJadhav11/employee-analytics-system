
from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from app_pages.common import (
    PLOTLY_TEMPLATE,
    department_picker,
    employee_picker,
    get,
    request_key,
    run,
    show_write_result,
)
from hr_analytics.models import Project, ValidationError


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("Projects & Assignments")

st.caption(
    "Manage organizational projects, allocate employees "
    "and identify project staffing bottlenecks."
)

st.markdown(
    """
    <div style="
        background:linear-gradient(110deg,#1D3540 0%,#1D2A35 70%,#26313E 100%);
        border:1px solid #34504F;
        border-left:4px solid #829ED0;
        border-radius:11px;
        padding:19px 22px;
        margin:10px 0 24px 0;
    ">
        <div style="
            color:#829ED0;
            font-size:11px;
            font-weight:700;
            letter-spacing:1.2px;
        ">
            PROJECT MANAGEMENT WORKSPACE
        </div>
        <div style="
            color:#F0F4F7;
            font-size:20px;
            font-weight:650;
            margin-top:7px;
        ">
            Plan projects and manage workforce allocation.
        </div>
        <div style="
            color:#B8C7D1;
            font-size:13px;
            line-height:1.6;
            margin-top:6px;
        ">
            Create projects, assign employees, monitor project records
            and analyze staffing constraints through the analytics warehouse.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Project management tabs
# ---------------------------------------------------------------------

tab_new, tab_assign, tab_list, tab_bottle = st.tabs(
    [
        "Create Project",
        "Assign Employee",
        "Browse Projects",
        "Bottleneck Analysis",
    ]
)


# =====================================================================
# 1. CREATE PROJECT
# =====================================================================

with tab_new:

    st.subheader("Create a new project")

    st.caption(
        "Register a project with its ownership, timeline, budget and priority."
    )

    with st.container(border=True):

        st.markdown("### Project ownership")

        dept = department_picker(
            "Owning department",
            key="prj_dept",
        )

        st.divider()

        with st.form("new_project"):

            st.markdown("### 01 · Project information")

            a, b = st.columns([1, 3])

            code = a.text_input(
                "Project code",
                placeholder="PRJ-09001",
            )

            name = b.text_input(
                "Project name",
                placeholder="Enter project name",
            )

            st.divider()

            st.markdown("### 02 · Timeline and budget")

            a, b, c = st.columns(3)

            start = a.date_input(
                "Start date",
                value=date.today(),
            )

            end = b.date_input(
                "End date",
                value=date.today() + timedelta(days=180),
            )

            budget = c.number_input(
                "Budget",
                min_value=0.0,
                value=500000.0,
                step=10000.0,
            )

            st.divider()

            st.markdown("### 03 · Project classification")

            a, b, c = st.columns(3)

            status = a.selectbox(
                "Status",
                Project.STATUSES,
            )

            priority = b.selectbox(
                "Priority",
                Project.PRIORITIES,
                index=1,
            )

            client = c.text_input(
                "Client",
            )

            st.divider()

            ok = st.form_submit_button(
                "Create project",
                type="primary",
                use_container_width=True,
            )

    if ok:

        try:
            project = Project(
                code,
                name,
                dept,
                start,
                end,
                budget,
                status,
                priority,
                client or None,
            )

        except ValidationError as exc:
            st.warning(str(exc))

        else:

            key = request_key(
                "create_project",
                project.to_record(),
            )

            result = run(
                lambda: get("project").create(
                    project,
                    request_key=key,
                )
            )

            show_write_result(result)


# =====================================================================
# 2. ASSIGN EMPLOYEE
# =====================================================================

with tab_assign:

    st.subheader("Assign an employee to a project")

    st.caption(
        "Allocate an employee to an active project and define their "
        "responsibility, allocation percentage and assignment period."
    )

    emp = employee_picker(key="asg")

    projects = run(
        lambda: get("project").list(
            status="Active",
            limit=1000,
        )
    )

    if emp and projects is not None and not projects.empty:

        labels = {
            int(r.project_id):
            f"{r.project_code} · {r.project_name} ({r.department_name})"
            for r in projects.itertuples()
        }

        with st.container(border=True):

            st.markdown("### Assignment details")

            with st.form("assign"):

                pid = st.selectbox(
                    "Active project",
                    list(labels),
                    format_func=labels.get,
                )

                st.divider()

                a, b = st.columns(2)

                role = a.selectbox(
                    "Assignment role",
                    [
                        "Contributor",
                        "Analyst",
                        "Developer",
                        "Lead",
                        "Reviewer",
                        "Coordinator",
                    ],
                )

                alloc = b.select_slider(
                    "Allocation percentage",
                    [10, 25, 50, 75, 100],
                    50,
                )

                st.divider()

                st.markdown("**Assignment period**")

                a, b = st.columns(2)

                s = a.date_input(
                    "Start date",
                    value=date.today(),
                )

                e = b.date_input(
                    "End date",
                    value=date.today() + timedelta(days=90),
                )

                st.divider()

                submitted = st.form_submit_button(
                    "Assign employee",
                    type="primary",
                    use_container_width=True,
                )

        if submitted:

            key = request_key(
                "assign",
                {
                    "emp": int(emp["employee_id"]),
                    "pid": pid,
                    "role": role,
                    "alloc": alloc,
                    "s": s,
                    "e": e,
                },
            )

            result = run(
                lambda: get("project").assign(
                    int(emp["employee_id"]),
                    pid,
                    role,
                    alloc,
                    s,
                    e,
                    request_key=key,
                )
            )

            show_write_result(result)

    elif projects is not None and projects.empty:

        st.info(
            "No active projects are currently available. "
            "Create an active project before assigning employees."
        )

    elif not emp:

        st.info(
            "Select an employee above to continue with project assignment."
        )


# =====================================================================
# 3. BROWSE PROJECTS
# =====================================================================

with tab_list:

    st.subheader("Project directory")

    st.caption(
        "Browse registered projects and filter them using their current status."
    )

    with st.container(border=True):

        status = st.selectbox(
            "Filter by project status",
            ["All", *Project.STATUSES],
        )

        df = run(
            lambda: get("project").list(
                status=None if status == "All" else status
            )
        )

        if df is not None:

            if df.empty:

                st.info("No projects found for this selection.")

            else:

                st.markdown("### Project overview")

                total_projects = len(df)

                c1, c2, c3 = st.columns(3)

                c1.metric(
                    "Projects found",
                    f"{total_projects:,}",
                )

                if "status" in df.columns:

                    active_count = int(
                        (df["status"] == "Active").sum()
                    )

                    c2.metric(
                        "Active projects",
                        f"{active_count:,}",
                    )

                    c3.metric(
                        "Other statuses",
                        f"{total_projects - active_count:,}",
                    )

                else:

                    c2.metric("Project records", f"{total_projects:,}")
                    c3.metric("Selected filter", status)

                st.divider()

                st.markdown("**Project records**")

                st.dataframe(
                    df,
                    hide_index=True,
                    use_container_width=True,
                )


# =====================================================================
# 4. BOTTLENECK ANALYSIS
# =====================================================================

with tab_bottle:

    st.subheader("Project staffing bottleneck analysis")

    st.caption(
        "Identify projects that may require management attention "
        "based on staffing availability, delays and budget."
    )

    st.markdown(
        """
        <div style="
            background:#1D2A35;
            border:1px solid #354656;
            border-left:4px solid #D9B477;
            border-radius:9px;
            padding:13px 17px;
            margin:10px 0 20px 0;
        ">
            <div style="color:#D9B477;font-size:11px;font-weight:700;
                        letter-spacing:1px;">
                ANALYTICS METHOD
            </div>
            <div style="color:#B8C7D1;font-size:13px;margin-top:5px;">
                Uses a Common Table Expression (CTE) and SQL RANK()
                to identify projects that may need additional attention.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    as_of = st.date_input(
        "Analysis date",
        value=date(2025, 12, 31),
        key="bn_asof",
    )

    bn = run(
        lambda: get("project").bottlenecks(
            as_of,
            limit=25,
        )
    )

    if bn is not None and not bn.empty:

        st.markdown("### Project staffing and delay overview")

        # Summary indicators based on the returned query results.
        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Projects analyzed",
            f"{len(bn):,}",
        )

        if "days_overdue" in bn.columns:

            overdue_count = int(
                (bn["days_overdue"] > 0).sum()
            )

            c2.metric(
                "Overdue projects",
                f"{overdue_count:,}",
            )

        if "fte" in bn.columns:

            c3.metric(
                "Total staffed FTE",
                f"{bn['fte'].fillna(0).sum():,.1f}",
            )

        st.divider()

        # Project staffing scatter plot.
        fig = px.scatter(
            bn,
            x="fte",
            y="days_overdue",
            size="budget",
            color="department_name",
            hover_data=[
                "project_code",
                "project_name",
                "people",
                "priority",
            ],
            template=PLOTLY_TEMPLATE,
            labels={
                "fte": "Staffed FTE",
                "days_overdue": "Days overdue",
                "budget": "Project budget",
                "department_name": "Department",
            },
            color_discrete_sequence=[
                "#63CBB5",
                "#D9B477",
                "#829ED0",
            ],
        )

        fig.update_layout(
            height=480,
            margin=dict(l=15, r=15, t=25, b=15),
            legend_title_text="Department",
            hoverlabel=dict(
                bgcolor="#1D2A35",
                font_color="#F0F4F7",
            ),
        )

        fig.update_xaxes(
            zeroline=False,
            gridcolor="#293846",
        )

        fig.update_yaxes(
            zeroline=True,
            zerolinecolor="#82909D",
            gridcolor="#293846",
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        st.caption(
            "Each bubble represents a project. Bubble size reflects its "
            "budget, the horizontal axis represents staffed FTE, and the "
            "vertical axis represents overdue days."
        )

        with st.expander(
            "View bottleneck analysis details",
            expanded=True,
        ):

            st.dataframe(
                bn,
                hide_index=True,
                use_container_width=True,
            )

    elif bn is not None:

        st.info(
            "No project bottlenecks were returned for the selected date."
        )
