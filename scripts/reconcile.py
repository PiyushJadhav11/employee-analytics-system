"""
Run the reconciliation checks on their own, at any time (read-only apart from the log).

    python scripts/reconcile.py                      # all layers
    python scripts/reconcile.py --layer OLTP_DW      # STAGING_OLTP | OLTP_DW (OLTP_DW includes DW_INTEGRITY)

Exit code 1 if any check FAILs, so it can gate a CI job or a cron run.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hr_analytics.etl import log_checks  # noqa: E402
from hr_analytics.managers import ManagerError, ReconciliationManager  # noqa: E402
from hr_analytics.models import ValidationError  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--layer", choices=ReconciliationManager.LAYERS)
    args = p.parse_args()
    try:
        df = ReconciliationManager().run(layer=args.layer)
    except (ManagerError, ValidationError) as exc:
        logging.error("%s", exc)
        return 1
    fails, warns = log_checks(df.to_dict("records"))
    logging.info("Run %s: %d checks, %d failed, %d warnings",
                 df["run_id"].iloc[0] if not df.empty else "?", len(df), fails, warns)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
