
import streamlit as st

from app_pages.common import get, run


# ---------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------

st.title("ETL & Data Operations")

st.caption(
    "Monitor data ingestion, execute warehouse loads, "
    "validate data quality and inspect ETL execution history."
)

st.markdown(
    """
    <div style="
        background:#1D3540;
        border:1px solid #34504F;
        border-left:4px solid #63CBB5;
        border-radius:11px;
        padding:16px 20px;
        margin:10px 0 22px 0;
    ">
        <div style="color:#63CBB5;font-size:11px;font-weight:700;
                    letter-spacing:1px;">
            DATA ENGINEERING WORKSPACE
        </div>
        <div style="color:#F0F4F7;font-size:17px;font-weight:650;
                    margin-top:6px;">
            Maintain reliable and consistent warehouse data.
        </div>
        <div style="color:#B8C7D1;font-size:13px;margin-top:5px;">
            Execute ETL operations, reconcile data layers,
            monitor rejected records and inspect audit history.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Reconciliation status styling
# ---------------------------------------------------------------------

def status_style(df):

    colors = {
        "PASS": "#203D36",
        "FAIL": "#4A292E",
        "WARN": "#493B25",
        "SKIP": "#303943",
        "INFO": "#26364A",
    }

    text_colors = {
        "PASS": "#8BE0C1",
        "FAIL": "#F19A9A",
        "WARN": "#E8C47D",
        "SKIP": "#C1CBD4",
        "INFO": "#A9C5E8",
    }

    def style_row(row):

        status = row.get("status", "")

        background = colors.get(status, "")
        foreground = text_colors.get(status, "#E7EDF2")

        return [
            f"background-color: {background}; color: {foreground};"
            for _ in row
        ]

    return df.style.apply(
        style_row,
        axis=1,
    )


# ---------------------------------------------------------------------
# Reconciliation summary
# ---------------------------------------------------------------------

def show_reconciliation(df):

    if df is None or df.empty:
        st.info("No reconciliation results yet.")
        return

    counts = df["status"].value_counts()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total checks",
        len(df),
    )

    c2.metric(
        "Passed",
        int(counts.get("PASS", 0)),
    )

    c3.metric(
        "Failed",
        int(counts.get("FAIL", 0)),
    )

    c4.metric(
        "Warnings",
        int(counts.get("WARN", 0)),
    )

    if counts.get("FAIL", 0):
        st.error(
            "Some reconciliation checks failed. "
            "Review the failed rows below."
        )

    elif counts.get("WARN", 0):
        st.warning(
            "Reconciliation completed with warnings. "
            "Review the warning rows below."
        )

    else:
        st.success(
            "No failed or warning reconciliation checks."
        )

    cols = [
        c for c in [
            "layer",
            "check_name",
            "expected_value",
            "actual_value",
            "status",
            "details",
        ]
        if c in df
    ]

    st.dataframe(
        status_style(df[cols]),
        hide_index=True,
        use_container_width=True,
    )


# ---------------------------------------------------------------------
# Staging history display helpers
# ---------------------------------------------------------------------

def format_count(value):

    """
    Format integer-like values with comma separators.
    This only changes their display, not the database records.
    """

    try:
        number = float(value)

        if number.is_integer():
            return f"{int(number):,}"

    except (TypeError, ValueError, OverflowError):
        pass

    return value


def prepare_staging_display(df):

    """
    Create a presentation-only copy of staging history.
    The original DataFrame returned by the backend remains unchanged.
    """

    display_df = df.copy()

    count_columns = [
        "csv_rows",
        "staged_rows",
    ]

    for column in count_columns:

        if column in display_df.columns:
            display_df[column] = display_df[column].map(
                format_count
            )

    return display_df


def staging_column_config(df):

    """
    Configure widths and descriptions for available staging columns.
    """

    config = {}

    if "batch_id" in df.columns:
        config["batch_id"] = st.column_config.TextColumn(
            "Batch ID",
            width="small",
        )

    if "table_name" in df.columns:
        config["table_name"] = st.column_config.TextColumn(
            "Table",
            width="medium",
        )

    if "status" in df.columns:
        config["status"] = st.column_config.TextColumn(
            "Status",
            width="small",
        )

    if "csv_rows" in df.columns:
        config["csv_rows"] = st.column_config.TextColumn(
            "CSV rows",
            width="small",
            help="Number of records in the source CSV file.",
        )

    if "staged_rows" in df.columns:
        config["staged_rows"] = st.column_config.TextColumn(
            "Staged rows",
            width="small",
            help="Number of records loaded into staging.",
        )

    if "control_column" in df.columns:
        config["control_column"] = st.column_config.TextColumn(
            "Control column",
            width="medium",
        )

    if "csv_control" in df.columns:
        config["csv_control"] = st.column_config.NumberColumn(
            "CSV control",
            width="medium",
            format="localized",
        )

    if "staged_control" in df.columns:
        config["staged_control"] = st.column_config.NumberColumn(
            "Staged control",
            width="medium",
            format="localized",
        )

    if "sha256" in df.columns:
        config["sha256"] = st.column_config.TextColumn(
            "SHA-256",
            width="medium",
        )

    if "message" in df.columns:
        config["message"] = st.column_config.TextColumn(
            "Message",
            width="medium",
        )

    if "finished_at" in df.columns:
        config["finished_at"] = st.column_config.TextColumn(
            "Finished at",
            width="medium",
        )

    return config


# ---------------------------------------------------------------------
# Main operations tabs
# ---------------------------------------------------------------------

tab_run, tab_recon, tab_staging, tab_audit = st.tabs(
    [
        "Run ETL",
        "Reconciliation",
        "Staging Loads & Rejects",
        "Audit & Counts",
    ]
)


# =====================================================================
# 1. RUN ETL
# =====================================================================

with tab_run:

    st.subheader("ETL pipeline execution")

    st.caption(
        "Transfer and transform operational records into the analytical data warehouse."
    )

    st.markdown(
        """
        **ETL execution details**

        - Source: `hr_oltp`
        - Destination: `hr_dw`
        - Procedure: `hr_dw.sp_run_full_etl()`
        - Execution: Idempotent
        """
    )

    st.info(
        "The pipeline loads new or changed records. "
        "Repeated execution should not duplicate previously loaded data."
    )

    if st.button(
        "Run ETL now",
        type="primary",
        use_container_width=True,
    ):

        with st.spinner(
            "Loading dimensions and facts, then reconciling..."
        ):

            out = run(
                lambda: get("etl").run_full_etl()
            )

        if out is not None:

            st.success("ETL run finished.")

            st.markdown("**ETL execution steps**")

            st.dataframe(
                out["steps"],
                hide_index=True,
                use_container_width=True,
            )

            st.divider()

            st.markdown("**Post-ETL reconciliation**")

            show_reconciliation(
                out["reconciliation"]
            )

            st.cache_data.clear()


# =====================================================================
# 2. RECONCILIATION
# =====================================================================

with tab_recon:

    st.subheader("Data quality and reconciliation")

    st.caption(
        "Verify data consistency across the ingestion, operational and analytical database layers."
    )

    st.markdown(
        """
        **Validation layers**

        1. CSV → Staging
        2. Staging → OLTP
        3. OLTP → Warehouse
        4. Warehouse integrity and SCD Type 2 rules
        """
    )

    st.info(
        "Reconciliation checks validate data consistency "
        "without intentionally modifying business records."
    )

    if st.button(
        "Run reconciliation now",
        type="primary",
    ):

        with st.spinner("Running reconciliation checks..."):

            df = run(
                lambda: get("recon").run()
            )

        show_reconciliation(df)

    st.divider()

    st.markdown("**Recent reconciliation runs**")

    runs = run(
        lambda: get("recon").runs(20)
    )

    if runs is not None and not runs.empty:

        st.dataframe(
            runs,
            hide_index=True,
            use_container_width=True,
        )

        chosen = st.selectbox(
            "Select a reconciliation run",
            runs["run_id"].tolist(),
            format_func=lambda r: (
                f"{str(r)[:8]}… · "
                f"{runs.set_index('run_id').loc[r, 'checked_at']}"
            ),
        )

        st.markdown("**Selected run results**")

        show_reconciliation(
            run(
                lambda: get("recon").results(chosen)
            )
        )

    elif runs is not None:

        st.info(
            "No previous reconciliation runs are available."
        )


# =====================================================================
# 3. STAGING LOADS AND REJECTS
# =====================================================================

with tab_staging:

    st.subheader("Staging load history")

    st.caption(
        "Monitor CSV ingestion batches, file checksums, loaded records and staging control totals."
    )

    st.markdown(
        """
        Previously loaded files are identified using their SHA-256
        checksum. Files already marked as LOADED are skipped
        during subsequent ingestion attempts.
        """
    )

    batches = run(
        lambda: get("recon").load_batches(30)
    )

    if batches is not None:

        if batches.empty:

            st.info("No staging load batches found.")

        else:

            st.markdown("**Recent staging batches**")

            st.caption(
                f"Displaying {len(batches):,} recent staging load records."
            )

            display_batches = prepare_staging_display(
                batches
            )

            st.dataframe(
                display_batches,
                column_config=staging_column_config(
                    display_batches
                ),
                hide_index=True,
                use_container_width=True,
                height=420,
            )

            st.caption(
                "Use horizontal scrolling to inspect all batch details, "
                "including checksums, control totals and timestamps."
            )

    st.divider()

    st.subheader("Rejected records")

    st.caption(
        "Summary of records rejected during the latest staging-to-OLTP load."
    )

    rej = run(
        lambda: get("recon").rejects_summary()
    )

    if rej is not None and rej.empty:

        st.success(
            "No rejected records were found."
        )

    elif rej is not None:

        st.dataframe(
            rej,
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            "The full rejection records are available in "
            "`hr_staging.stg_rejects`."
        )


# =====================================================================
# 4. AUDIT AND COUNTS
# =====================================================================

with tab_audit:

    st.subheader("Database and warehouse monitoring")

    st.caption(
        "Inspect database table volumes, historical employee versions "
        "and ETL execution records."
    )

    c1, c2 = st.columns([2, 3])

    with c1:

        st.markdown("**Database table counts**")

        counts = run(
            lambda: get("etl").table_counts()
        )

        if counts is not None:

            st.dataframe(
                counts,
                hide_index=True,
                use_container_width=True,
            )

    with c2:

        st.markdown("**SCD Type 2 employee versions**")

        scd = run(
            lambda: get("analytics").scd2_summary()
        )

        if scd is not None:

            st.dataframe(
                scd,
                hide_index=True,
                use_container_width=True,
            )

    st.divider()

    st.markdown("**ETL audit log**")

    audit = run(
        lambda: get("etl").audit_log(50)
    )

    if audit is not None:

        if audit.empty:

            st.info("No ETL audit records found.")

        else:

            st.dataframe(
                audit,
                hide_index=True,
                use_container_width=True,
            )
