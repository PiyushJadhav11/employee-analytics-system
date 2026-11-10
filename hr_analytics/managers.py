"""
Data Access Layer. Every manager inherits DatabaseConnection, so it gets the
shared pool and the query helpers, and is itself a singleton.

    BaseManager         error handling shared by all managers
    LookupManager       departments, roles, employee search
    EmployeeManager     onboarding, department transfers / promotions (SCD2), terminations
    ProjectManager      projects and assignments, bottleneck query
    ReviewManager       performance reviews
    AnalyticsManager    read-only queries against the star schema (hr_dw)
    EtlManager          runs the warehouse load and reads its audit log
    ReconciliationManager  runs/reads the layer-by-layer reconciliation checks

Every write method is idempotent: it accepts a request_key (stored in
hr_oltp.idempotency_keys in the same transaction as the write) and, where the
data has a natural key, also treats an exact repeat as a no-op. A retry or a
double-click therefore returns the original result instead of writing twice.

Write paths keep the warehouse in step with OLTP: after an OLTP change commits,
the manager calls the matching hr_dw procedure for just that employee. If that
sync fails the OLTP change still stands, and the next full ETL run picks it up.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, TypeVar

import pandas as pd

from mysql.connector import errors as mysql_errors

from hr_analytics.db_manager import DatabaseConnection, DatabaseError, to_numeric_frame
from hr_analytics.models import Employee, Project, Review, ValidationError

log = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


class ManagerError(RuntimeError):
    """A failed business operation, with a message fit for the UI."""


def handles_errors(action: str) -> Callable[[F], F]:
    """Turn any failure inside a manager method into a ManagerError naming the action.

    ValidationError passes through untouched: it is already a user-facing message
    about the input, not a system failure.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except (ValidationError, ManagerError):
                raise
            except DatabaseError as exc:
                raise ManagerError(f"Could not {action}: {exc}") from exc
            except Exception as exc:  # unexpected: log the traceback, show a short message
                log.exception("Unexpected error while trying to %s", action)
                raise ManagerError(f"Could not {action}: unexpected {type(exc).__name__}: {exc}") from exc
        return wrapper  # type: ignore[return-value]
    return decorator


@dataclass
class WriteResult:
    id: int
    dw_synced: bool
    message: str = ""
    replayed: bool = False   # True when this request had already been applied; nothing new was written


class BaseManager(DatabaseConnection):
    def _sync_dw(self, procedure: str, *args: Any) -> bool:
        try:
            self.call_procedure(procedure, args)
            return True
        except DatabaseError:
            log.exception("Warehouse sync via %s failed; the next full ETL will catch up", procedure)
            return False

    # ------------------------------------------------------------------ idempotency keys
    @staticmethod
    def _claim_request(cur: Any, request_key: str | None, operation: str) -> dict | None:
        """Claim an idempotency key inside the caller's transaction.

        Returns None the first time (the caller goes ahead and writes). If the key
        was already used, returns the stored row so the caller can return the
        original result without writing anything.

        Inserting first (rather than SELECT-then-INSERT) is what makes concurrent
        retries safe: the second INSERT waits on the primary-key lock until the
        first transaction commits, then fails with a duplicate key and reads the
        committed result. If the first transaction rolls back, its key disappears
        with it and the retry proceeds normally.
        """
        if not request_key:
            return None
        try:
            cur.execute("INSERT INTO hr_oltp.idempotency_keys (request_key, operation) VALUES (%s, %s)",
                        (request_key, operation))
            return None
        except mysql_errors.IntegrityError as exc:
            if exc.errno != 1062:
                raise
        cur.execute("SELECT operation, entity_id, response FROM hr_oltp.idempotency_keys WHERE request_key = %s",
                    (request_key,))
        row = cur.fetchone()
        if row["operation"] != operation:
            raise ValidationError("This request key was already used for a different operation.")
        return row

    @staticmethod
    def _complete_request(cur: Any, request_key: str | None, entity_id: int | None, response: str) -> None:
        if request_key:
            cur.execute("UPDATE hr_oltp.idempotency_keys SET entity_id = %s, response = %s WHERE request_key = %s",
                        (entity_id, response[:255], request_key))


