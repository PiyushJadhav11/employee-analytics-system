"""
Python side of the ETL: running .sql files and loading CSVs into staging.

    SqlScriptRunner   executes a .sql file, honouring MySQL Workbench's DELIMITER $$ syntax
    StagingLoader     loads data/synthetic/*.csv into hr_staging — idempotent and reconciled
    CheckResult       one reconciliation check, written to hr_dw.reconciliation_log
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from hr_analytics.db_manager import DatabaseConnection, DatabaseError

log = logging.getLogger(__name__)

MANIFEST_NAME = "_manifest.json"


class SqlScriptRunner(DatabaseConnection):
    """The mysql driver runs one statement at a time and knows nothing about DELIMITER,
    which is a client-side directive. This splits a script the way the mysql CLI does."""

    _DELIM_RE = re.compile(r"^\s*DELIMITER\s+(\S+)\s*$", re.IGNORECASE)

    @classmethod
    def split(cls, script: str) -> list[str]:
        statements, buf, delim = [], [], ";"
        for line in script.splitlines():
            m = cls._DELIM_RE.match(line)
            if m:
                delim = m.group(1)
                continue
            if line.strip().startswith("--") and not buf:
                continue
            buf.append(line)
            joined = "\n".join(buf).rstrip()
            if joined.endswith(delim):
                stmt = joined[: -len(delim)].strip()
                if stmt and not cls._only_comments(stmt):
                    statements.append(stmt)
                buf = []
        tail = "\n".join(buf).strip()
        if tail and not cls._only_comments(tail):
            statements.append(tail)
        return statements

    @staticmethod
    def _only_comments(text: str) -> bool:
        return all(line.strip().startswith("--") or not line.strip() for line in text.splitlines())

    def run_file(self, path: Path) -> int:
        statements = self.split(path.read_text(encoding="utf-8"))
        with self.connection() as conn:
            cur = conn.cursor()
            try:
                for stmt in statements:
                    try:
                        cur.execute(stmt)
                        if cur.with_rows:
                            cur.fetchall()
                    except Exception as exc:
                        first_line = stmt.strip().splitlines()[0][:100]
                        raise DatabaseError(f"{path.name}: failed at `{first_line}` — {exc}") from exc
            finally:
                cur.close()
        log.info("  %-28s %3d statements", path.name, len(statements))
        return len(statements)

    def run_sql(self, sql: str) -> None:
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            cur.close()


# --------------------------------------------------------------------------- reconciliation records
@dataclass
class CheckResult:
    layer: str
    check_name: str
    expected: Decimal | int | None
    actual: Decimal | int | None
    status: str          # PASS | FAIL | WARN | INFO | SKIP
    details: str | None = None

    @classmethod
    def compare(cls, layer: str, name: str, expected, actual, on_mismatch: str = "FAIL",
                details: str | None = None) -> "CheckResult":
        same = expected is not None and actual is not None and Decimal(str(expected)) == Decimal(str(actual))
        return cls(layer, name, expected, actual, "PASS" if same else on_mismatch, details)


class ManifestError(RuntimeError):
    """The CSVs on disk are not the set the synthesizer published."""


class StagingLoadError(RuntimeError):
    """A staging table could not be replaced; its previous contents are unchanged."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- staging loader
