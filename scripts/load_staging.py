"""
Step 3 — load the synthesized CSVs into hr_staging, clean them into hr_oltp,
and reconcile both hops.

    python scripts/load_staging.py                   # CSVs -> staging -> OLTP, reconciled
    python scripts/load_staging.py --staging-only    # stop after staging (inspect it in Workbench)
    python scripts/load_staging.py --force           # reload staging even if the files were already loaded
    python scripts/load_staging.py --no-manifest     # hand-supplied CSVs without _manifest.json

Safe to re-run: unchanged files are skipped, each table is replaced atomically,
and the OLTP load only inserts keys it does not have yet.
Exit code 1 if any reconciliation check FAILs.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_analytics.db_manager import DatabaseConnection, DatabaseError  # noqa: E402
from hr_analytics.etl import ManifestError, StagingLoader, StagingLoadError, log_checks  # noqa: E402
from hr_analytics.managers import ManagerError, ReconciliationManager  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=ROOT / "data" / "synthetic")
    p.add_argument("--staging-only", action="store_true")
    p.add_argument("--force", action="store_true", help="reload files even if already loaded")
    p.add_argument("--no-manifest", action="store_true", help="allow CSVs without _manifest.json")
    args = p.parse_args()

    run_id = str(uuid.uuid4())
    try:
        t0 = time.perf_counter()
        logging.info("Run %s — loading CSVs from %s into hr_staging", run_id, args.data_dir)
        checks = StagingLoader(args.data_dir).load_all(run_id, force=args.force,
                                                      require_manifest=not args.no_manifest)
        logging.info("Reconciliation CSV -> staging:")
        fails, _ = log_checks(checks)
        if fails:
            logging.error("%d CSV -> staging check(s) failed; not loading OLTP.", fails)
            return 1
        if args.staging_only:
            return 0

        logging.info("Cleaning staging into hr_oltp (CALL hr_oltp.sp_load_from_staging) ...")
        results = DatabaseConnection().call_procedure("hr_oltp.sp_load_from_staging")
        for row in results[-1]:
            logging.info("  %-20s %10s rows", row["table_name"], f"{row['row_count']:,}")

        logging.info("Reconciliation staging -> OLTP:")
        recon = ReconciliationManager().run(layer="STAGING_OLTP", run_id=run_id)
        fails, warns = log_checks(recon[recon["layer"] != "CSV_STAGING"].to_dict("records"))
        logging.info("Done in %.1fs — run %s: %d failed, %d warnings. Next: python scripts/run_etl.py",
                     time.perf_counter() - t0, run_id, fails, warns)
        return 1 if fails else 0
    except (DatabaseError, ManagerError, ManifestError, StagingLoadError, FileNotFoundError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
