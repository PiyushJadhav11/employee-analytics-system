import streamlit as st

from app_pages.common import get, run

st.title("ETL, reconciliation & data ops")


def status_style(df):
    colors = {"PASS": "#e7f5ec", "FAIL": "#fde2e2", "WARN": "#fff4d6", "SKIP": "#eeeeee", "INFO": "#eef3fb"}
    return df.style.apply(lambda r: [f"background-color: {colors.get(r['status'], '')}" for _ in r], axis=1)


def show_reconciliation(df) -> None:
    if df is None or df.empty:
        st.info("No reconciliation results yet.")
        return
    counts = df["status"].value_counts()
    c = st.columns(4)
    c[0].metric("Checks", len(df))
    c[1].metric("Passed", int(counts.get("PASS", 0)))
    c[2].metric("Failed", int(counts.get("FAIL", 0)))
    c[3].metric("Warnings", int(counts.get("WARN", 0)))
    if counts.get("FAIL", 0):
        st.error("Some checks failed — the layers do not agree. See the red rows.")
    cols = [c for c in ["layer", "check_name", "expected_value", "actual_value", "status", "details"] if c in df]
    st.dataframe(status_style(df[cols]), hide_index=True, use_container_width=True)


tab_run, tab_recon, tab_staging, tab_audit = st.tabs(
    ["Run ETL", "Reconciliation", "Staging loads & rejects", "Audit log & counts"])

with tab_run:
    st.markdown("Run the full OLTP → warehouse load (`CALL hr_dw.sp_run_full_etl()`). "
                "It is **idempotent**: only new or changed rows are written, so running it twice in a row "
                "writes 0 rows the second time. A lock prevents two loads running at once. "
                "Every run ends with a full reconciliation.")
    if st.button("Run ETL now", type="primary"):
        with st.spinner("Loading dimensions and facts, then reconciling…"):
            out = run(lambda: get("etl").run_full_etl())
        if out is not None:
            st.success("ETL run finished.")
            st.dataframe(out["steps"], hide_index=True)
            show_reconciliation(out["reconciliation"])
            st.cache_data.clear()

with tab_recon:
    st.markdown("Each layer is checked against the one before it: **CSV → staging** (written by "
                "`load_staging.py`), **staging → OLTP**, **OLTP → warehouse**, and **warehouse integrity** "
                "(SCD2 rules). Read-only, safe to run any time.")
    if st.button("Run reconciliation now"):
        with st.spinner("Reconciling…"):
            df = run(lambda: get("recon").run())
        show_reconciliation(df)
    runs = run(lambda: get("recon").runs(20))
    if runs is not None and not runs.empty:
        st.subheader("Recent runs")
        st.dataframe(runs, hide_index=True, use_container_width=True)
        chosen = st.selectbox("Show run", runs["run_id"].tolist(),
                              format_func=lambda r: f"{r[:8]}… · {runs.set_index('run_id').loc[r, 'checked_at']}")
        show_reconciliation(run(lambda: get("recon").results(chosen)))

with tab_staging:
    st.markdown("Every CSV load attempt, with the file's sha256 and the CSV-vs-table row count and control "
                "total. A file whose checksum is already **LOADED** is **SKIPPED** on re-runs.")
    st.dataframe(run(lambda: get("recon").load_batches(30)), hide_index=True, use_container_width=True)
    st.subheader("Rejected rows (latest staging → OLTP load)")
    rej = run(lambda: get("recon").rejects_summary())
    if rej is not None and rej.empty:
        st.success("No rows were rejected.")
    elif rej is not None:
        st.dataframe(rej, hide_index=True)
        st.caption("Full list: `SELECT * FROM hr_staging.stg_rejects;`")

with tab_audit:
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("**Row counts** (exact `COUNT(*)`)")
        st.dataframe(run(lambda: get("etl").table_counts()), hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**SCD Type 2 versions in dim_employee**")
        st.dataframe(run(lambda: get("analytics").scd2_summary()), hide_index=True)
    st.markdown("**ETL audit log**")
    st.dataframe(run(lambda: get("etl").audit_log(50)), hide_index=True, use_container_width=True)
