"""
Step 2 — create the three schemas, all tables, stored procedures and views.

    python scripts/setup_database.py            # safe to re-run: creates what is missing, keeps data
    python scripts/setup_database.py --only 06  # re-run one file (e.g. after editing a procedure)
    python scripts/setup_database.py --reset    # DROP hr_staging, hr_oltp and hr_dw first (asks to confirm)

Idempotent by default: tables use CREATE TABLE IF NOT EXISTS, procedures are
dropped and recreated, views use CREATE OR REPLACE. Only --reset deletes data.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_analytics.db_manager import DatabaseError  # noqa: E402
from hr_analytics.etl import SqlScriptRunner  # noqa: E402

SCHEMAS = ("hr_staging", "hr_oltp", "hr_dw")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="run only the sql file whose name starts with this prefix, e.g. 06")
    p.add_argument("--reset", action="store_true", help="drop and recreate all three schemas (deletes ALL data)")
    p.add_argument("--yes", action="store_true", help="skip the --reset confirmation prompt")
    args = p.parse_args()

    files = sorted((ROOT / "sql").glob("[0-9][0-9]_*.sql"))
    if args.only:
        files = [f for f in files if f.name.startswith(args.only)]
    try:
        runner = SqlScriptRunner()
        if args.reset:
            if not args.yes:
                answer = input(f"This permanently deletes {', '.join(SCHEMAS)} and all their data. "
                               "Type RESET to continue: ")
                if answer.strip() != "RESET":
                    logging.info("Cancelled; nothing was dropped.")
                    return 1
            for schema in SCHEMAS:
                runner.run_sql(f"DROP DATABASE IF EXISTS {schema}")
            logging.warning("Dropped %s", ", ".join(SCHEMAS))
        logging.info("Running %d SQL file(s)", len(files))
        for f in files:
            runner.run_file(f)
    except DatabaseError as exc:
        logging.error("%s", exc)
        return 1
    logging.info("Database objects are in place. Next: python scripts/load_staging.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