# --------------------------------------------------------------------------- lookups
class LookupManager(BaseManager):
    @handles_errors("load departments")
    def departments(self) -> pd.DataFrame:
        return self.fetch_df("SELECT department_id, department_code, department_name "
                             "FROM hr_oltp.departments ORDER BY department_name")

    @handles_errors("load job roles")
    def roles(self, department_id: int | None = None) -> pd.DataFrame:
        sql = ("SELECT j.job_role_id, j.role_name, j.department_id, d.department_name "
               "FROM hr_oltp.job_roles j JOIN hr_oltp.departments d USING (department_id)")
        if department_id is None:
            return self.fetch_df(sql + " ORDER BY d.department_name, j.role_name")
        return self.fetch_df(sql + " WHERE j.department_id = %s ORDER BY j.role_name", (department_id,))

    @handles_errors("search employees")
    def search_employees(self, term: str = "", active_only: bool = True, limit: int = 50) -> pd.DataFrame:
        like = f"%{term.strip()}%"
        sql = """
            SELECT e.employee_id, e.employee_number, CONCAT(e.first_name, ' ', e.last_name) AS full_name,
                   e.email, d.department_name, j.role_name AS job_role, e.job_level, e.monthly_income,
                   e.hire_date, e.termination_date
            FROM hr_oltp.employees e
            JOIN hr_oltp.departments d ON d.department_id = e.department_id
            JOIN hr_oltp.job_roles   j ON j.job_role_id   = e.job_role_id
            WHERE (CAST(e.employee_number AS CHAR) LIKE %s OR e.email LIKE %s
                   OR CONCAT(e.first_name, ' ', e.last_name) LIKE %s)
        """
        if active_only:
            sql += " AND e.termination_date IS NULL"
        sql += " ORDER BY e.employee_number DESC LIMIT %s"
        return self.fetch_df(sql, (like, like, like, int(limit)))