class StagingLoader(DatabaseConnection):
    """Loads the synthesized CSVs into hr_staging.

    Idempotent:
      * Each table is replaced inside ONE transaction (DELETE + batched INSERT,
        not TRUNCATE, which would commit immediately). A failure half-way leaves
        the previous contents intact instead of a half-loaded table.
      * Every attempt is recorded in hr_staging.load_batches with the file's
        sha256. If the same file is already LOADED and the table still holds
        exactly that many rows, the table is skipped (use force=True to reload).

    Reconciled (layer CSV_STAGING in hr_dw.reconciliation_log):
      * file checksum matches the synthesizer's _manifest.json
      * CSV row count = staged row count
      * CSV control total = staged control total (SUM of a numeric column)
      * distinct natural keys in staging = the manifest's expected count after de-duplication
    """

    TABLES = {  # csv name -> (staging table, control column, natural key, manifest expected key)
        "departments": ("stg_departments", None, "department_code", "departments"),
        "job_roles": ("stg_job_roles", None, "department, job_role", "job_roles"),
        "employees": ("stg_employees", "monthly_income", "employee_number", "employees"),
        "employee_history": ("stg_employee_history", "monthly_income", "employee_number, effective_start",
                             "employee_history"),
        "projects": ("stg_projects", "budget", "project_code", "projects"),
        "assignments": ("stg_assignments", "allocation_pct", "employee_number, project_code, start_date",
                        "assignments"),
        "reviews": ("stg_reviews", "performance_score", "review_id", "reviews"),
    }
    LAYER = "CSV_STAGING"

    def __init__(self, data_dir: Path, batch_size: int = 5_000) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.batch_size = batch_size

    # ------------------------------------------------------------------ public
    def load_all(self, run_id: str, force: bool = False, require_manifest: bool = True) -> list[CheckResult]:
        checks: list[CheckResult] = []
        missing = [n for n in self.TABLES if not (self.data_dir / f"{n}.csv").exists()]
        if missing:
            raise FileNotFoundError(f"Missing CSVs in {self.data_dir}: {missing}. Run scripts/data_synthesizer.py first.")

        manifest = self._read_manifest(require_manifest)
        checks += self._verify_checksums(manifest)
        if any(c.status == "FAIL" for c in checks):
            self.record(run_id, checks)
            raise ManifestError("CSV files do not match _manifest.json (edited, truncated or from another run). "
                                "Re-run scripts/data_synthesizer.py. Nothing was loaded.")

        for name, (table, control_col, key, expected_key) in self.TABLES.items():
            path = self.data_dir / f"{name}.csv"
            sha = manifest["files"][name]["sha256"] if manifest else sha256_file(path)
            checks += self._load_table(run_id, path, table, control_col, sha, force)
            expected = (manifest or {}).get("expected_after_dedup", {}).get(expected_key)
            distinct = self.fetch_one(f"SELECT COUNT(DISTINCT {key}) AS n FROM hr_staging.{table}")["n"]
            checks.append(
                CheckResult.compare(self.LAYER, f"{name}: distinct keys = manifest expected", expected, distinct,
                                    details=f"COUNT(DISTINCT {key})")
                if expected is not None else
                CheckResult(self.LAYER, f"{name}: distinct keys = manifest expected", None, distinct, "SKIP",
                            "no manifest"))
        self.record(run_id, checks)
        return checks

    def record(self, run_id: str, checks: list[CheckResult]) -> None:
        if not checks:
            return
        with self.transaction() as cur:
            cur.executemany(
                """INSERT INTO hr_dw.reconciliation_log
                   (run_id, layer, check_name, expected_value, actual_value, status, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                [(run_id, c.layer, c.check_name, c.expected, c.actual, c.status, c.details) for c in checks])

    # ------------------------------------------------------------------ manifest
    def _read_manifest(self, required: bool) -> dict | None:
        path = self.data_dir / MANIFEST_NAME
        if not path.exists():
            if required:
                raise ManifestError(f"{path} not found. Re-run scripts/data_synthesizer.py, or pass "
                                    "--no-manifest to load hand-supplied CSVs without checksum checks.")
            log.warning("No manifest — loading without checksum or expected-count reconciliation")
            return None
        return json.loads(path.read_text())

    def _verify_checksums(self, manifest: dict | None) -> list[CheckResult]:
        if manifest is None:
            return [CheckResult(self.LAYER, "files match manifest", None, None, "SKIP", "no manifest")]
        out = []
        for name in self.TABLES:
            meta = manifest["files"].get(name)
            actual = sha256_file(self.data_dir / f"{name}.csv")
            ok = meta is not None and meta["sha256"] == actual
            out.append(CheckResult(self.LAYER, f"{name}: file sha256 = manifest", None, None,
                                   "PASS" if ok else "FAIL", f"sha256 {actual[:12]}…"))
        return out

    # ------------------------------------------------------------------ one table
    def _load_table(self, run_id: str, path: Path, table: str, control_col: str | None, sha: str,
                    force: bool) -> list[CheckResult]:
        started = datetime.now()
        name = path.stem
        last = self.fetch_one(
            """SELECT file_sha256, csv_rows, csv_control FROM hr_staging.load_batches
               WHERE table_name = %s AND status = 'LOADED' ORDER BY batch_id DESC LIMIT 1""", (table,))
        current_rows = self.fetch_one(f"SELECT COUNT(*) AS n FROM hr_staging.{table}")["n"]

        if not force and last and last["file_sha256"] == sha and current_rows == last["csv_rows"]:
            csv_rows, csv_control, status, msg = last["csv_rows"], last["csv_control"], "SKIPPED", "already loaded"
            log.info("  %-22s %10s rows  skipped (same file already loaded)", table, f"{csv_rows:,}")
        else:
            t0 = time.perf_counter()
            csv_rows, csv_control = 0, None
            try:
                df = pd.read_csv(path, keep_default_na=True, low_memory=False)
                csv_rows = len(df)
                csv_control = (sum((Decimal(str(v)) for v in df[control_col].dropna()), Decimal(0))
                               if control_col else None)
                self._replace_table(table, df)
            except Exception as exc:
                self._record_batch(run_id, table, path, sha, csv_rows, current_rows, control_col, csv_control,
                                   None, "FAILED", f"{type(exc).__name__}: {exc}"[:255], started)
                raise StagingLoadError(f"Loading {path.name} into hr_staging.{table} failed "
                                       f"({type(exc).__name__}: {str(exc)[:150]}). The table still holds its "
                                       f"previous {current_rows:,} rows.") from exc
            status, msg = "LOADED", None
            log.info("  %-22s %10s rows  %5.1fs", table, f"{csv_rows:,}", time.perf_counter() - t0)

        staged = self.fetch_one(
            f"SELECT COUNT(*) AS n{', SUM(`' + control_col + '`) AS s' if control_col else ''} FROM hr_staging.{table}")
        staged_rows, staged_control = staged["n"], staged.get("s")
        mismatch = staged_rows != csv_rows or (control_col and Decimal(str(staged_control)) != Decimal(str(csv_control)))
        if mismatch and status == "LOADED":
            status, msg = "MISMATCH", "staged rows or control total differ from the CSV"
        self._record_batch(run_id, table, path, sha, csv_rows, staged_rows, control_col, csv_control,
                           staged_control, status, msg, started)

        checks = [CheckResult.compare(self.LAYER, f"{name}: CSV rows = staged rows", csv_rows, staged_rows,
                                      details=f"batch {status.lower()}")]
        if control_col:
            checks.append(CheckResult.compare(self.LAYER, f"{name}: control total {control_col}",
                                              csv_control, staged_control))
        return checks

    def _replace_table(self, table: str, df: pd.DataFrame) -> None:
        df = df.astype(object).where(pd.notna(df), None)  # NaN -> NULL
        cols = ", ".join(f"`{c}`" for c in df.columns)
        sql = f"INSERT INTO hr_staging.{table} ({cols}) VALUES ({', '.join(['%s'] * len(df.columns))})"
        rows = [tuple(self._py(v) for v in r) for r in df.itertuples(index=False, name=None)]
        with self.connection() as conn:  # one transaction: old rows stay until the new ones commit
            cur = conn.cursor()
            cur.execute(f"DELETE FROM hr_staging.{table}")
            for i in range(0, len(rows), self.batch_size):
                cur.executemany(sql, rows[i: i + self.batch_size])
            cur.close()

    def _record_batch(self, run_id, table, path, sha, csv_rows, staged_rows, control_col, csv_control,
                      staged_control, status, message, started) -> None:
        self.execute(
            """INSERT INTO hr_staging.load_batches
               (run_id, table_name, file_name, file_sha256, csv_rows, staged_rows, control_column,
                csv_control, staged_control, status, message, started_at, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(3))""",
            (run_id, table, path.name, sha, csv_rows, staged_rows, control_col, csv_control, staged_control,
             status, message, started))

    @staticmethod
    def _py(v):
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            return float(v)
        return v


def log_checks(rows, logger: logging.Logger = log) -> tuple[int, int]:
    """Log reconciliation rows (CheckResults or dicts/DataFrame rows); return (fails, warnings)."""
    fails = warns = 0
    for r in rows:
        get = (lambda k: getattr(r, {"check_name": "check_name", "expected_value": "expected",
                                     "actual_value": "actual"}.get(k, k))) if isinstance(r, CheckResult) else r.get
        status = get("status")
        fails += status == "FAIL"
        warns += status == "WARN"
        exp, act = get("expected_value"), get("actual_value")
        level = logging.ERROR if status == "FAIL" else logging.WARNING if status == "WARN" else logging.INFO
        logger.log(level, "  [%-4s] %-13s %-52s expected=%-16s actual=%s", status, get("layer"),
                   get("check_name"), _fmt(exp), _fmt(act))
    return fails, warns


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    d = Decimal(str(v))
    return f"{d:,.0f}" if d == d.to_integral_value() else f"{d:,.2f}"
