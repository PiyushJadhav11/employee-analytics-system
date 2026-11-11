"""
Step 4 — load the star schema from OLTP (CALL hr_dw.sp_run_full_etl), then
reconcile every layer.

Safe to re-run: dimensions upsert, dim_employee applies SCD2 only to changed
employees, and the fact table only inserts reviews it has not seen — a second
run writes 0 rows. A named lock stops two loads from running at once.
Exit code 1 if any reconciliation check FAILs.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_analytics.etl import log_checks  # noqa: E402
from hr_analytics.managers import EtlManager, ManagerError  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    try:
        t0 = time.perf_counter()
        logging.info("Running hr_dw.sp_run_full_etl ...")
        out = EtlManager().run_full_etl()
        steps = out["steps"]
        for _, s in steps.iterrows():
            logging.info("  %-26s %10s rows  %6.2fs", s["step_name"], f"{int(s['rows_affected'] or 0):,}", float(s["seconds"]))
        logging.info("Reconciliation (all layers):")
        fails, warns = log_checks(out["reconciliation"].to_dict("records"))
        run_id = steps["run_id"].iloc[0] if not steps.empty else "?"
        logging.info("ETL finished in %.1fs — run %s: %d failed, %d warnings. Next: streamlit run streamlit_app.py",
                     time.perf_counter() - t0, run_id, fails, warns)
        return 1 if fails else 0
    except ManagerError as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