# --------------------------------------------------------------------------- employees
class EmployeeManager(BaseManager):
    @handles_errors("onboard the employee")
    def onboard(self, emp: Employee, engagement: dict[str, int] | None = None,
                request_key: str | None = None) -> WriteResult:
        """Insert the employee, their first engagement survey and their first history
        version ('HIRE') in one transaction, then push the new version to dim_employee.

        Idempotent twice over: by request_key (double-submits), and by email — the
        same person (same email, birth date and hire date) is never onboarded twice."""
        engagement = engagement or {}
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "onboard")
            if prior:
                result = WriteResult(prior["entity_id"], False, prior["response"], replayed=True)
            else:
                cur.execute("""SELECT employee_id, employee_number, date_of_birth, hire_date
                               FROM hr_oltp.employees WHERE email = %s""", (emp.email,))
                existing = cur.fetchone()
                if existing:
                    if existing["date_of_birth"] != emp.date_of_birth or existing["hire_date"] != emp.hire_date:
                        raise ValidationError(f"{emp.email} already belongs to employee "
                                              f"#{existing['employee_number']}.")
                    msg = f"Employee #{existing['employee_number']} was already onboarded; nothing changed."
                    self._complete_request(cur, request_key, existing["employee_id"], msg)
                    result = WriteResult(existing["employee_id"], False, msg, replayed=True)
                else:
                    self._assert_role_in_department(cur, emp.job_role_id, emp.department_id)
                    if emp.employee_number is None:
                        cur.execute("SELECT COALESCE(MAX(employee_number), 100000) + 1 AS n FROM hr_oltp.employees")
                        emp.employee_number = int(cur.fetchone()["n"])
                    rec = emp.to_record()
                    cur.execute(f"INSERT INTO hr_oltp.employees ({', '.join(rec)}) "
                                f"VALUES ({', '.join(['%s'] * len(rec))})", tuple(rec.values()))
                    emp.employee_id = cur.lastrowid
                    cur.execute(
                        """INSERT INTO hr_oltp.employee_engagement
                           (employee_id, environment_satisfaction, job_satisfaction, relationship_satisfaction,
                            work_life_balance, job_involvement, surveyed_on)
                           VALUES (%s, %s, %s, %s, %s, %s, CURDATE())""",
                        (emp.employee_id, engagement.get("environment_satisfaction", 3),
                         engagement.get("job_satisfaction", 3), engagement.get("relationship_satisfaction", 3),
                         engagement.get("work_life_balance", 3), engagement.get("job_involvement", 3)),
                    )
                    cur.execute(
                        """INSERT INTO hr_oltp.employee_history
                           (employee_id, department_id, job_role_id, job_level, monthly_income,
                            effective_start, effective_end, is_current, change_reason)
                           VALUES (%s, %s, %s, %s, %s, %s, '9999-12-31', TRUE, 'HIRE')""",
                        (emp.employee_id, emp.department_id, emp.job_role_id, emp.job_level,
                         emp.monthly_income, emp.hire_date),
                    )
                    msg = f"Employee #{emp.employee_number} {emp.full_name} onboarded."
                    self._complete_request(cur, request_key, emp.employee_id, msg)
                    result = WriteResult(emp.employee_id, False, msg)
        # Re-running the sync on a replay is safe (it is idempotent) and repairs a
        # warehouse that missed the first sync.
        result.dw_synced = self._sync_dw("hr_dw.sp_load_dim_employee", result.id)
        return result

    @handles_errors("load the employee")
    def get(self, employee_id: int) -> dict | None:
        return self.fetch_one(
            """SELECT e.*, d.department_name, j.role_name AS job_role
               FROM hr_oltp.employees e
               JOIN hr_oltp.departments d ON d.department_id = e.department_id
               JOIN hr_oltp.job_roles   j ON j.job_role_id   = e.job_role_id
               WHERE e.employee_id = %s""", (employee_id,))

    @handles_errors("change the employee's position")
    def change_position(
        self,
        employee_id: int,
        department_id: int,
        job_role_id: int,
        effective_date: date,
        reason: str = "DEPARTMENT_TRANSFER",
        job_level: int | None = None,
        monthly_income: float | None = None,
        request_key: str | None = None,
    ) -> WriteResult:
        """Department transfer, promotion or salary revision — the SCD Type 2 trigger.

        OLTP side: close the current employee_history row the day before
        effective_date, open a new one, and update employees. Then
        sp_load_dim_employee(employee_id) sees the Type 2 hash change and
        expires/inserts the matching dim_employee rows.

        Idempotent: a repeat of a change that is already the current version
        (same values, same effective date) is a no-op, with or without a request key.
        """
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "change_position")
            if prior:
                result = WriteResult(employee_id, False, prior["response"], replayed=True)
            else:
                cur.execute(
                    """SELECT history_id, department_id, job_role_id, job_level, monthly_income, effective_start
                       FROM hr_oltp.employee_history
                       WHERE employee_id = %s AND is_current = TRUE FOR UPDATE""", (employee_id,))
                current = cur.fetchone()
                if current is None:
                    raise ValidationError("Employee has no current history version.")
                new_level = int(job_level if job_level is not None else current["job_level"])
                new_income = round(float(monthly_income if monthly_income is not None
                                         else current["monthly_income"]), 2)
                same_values = (department_id == current["department_id"]
                               and job_role_id == current["job_role_id"]
                               and new_level == current["job_level"]
                               and new_income == round(float(current["monthly_income"]), 2))
                if same_values and effective_date == current["effective_start"]:
                    msg = f"This change is already in effect since {effective_date}; nothing changed."
                    self._complete_request(cur, request_key, employee_id, msg)
                    result = WriteResult(employee_id, False, msg, replayed=True)
                else:
                    cur.execute("SELECT termination_date FROM hr_oltp.employees WHERE employee_id = %s",
                                (employee_id,))
                    if (cur.fetchone() or {}).get("termination_date"):
                        raise ValidationError("Employee has left the company; their position cannot change.")
                    if same_values:
                        raise ValidationError("Nothing changed — pick a different department, role, level or salary.")
                    if effective_date <= current["effective_start"]:
                        raise ValidationError("Effective date must be after the current version's start "
                                              f"({current['effective_start']}).")
                    self._assert_role_in_department(cur, job_role_id, department_id)
                    if not 1 <= new_level <= 5:
                        raise ValidationError("Job level must be between 1 and 5.")
                    if new_income <= 0:
                        raise ValidationError("Monthly income must be positive.")

                    cur.execute("UPDATE hr_oltp.employee_history SET effective_end = %s, is_current = FALSE "
                                "WHERE history_id = %s",
                                (effective_date - timedelta(days=1), current["history_id"]))
                    cur.execute(
                        """INSERT INTO hr_oltp.employee_history
                           (employee_id, department_id, job_role_id, job_level, monthly_income,
                            effective_start, effective_end, is_current, change_reason)
                           VALUES (%s, %s, %s, %s, %s, %s, '9999-12-31', TRUE, %s)""",
                        (employee_id, department_id, job_role_id, new_level, new_income, effective_date, reason))
                    cur.execute(
                        """UPDATE hr_oltp.employees
                           SET department_id = %s, job_role_id = %s, job_level = %s, monthly_income = %s
                           WHERE employee_id = %s""",
                        (department_id, job_role_id, new_level, new_income, employee_id))
                    msg = f"Position updated, effective {effective_date}."
                    self._complete_request(cur, request_key, employee_id, msg)
                    result = WriteResult(employee_id, False, msg)
        result.dw_synced = self._sync_dw("hr_dw.sp_load_dim_employee", employee_id)
        return result

    @handles_errors("record the termination")
    def terminate(self, employee_id: int, termination_date: date, request_key: str | None = None) -> WriteResult:
        """Attrition is a Type 1 attribute: it is overwritten, not versioned.
        Recording the same exit date again is a no-op; a different date is refused."""
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "terminate")
            if prior:
                result = WriteResult(employee_id, False, prior["response"], replayed=True)
            else:
                cur.execute("SELECT hire_date, termination_date FROM hr_oltp.employees "
                            "WHERE employee_id = %s FOR UPDATE", (employee_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValidationError("Employee not found.")
                if row["termination_date"] == termination_date:
                    msg = f"Exit on {termination_date} was already recorded; nothing changed."
                    self._complete_request(cur, request_key, employee_id, msg)
                    result = WriteResult(employee_id, False, msg, replayed=True)
                elif row["termination_date"] is not None:
                    raise ValidationError(f"Employee already left on {row['termination_date']}.")
                elif termination_date < row["hire_date"]:
                    raise ValidationError("Exit date is before the hire date.")
                else:
                    cur.execute("UPDATE hr_oltp.employees SET termination_date = %s, attrition = TRUE "
                                "WHERE employee_id = %s", (termination_date, employee_id))
                    msg = "Termination recorded."
                    self._complete_request(cur, request_key, employee_id, msg)
                    result = WriteResult(employee_id, False, msg)
        result.dw_synced = self._sync_dw("hr_dw.sp_load_dim_employee", employee_id)
        return result

    @handles_errors("load the OLTP history")
    def oltp_history(self, employee_id: int) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT h.effective_start, h.effective_end, h.is_current, h.change_reason,
                      d.department_name, j.role_name AS job_role, h.job_level, h.monthly_income
               FROM hr_oltp.employee_history h
               JOIN hr_oltp.departments d ON d.department_id = h.department_id
               JOIN hr_oltp.job_roles   j ON j.job_role_id   = h.job_role_id
               WHERE h.employee_id = %s ORDER BY h.effective_start""", (employee_id,))

    @handles_errors("load the warehouse history")
    def dw_versions(self, employee_id: int) -> pd.DataFrame:
        """The SCD2 rows in dim_employee — what the warehouse believes, version by version."""
        return self.fetch_df(
            """SELECT employee_sk, version_no, department_name, job_role, job_level, monthly_income,
                      salary_band, start_date, end_date, is_current, change_reason
               FROM hr_dw.dim_employee WHERE employee_id = %s ORDER BY start_date""", (employee_id,))

    @staticmethod
    def _assert_role_in_department(cur: Any, job_role_id: int, department_id: int) -> None:
        cur.execute("SELECT 1 AS ok FROM hr_oltp.job_roles WHERE job_role_id = %s AND department_id = %s",
                    (job_role_id, department_id))
        if cur.fetchone() is None:
            raise ValidationError("That job role does not belong to the selected department.")


# --------------------------------------------------------------------------- projects
class ProjectManager(BaseManager):
    @handles_errors("create the project")
    def create(self, project: Project, request_key: str | None = None) -> WriteResult:
        """Idempotent on project_code: re-creating the same project returns the existing one;
        reusing a code for a different project is refused."""
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "create_project")
            if prior:
                result = WriteResult(prior["entity_id"], False, prior["response"], replayed=True)
            else:
                cur.execute("SELECT project_id, project_name, department_id FROM hr_oltp.projects "
                            "WHERE project_code = %s", (project.project_code,))
                existing = cur.fetchone()
                if existing and (existing["project_name"] != project.project_name
                                 or existing["department_id"] != project.department_id):
                    raise ValidationError(f"Project code {project.project_code} is already used by "
                                          f"'{existing['project_name']}'.")
                if existing:
                    msg = f"Project {project.project_code} already exists; nothing changed."
                    result = WriteResult(existing["project_id"], False, msg, replayed=True)
                else:
                    rec = project.to_record()
                    cur.execute(f"INSERT INTO hr_oltp.projects ({', '.join(rec)}) "
                                f"VALUES ({', '.join(['%s'] * len(rec))})", tuple(rec.values()))
                    msg = f"Project {project.project_code} created."
                    result = WriteResult(cur.lastrowid, False, msg)
                self._complete_request(cur, request_key, result.id, msg)
        project.project_id = result.id
        result.dw_synced = self._sync_dw("hr_dw.sp_load_dim_project")
        return result

    @handles_errors("load projects")
    def list(self, status: str | None = None, department_id: int | None = None, limit: int = 500) -> pd.DataFrame:
        sql = """SELECT p.project_id, p.project_code, p.project_name, d.department_name, p.client_name,
                        p.start_date, p.end_date, p.budget, p.status, p.priority
                 FROM hr_oltp.projects p JOIN hr_oltp.departments d ON d.department_id = p.department_id
                 WHERE (%s IS NULL OR p.status = %s) AND (%s IS NULL OR p.department_id = %s)
                 ORDER BY p.start_date DESC LIMIT %s"""
        return self.fetch_df(sql, (status, status, department_id, department_id, int(limit)))

    @handles_errors("assign the employee")
    def assign(self, employee_id: int, project_id: int, role_on_project: str, allocation_pct: int,
               start_date: date, end_date: date | None = None, request_key: str | None = None) -> WriteResult:
        """Idempotent on (employee, project, start_date): the same assignment twice is a no-op."""
        if not 1 <= allocation_pct <= 100:
            raise ValidationError("Allocation must be 1-100%.")
        if end_date and end_date < start_date:
            raise ValidationError("End date must be on or after the start date.")
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "assign")
            if prior:
                return WriteResult(prior["entity_id"], True, prior["response"], replayed=True)
            cur.execute("""SELECT assignment_id, role_on_project, allocation_pct, end_date FROM hr_oltp.assignments
                           WHERE employee_id = %s AND project_id = %s AND start_date = %s FOR UPDATE""",
                        (employee_id, project_id, start_date))
            existing = cur.fetchone()
            if existing:
                if (existing["role_on_project"], existing["allocation_pct"], existing["end_date"]) != \
                        (role_on_project, allocation_pct, end_date):
                    raise ValidationError("This employee already has an assignment to that project starting that "
                                          "day with different details.")
                msg = "Assignment already exists; nothing changed."
                self._complete_request(cur, request_key, existing["assignment_id"], msg)
                return WriteResult(existing["assignment_id"], True, msg, replayed=True)
            cur.execute(
                """SELECT COALESCE(SUM(allocation_pct), 0) AS pct FROM hr_oltp.assignments
                   WHERE employee_id = %s AND start_date <= COALESCE(%s, '9999-12-31')
                     AND COALESCE(end_date, '9999-12-31') >= %s""", (employee_id, end_date, start_date))
            load = int(cur.fetchone()["pct"])
            if load + allocation_pct > 150:
                raise ValidationError(f"Employee is already allocated {load}% in that period; "
                                      "this assignment would exceed 150%.")
            cur.execute(
                """INSERT INTO hr_oltp.assignments (employee_id, project_id, role_on_project, allocation_pct,
                                                    start_date, end_date) VALUES (%s, %s, %s, %s, %s, %s)""",
                (employee_id, project_id, role_on_project, allocation_pct, start_date, end_date))
            new_id = cur.lastrowid
            self._complete_request(cur, request_key, new_id, "Assignment saved.")
        return WriteResult(new_id, True, "Assignment saved.")

    @handles_errors("analyse project bottlenecks")
    def bottlenecks(self, as_of: date | None = None, limit: int = 25) -> pd.DataFrame:
        """Active projects that are overdue or thinly staffed relative to their budget.
        Uses a CTE for current staffing and RANK() to order the worst first."""
        as_of = as_of or date.today()
        return self.fetch_df(
            """
            WITH staffing AS (
                SELECT a.project_id, COUNT(*) AS people, SUM(a.allocation_pct) / 100 AS fte
                FROM hr_oltp.assignments a
                WHERE a.start_date <= %s AND COALESCE(a.end_date, '9999-12-31') >= %s
                GROUP BY a.project_id
            ),
            scored AS (
                SELECT p.project_code, p.project_name, d.department_name, p.status, p.priority, p.budget,
                       p.end_date, GREATEST(DATEDIFF(%s, p.end_date), 0) AS days_overdue,
                       COALESCE(s.people, 0) AS people, COALESCE(s.fte, 0) AS fte,
                       p.budget / NULLIF(COALESCE(s.fte, 0), 0) AS budget_per_fte
                FROM hr_oltp.projects p
                JOIN hr_oltp.departments d ON d.department_id = p.department_id
                LEFT JOIN staffing s ON s.project_id = p.project_id
                WHERE p.status IN ('Active', 'On Hold')
            )
            SELECT s.*,
                   RANK() OVER (ORDER BY (s.days_overdue > 0) DESC, s.fte ASC, s.budget DESC) AS bottleneck_rank
            FROM scored s
            ORDER BY bottleneck_rank
            LIMIT %s""", (as_of, as_of, as_of, int(limit)))


# --------------------------------------------------------------------------- reviews
class ReviewManager(BaseManager):
    @handles_errors("submit the review")
    def submit(self, review: Review, request_key: str | None = None) -> WriteResult:
        """Reviews have no natural key (two reviews on one day are legitimate), so
        duplicate protection comes from the request key alone."""
        with self.transaction() as cur:
            prior = self._claim_request(cur, request_key, "submit_review")
            if prior:
                result = WriteResult(prior["entity_id"], False, prior["response"], replayed=True)
            else:
                cur.execute("SELECT hire_date, termination_date FROM hr_oltp.employees WHERE employee_id = %s",
                            (review.employee_id,))
                emp = cur.fetchone()
                if emp is None:
                    raise ValidationError("Employee not found.")
                if review.review_date < emp["hire_date"]:
                    raise ValidationError("Review date is before the employee's hire date.")
                if emp["termination_date"] and review.review_date > emp["termination_date"]:
                    raise ValidationError("Review date is after the employee left.")
                if review.reviewer_id == review.employee_id:
                    raise ValidationError("An employee cannot review themselves.")
                rec = review.to_record()
                cur.execute(f"INSERT INTO hr_oltp.reviews ({', '.join(rec)}) "
                            f"VALUES ({', '.join(['%s'] * len(rec))})", tuple(rec.values()))
                review.review_id = cur.lastrowid
                msg = f"Review saved — rating {review.rating} ({review.rating_label})."
                self._complete_request(cur, request_key, review.review_id, msg)
                result = WriteResult(review.review_id, False, msg)
        result.dw_synced = self._sync_dw("hr_dw.sp_load_fact_performance_reviews", review.employee_id)
        return result

    @handles_errors("load reviews")
    def for_employee(self, employee_id: int) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT r.review_id, r.review_date, r.performance_score, r.rating, r.goals_met_pct,
                      p.project_code, r.comments
               FROM hr_oltp.reviews r LEFT JOIN hr_oltp.projects p ON p.project_id = r.project_id
               WHERE r.employee_id = %s ORDER BY r.review_date DESC""", (employee_id,))


# --------------------------------------------------------------------------- analytics (OLAP)
class AnalyticsManager(BaseManager):
    """Read-only. Everything here queries hr_dw, never hr_oltp."""

    @handles_errors("load KPIs")
    def kpis(self) -> dict:
        return self.fetch_one(
            """
            WITH latest AS (SELECT MAX(review_year) AS y FROM hr_dw.fact_performance_reviews)
            SELECT
              (SELECT COUNT(*) FROM hr_dw.dim_employee WHERE is_current = 1 AND attrition_flag = 0) AS active_headcount,
              (SELECT ROUND(100 * AVG(attrition_flag), 2) FROM hr_dw.dim_employee WHERE is_current = 1) AS attrition_rate_pct,
              (SELECT y FROM latest) AS latest_year,
              (SELECT ROUND(AVG(performance_score), 3) FROM hr_dw.fact_performance_reviews
                 WHERE review_year = (SELECT y FROM latest)) AS latest_avg_score,
              (SELECT COUNT(*) FROM hr_dw.fact_performance_reviews) AS total_reviews,
              (SELECT COUNT(*) FROM hr_dw.dim_employee WHERE is_current = 0) AS historical_versions
            """) or {}

    @handles_errors("load year-over-year trends")
    def yoy_performance(self) -> pd.DataFrame:
        return self.fetch_df("SELECT * FROM hr_dw.vw_yoy_performance ORDER BY department_name, review_year")

    @handles_errors("load review years")
    def review_years(self) -> list[int]:
        rows = self.fetch_all("SELECT DISTINCT review_year FROM hr_dw.fact_performance_reviews ORDER BY 1 DESC")
        return [r["review_year"] for r in rows]

    @handles_errors("rank top performers")
    def top_performers(self, year: int, department: str | None = None, top_n: int = 10) -> pd.DataFrame:
        """DENSE_RANK inside each department for one review year. Ties on score are broken by
        goals met; employees still tied share a rank (that is what DENSE_RANK means)."""
        return self.fetch_df(
            """
            WITH employee_year AS (
                SELECT de.employee_id, dd.department_name,
                       AVG(f.performance_score) AS avg_score, AVG(f.goals_met_pct) AS avg_goals_met_pct
                FROM hr_dw.fact_performance_reviews f
                JOIN hr_dw.dim_employee   de ON de.employee_sk   = f.employee_sk
                JOIN hr_dw.dim_department dd ON dd.department_sk = f.department_sk
                WHERE f.review_year = %(year)s
                  AND (%(dept)s IS NULL OR dd.department_name = %(dept)s)
                GROUP BY de.employee_id, dd.department_name
            ),
            ranked AS (
                SELECT ey.*, DENSE_RANK() OVER (PARTITION BY ey.department_name
                                                ORDER BY ey.avg_score DESC, ey.avg_goals_met_pct DESC) AS dept_rank
                FROM employee_year ey
            )
            SELECT r.department_name, r.dept_rank, cur.employee_number, cur.full_name,
                   cur.job_role AS current_role, ROUND(r.avg_score, 2) AS score,
                   ROUND(r.avg_goals_met_pct, 1) AS goals_met_pct
            FROM ranked r
            JOIN hr_dw.dim_employee cur ON cur.employee_id = r.employee_id AND cur.is_current = 1
            WHERE r.dept_rank <= %(n)s
            ORDER BY r.department_name, r.dept_rank, cur.employee_number""",
            {"year": int(year), "dept": department, "n": int(top_n)})

    @handles_errors("load the rating distribution")
    def rating_distribution(self, year: int) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT dd.department_name, f.rating, COUNT(*) AS reviews
               FROM hr_dw.fact_performance_reviews f
               JOIN hr_dw.dim_department dd ON dd.department_sk = f.department_sk
               WHERE f.review_year = %s GROUP BY dd.department_name, f.rating ORDER BY 1, 2""", (int(year),))

    @handles_errors("load attrition risk")
    def attrition_risk_by_department(self) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT department_name, risk_tier, COUNT(*) AS employees
               FROM hr_dw.vw_attrition_risk WHERE attrition_flag = 0
               GROUP BY department_name, risk_tier""")

    @handles_errors("validate the attrition risk score")
    def risk_score_validation(self) -> pd.DataFrame:
        """Average risk score of people who left vs. people who stayed. If the score is
        meaningful, leavers score clearly higher."""
        return self.fetch_df(
            """SELECT CASE attrition_flag WHEN 1 THEN 'Left' ELSE 'Stayed' END AS outcome,
                      COUNT(*) AS employees, ROUND(AVG(risk_score), 1) AS avg_risk_score,
                      ROUND(100 * AVG(risk_tier = 'High'), 1) AS pct_high_tier
               FROM hr_dw.vw_attrition_risk GROUP BY attrition_flag""")

    @handles_errors("list at-risk employees")
    def at_risk_employees(self, department: str | None = None, limit: int = 50) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT employee_number, full_name, department_name, job_role, job_level, salary_band,
                      overtime_flag, job_satisfaction, work_life_balance, years_since_last_promotion,
                      latest_score, risk_score, risk_tier
               FROM hr_dw.vw_attrition_risk
               WHERE attrition_flag = 0 AND (%s IS NULL OR department_name = %s)
               ORDER BY risk_score DESC, employee_number LIMIT %s""", (department, department, int(limit)))

    @handles_errors("load attrition drivers")
    def attrition_by_driver(self, driver: str) -> pd.DataFrame:
        allowed = {"overtime_flag", "job_satisfaction", "work_life_balance", "environment_satisfaction",
                   "job_level", "salary_band", "age_band", "business_travel"}
        if driver not in allowed:  # column names can't be bound as parameters, so whitelist them
            raise ValidationError(f"Unknown driver {driver!r}")
        return self.fetch_df(
            f"""SELECT {driver} AS bucket, COUNT(*) AS employees,
                       ROUND(100 * AVG(attrition_flag), 2) AS attrition_rate_pct
                FROM hr_dw.dim_employee WHERE is_current = 1
                GROUP BY {driver} ORDER BY {driver}""")

    @handles_errors("load department attrition")
    def department_attrition(self) -> pd.DataFrame:
        return self.fetch_df("SELECT * FROM hr_dw.vw_department_attrition ORDER BY attrition_rate_pct DESC")

    @handles_errors("load project performance")
    def weakest_projects(self, limit: int = 15) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT project_code, project_name, department_name, status, reviewed_staff, reviews,
                      avg_score_rounded AS avg_score, weakest_rank_in_dept
               FROM hr_dw.vw_project_performance WHERE reviews >= 5
               ORDER BY avg_score ASC LIMIT %s""", (int(limit),))

    @handles_errors("load SCD2 statistics")
    def scd2_summary(self) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT change_reason, COUNT(*) AS versions,
                      CAST(SUM(is_current) AS UNSIGNED)     AS current_versions,
                      CAST(SUM(1 - is_current) AS UNSIGNED) AS expired_versions
               FROM hr_dw.dim_employee GROUP BY change_reason ORDER BY versions DESC""")


# --------------------------------------------------------------------------- ETL
class EtlManager(BaseManager):
    @handles_errors("run the warehouse ETL")
    def run_full_etl(self) -> dict[str, pd.DataFrame]:
        """CALL hr_dw.sp_run_full_etl(): returns {'steps': ..., 'reconciliation': ...}.
        The procedure reconciles every layer at the end of the run."""
        results = self.call_procedure("hr_dw.sp_run_full_etl")
        frames = [to_numeric_frame(pd.DataFrame(r)) for r in results]
        return {"steps": frames[0] if frames else pd.DataFrame(),
                "reconciliation": frames[1] if len(frames) > 1 else pd.DataFrame()}

    @handles_errors("load the ETL audit log")
    def audit_log(self, limit: int = 50) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT run_id, step_name, rows_affected, started_at, finished_at,
                      ROUND(TIMESTAMPDIFF(MICROSECOND, started_at, finished_at) / 1e6, 2) AS seconds
               FROM hr_dw.etl_audit_log ORDER BY log_id DESC LIMIT %s""", (int(limit),))

    @handles_errors("count table rows")
    def table_counts(self) -> pd.DataFrame:
        tables = [
            ("hr_staging", "stg_employees"), ("hr_staging", "stg_reviews"), ("hr_staging", "stg_rejects"),
            ("hr_oltp", "employees"), ("hr_oltp", "employee_history"), ("hr_oltp", "projects"),
            ("hr_oltp", "assignments"), ("hr_oltp", "reviews"),
            ("hr_dw", "dim_date"), ("hr_dw", "dim_department"), ("hr_dw", "dim_project"),
            ("hr_dw", "dim_employee"), ("hr_dw", "fact_performance_reviews"),
        ]
        # exact COUNT(*) rather than information_schema estimates, which are off by large margins on InnoDB
        sql = " UNION ALL ".join(f"SELECT '{s}' AS schema_name, '{t}' AS table_name, COUNT(*) AS row_count FROM {s}.{t}"
                                 for s, t in tables)
        return self.fetch_df(sql)


# --------------------------------------------------------------------------- reconciliation
class ReconciliationManager(BaseManager):
    """Runs and reads the reconciliation checks (sql/08_reconciliation.sql).

    Layers: CSV_STAGING (written by scripts/load_staging.py), STAGING_OLTP,
    OLTP_DW and DW_INTEGRITY (written by hr_dw.sp_reconcile)."""

    LAYERS = ("STAGING_OLTP", "OLTP_DW")

    @handles_errors("run reconciliation")
    def run(self, layer: str | None = None, run_id: str | None = None) -> pd.DataFrame:
        if layer is not None and layer not in self.LAYERS:
            raise ValidationError(f"layer must be one of {self.LAYERS} or None")
        results = self.call_procedure("hr_dw.sp_reconcile", (run_id, layer))
        return to_numeric_frame(pd.DataFrame(results[-1] if results else []))

    @handles_errors("load reconciliation runs")
    def runs(self, limit: int = 20) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT run_id, MIN(checked_at) AS checked_at, COUNT(*) AS checks,
                      CAST(SUM(status = 'PASS') AS UNSIGNED) AS passed,
                      CAST(SUM(status = 'FAIL') AS UNSIGNED) AS failed,
                      CAST(SUM(status = 'WARN') AS UNSIGNED) AS warnings,
                      GROUP_CONCAT(DISTINCT layer ORDER BY layer) AS layers
               FROM hr_dw.reconciliation_log GROUP BY run_id
               ORDER BY MAX(log_id) DESC LIMIT %s""", (int(limit),))

    @handles_errors("load reconciliation results")
    def results(self, run_id: str) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT layer, check_name, expected_value, actual_value, status, details, checked_at
               FROM hr_dw.reconciliation_log WHERE run_id = %s ORDER BY log_id""", (run_id,))

    @handles_errors("load staging batches")
    def load_batches(self, limit: int = 30) -> pd.DataFrame:
        return self.fetch_df(
            """SELECT batch_id, table_name, status, csv_rows, staged_rows, control_column, csv_control,
                      staged_control, LEFT(file_sha256, 12) AS sha256, message, finished_at
               FROM hr_staging.load_batches ORDER BY batch_id DESC LIMIT %s""", (int(limit),))

    @handles_errors("load rejected rows")
    def rejects_summary(self) -> pd.DataFrame:
        return self.fetch_df("""SELECT entity, reason, COUNT(*) AS rows_rejected
                                FROM hr_staging.stg_rejects GROUP BY entity, reason ORDER BY rows_rejected DESC""")

    @staticmethod
    def failures(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["status"] == "FAIL"] if not df.empty and "status" in df else df.iloc[0:0]
