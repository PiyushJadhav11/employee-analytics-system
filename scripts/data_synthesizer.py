"""
Data Synthesizer — scales the IBM HR Analytics snapshot (~1,470 rows) to 100,000+
employees and engineers the history needed for SCD Type 2.

Pipeline (each step is one class):

    BaseDatasetLoader      read + validate the IBM CSV (or SeedDatasetGenerator as a fallback)
    EmployeeScaler         bootstrap-sample whole rows, jitter numerics, add Faker identity fields
    HistoryEngineer        walk backwards from today's state to build prior versions (SCD2)
    ProjectSynthesizer     projects owned by departments
    AssignmentSynthesizer  employee <-> project allocations that respect tenure dates
    ReviewSynthesizer      one annual review per employee per year employed
    DirtyDataInjector      a small amount of realistic mess for the SQL cleaning step
    CsvExporter            writes data/synthetic/*.csv

Usage:
    python scripts/data_synthesizer.py                       # 100,000 employees
    python scripts/data_synthesizer.py --rows 250000
    python scripts/data_synthesizer.py --fallback-base       # no IBM CSV available
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "data" / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
DEFAULT_OUT = ROOT / "data" / "synthetic"
OPEN_END = date(9999, 12, 31)
MANIFEST_NAME = "_manifest.json"

log = logging.getLogger("synthesizer")

# Columns in the original IBM file. EmployeeCount, Over18 and StandardHours are
# constant across every row, so they carry no information and are dropped.
IBM_COLUMNS = [
    "Age", "Attrition", "BusinessTravel", "DailyRate", "Department", "DistanceFromHome",
    "Education", "EducationField", "EmployeeCount", "EmployeeNumber", "EnvironmentSatisfaction",
    "Gender", "HourlyRate", "JobInvolvement", "JobLevel", "JobRole", "JobSatisfaction",
    "MaritalStatus", "MonthlyIncome", "MonthlyRate", "NumCompaniesWorked", "Over18", "OverTime",
    "PercentSalaryHike", "PerformanceRating", "RelationshipSatisfaction", "StandardHours",
    "StockOptionLevel", "TotalWorkingYears", "TrainingTimesLastYear", "WorkLifeBalance",
    "YearsAtCompany", "YearsInCurrentRole", "YearsSinceLastPromotion", "YearsWithCurrManager",
]
CONSTANT_COLUMNS = ["EmployeeCount", "Over18", "StandardHours"]

DEPARTMENTS = pd.DataFrame(
    [
        ("SAL", "Sales", "CC-100", "Mumbai"),
        ("RND", "Research & Development", "CC-200", "Bengaluru"),
        ("HRM", "Human Resources", "CC-300", "Pune"),
    ],
    columns=["department_code", "department_name", "cost_center", "location"],
)

DEPARTMENT_ROLES = {
    "Sales": ["Sales Executive", "Sales Representative", "Manager"],
    "Research & Development": [
        "Research Scientist", "Laboratory Technician", "Manufacturing Director",
        "Healthcare Representative", "Research Director", "Manager",
    ],
    "Human Resources": ["Human Resources", "Manager"],
}

REVIEW_COMMENTS = {
    1: ["Did not meet core objectives; improvement plan agreed.", "Significant gaps in delivery this cycle."],
    2: ["Met some objectives; needs more consistency.", "Solid effort, delivery was uneven."],
    3: ["Met all objectives with good quality.", "Reliable contributor, strong teamwork.", "Consistently delivers on commitments."],
    4: ["Exceeded objectives and mentored peers.", "Outstanding impact across the project.", "Role model for the team."],
}


@dataclass
class SynthesizerConfig:
    target_rows: int = 100_000
    history_fraction: float = 0.35          # share of eligible employees who get prior versions
    n_projects: int = 2_000
    snapshot_date: date = date(2025, 12, 31)  # "today" of the IBM snapshot
    review_start_year: int = 2021
    dirty_fraction: float = 0.01            # 0 disables dirty-data injection
    seed: int = 42
    base_path: Path = DEFAULT_BASE
    output_dir: Path = DEFAULT_OUT
    fallback_base: bool = False
    rng: np.random.Generator = field(init=False)
    faker: Faker = field(init=False)

    def __post_init__(self) -> None:
        if self.target_rows < 1:
            raise ValueError("--rows must be positive")
        self.rng = np.random.default_rng(self.seed)
        self.faker = Faker("en_IN")
        Faker.seed(self.seed)


# --------------------------------------------------------------------------- base data
class BaseDatasetLoader:
    """Reads the IBM CSV and checks it is the file we expect."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Base dataset not found at {self.path}.\n"
                "Download 'IBM HR Analytics Employee Attrition & Performance' from Kaggle "
                "(pavansubhasht/ibm-hr-analytics-attrition-dataset) and place the CSV there, "
                "or re-run with --fallback-base."
            )
        df = pd.read_csv(self.path)
        missing = set(IBM_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{self.path.name} is missing expected IBM columns: {sorted(missing)}")
        log.info("Loaded IBM base dataset: %s rows x %s columns", len(df), df.shape[1])
        return df[IBM_COLUMNS]


class SeedDatasetGenerator:
    """Fallback: a 1,470-row frame with the IBM schema and similar distributions.

    Only used when the real CSV is unavailable (CI, quick demos). The README tells
    users to prefer the real file.
    """

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.rng = cfg.rng

    def generate(self, n: int = 1_470) -> pd.DataFrame:
        r = self.rng
        dept = r.choice(list(DEPARTMENT_ROLES), n, p=[0.30, 0.65, 0.05])
        role = np.array([r.choice(DEPARTMENT_ROLES[d]) for d in dept])
        level = np.clip(r.choice([1, 2, 3, 4, 5], n, p=[0.37, 0.36, 0.15, 0.07, 0.05]), 1, 5)
        level = np.where(np.isin(role, ["Manager", "Research Director"]), np.maximum(level, 4), level)
        income = np.clip((level * 3_400 + r.normal(0, 1_200, n)).round(), 1_009, 19_999)
        age = np.clip(r.normal(37, 9, n).round(), 18, 60).astype(int)
        total_years = np.clip((age - 18) * r.uniform(0.3, 0.9, n), 0, 40).round().astype(int)
        years_company = np.minimum(total_years, r.gamma(2.0, 3.5, n).round().astype(int))
        in_role = np.minimum(years_company, r.integers(0, 10, n))
        since_promo = np.minimum(years_company, r.integers(0, 8, n))
        with_mgr = np.minimum(years_company, r.integers(0, 10, n))
        overtime = r.choice(["Yes", "No"], n, p=[0.28, 0.72])
        jobsat = r.integers(1, 5, n)
        attr_p = 0.08 + 0.15 * (overtime == "Yes") + 0.06 * (jobsat == 1) + 0.06 * (level == 1)
        hike = r.integers(11, 26, n)
        return pd.DataFrame({
            "Age": age,
            "Attrition": np.where(r.random(n) < attr_p, "Yes", "No"),
            "BusinessTravel": r.choice(["Travel_Rarely", "Travel_Frequently", "Non-Travel"], n, p=[0.71, 0.19, 0.10]),
            "DailyRate": r.integers(102, 1_500, n),
            "Department": dept,
            "DistanceFromHome": r.integers(1, 30, n),
            "Education": r.choice([1, 2, 3, 4, 5], n, p=[0.12, 0.19, 0.39, 0.27, 0.03]),
            "EducationField": r.choice(["Life Sciences", "Medical", "Marketing", "Technical Degree", "Other", "Human Resources"], n, p=[0.41, 0.32, 0.11, 0.09, 0.05, 0.02]),
            "EmployeeCount": 1,
            "EmployeeNumber": np.arange(1, n + 1),
            "EnvironmentSatisfaction": r.integers(1, 5, n),
            "Gender": r.choice(["Male", "Female"], n, p=[0.6, 0.4]),
            "HourlyRate": r.integers(30, 101, n),
            "JobInvolvement": r.choice([1, 2, 3, 4], n, p=[0.06, 0.26, 0.59, 0.09]),
            "JobLevel": level,
            "JobRole": role,
            "JobSatisfaction": jobsat,
            "MaritalStatus": r.choice(["Married", "Single", "Divorced"], n, p=[0.46, 0.32, 0.22]),
            "MonthlyIncome": income.astype(int),
            "MonthlyRate": r.integers(2_094, 27_000, n),
            "NumCompaniesWorked": r.integers(0, 10, n),
            "Over18": "Y",
            "OverTime": overtime,
            "PercentSalaryHike": hike,
            "PerformanceRating": np.where(hike >= 20, 4, 3),
            "RelationshipSatisfaction": r.integers(1, 5, n),
            "StandardHours": 80,
            "StockOptionLevel": r.choice([0, 1, 2, 3], n, p=[0.43, 0.41, 0.11, 0.05]),
            "TotalWorkingYears": total_years,
            "TrainingTimesLastYear": r.integers(0, 7, n),
            "WorkLifeBalance": r.choice([1, 2, 3, 4], n, p=[0.05, 0.23, 0.61, 0.11]),
            "YearsAtCompany": years_company,
            "YearsInCurrentRole": in_role,
            "YearsSinceLastPromotion": since_promo,
            "YearsWithCurrManager": with_mgr,
        })


# --------------------------------------------------------------------------- employees
class EmployeeScaler:
    """Scales the base snapshot to N employees.

    Whole rows are bootstrap-sampled so cross-column correlations in the IBM data
    (income vs. level, attrition vs. overtime, ...) survive. Numerics then get
    bounded jitter so the copies are not identical, and the tenure columns are
    re-constrained so no employee has worked longer than they have been adults.
    """

    JITTER = {  # column: (absolute sd or relative sd, lower, upper, relative?)
        "Age": (2.5, 18, 60, False),
        "DailyRate": (0.10, 102, 1_499, True),
        "HourlyRate": (0.10, 30, 100, True),
        "MonthlyRate": (0.10, 2_094, 26_999, True),
        "MonthlyIncome": (0.08, 1_009, 19_999, True),
        "DistanceFromHome": (2.0, 1, 29, False),
        "NumCompaniesWorked": (1.0, 0, 9, False),
        "TrainingTimesLastYear": (1.0, 0, 6, False),
        "PercentSalaryHike": (1.0, 11, 25, False),
    }
    RESAMPLE_COLS = [  # survey answers: resample a few from the column's marginal
        "EnvironmentSatisfaction", "JobSatisfaction", "RelationshipSatisfaction",
        "WorkLifeBalance", "JobInvolvement",
    ]

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg
        self.rng = cfg.rng

    def scale(self, base: pd.DataFrame) -> pd.DataFrame:
        n, r = self.cfg.target_rows, self.rng
        df = base.drop(columns=CONSTANT_COLUMNS).iloc[r.integers(0, len(base), n)].reset_index(drop=True)

        for col, (sd, lo, hi, relative) in self.JITTER.items():
            vals = df[col].to_numpy(dtype=float)
            vals = vals * r.normal(1.0, sd, n) if relative else vals + r.normal(0, sd, n)
            df[col] = np.clip(np.round(vals), lo, hi).astype(int)

        for col in self.RESAMPLE_COLS:
            mask = r.random(n) < 0.15
            df.loc[mask, col] = r.choice(base[col].to_numpy(), mask.sum())

        # Tenure must be internally consistent after jitter.
        max_career = np.maximum(df["Age"] - 18, 0)
        df["TotalWorkingYears"] = np.minimum(df["TotalWorkingYears"], max_career)
        df["YearsAtCompany"] = np.minimum(df["YearsAtCompany"], df["TotalWorkingYears"])
        for col in ["YearsInCurrentRole", "YearsSinceLastPromotion", "YearsWithCurrManager"]:
            df[col] = np.minimum(df[col], df["YearsAtCompany"])

        df["EmployeeNumber"] = np.arange(100_001, 100_001 + n)
        df = self._add_identity(df)
        df = self._add_dates(df)
        return self._rename(df)

    def _add_identity(self, df: pd.DataFrame) -> pd.DataFrame:
        """Names come from pre-built Faker pools: 100k individual Faker calls is ~30x slower."""
        f, r, n = self.cfg.faker, self.rng, len(df)
        male = np.array([f.first_name_male() for _ in range(1_500)])
        female = np.array([f.first_name_female() for _ in range(1_500)])
        last = np.array([f.last_name() for _ in range(2_000)])
        cities = np.array([f.city() for _ in range(300)])

        is_male = (df["Gender"] == "Male").to_numpy()
        first = np.where(is_male, r.choice(male, n), r.choice(female, n))
        surname = r.choice(last, n)
        df.insert(1, "first_name", first)
        df.insert(2, "last_name", surname)
        slug = (pd.Series(first).str.lower() + "." + pd.Series(surname).str.lower()).str.replace(r"[^a-z.]", "", regex=True)
        df.insert(3, "email", slug + "." + df["EmployeeNumber"].astype(str) + "@greenfield-corp.com")
        df["city"] = r.choice(cities, n)
        return df

    def _add_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        snap, r, n = pd.Timestamp(self.cfg.snapshot_date), self.rng, len(df)
        hire = snap - pd.to_timedelta(df["YearsAtCompany"] * 365 + r.integers(0, 365, n), unit="D")
        dob = snap - pd.to_timedelta(df["Age"] * 365 + r.integers(0, 365, n), unit="D")
        # Leavers left within the last year, but never before they joined.
        leave_offset = pd.Series(pd.to_timedelta(r.integers(1, 365, n), unit="D"), index=df.index)
        term = (snap - leave_offset).where(df["Attrition"] == "Yes")
        term = term.where(term.isna() | (term > hire + pd.Timedelta(days=30)), hire + pd.Timedelta(days=30))
        df["hire_date"] = hire.dt.date
        df["date_of_birth"] = dob.dt.date
        df["termination_date"] = term.dt.date
        return df

    @staticmethod
    def _rename(df: pd.DataFrame) -> pd.DataFrame:
        mapping = {
            "EmployeeNumber": "employee_number", "Age": "age", "Attrition": "attrition",
            "BusinessTravel": "business_travel", "DailyRate": "daily_rate", "Department": "department",
            "DistanceFromHome": "distance_from_home", "Education": "education",
            "EducationField": "education_field", "EnvironmentSatisfaction": "environment_satisfaction",
            "Gender": "gender", "HourlyRate": "hourly_rate", "JobInvolvement": "job_involvement",
            "JobLevel": "job_level", "JobRole": "job_role", "JobSatisfaction": "job_satisfaction",
            "MaritalStatus": "marital_status", "MonthlyIncome": "monthly_income",
            "MonthlyRate": "monthly_rate", "NumCompaniesWorked": "num_companies_worked",
            "OverTime": "overtime", "PercentSalaryHike": "percent_salary_hike",
            "PerformanceRating": "performance_rating",
            "RelationshipSatisfaction": "relationship_satisfaction",
            "StockOptionLevel": "stock_option_level", "TotalWorkingYears": "total_working_years",
            "TrainingTimesLastYear": "training_times_last_year", "WorkLifeBalance": "work_life_balance",
            "YearsAtCompany": "years_at_company", "YearsInCurrentRole": "years_in_current_role",
            "YearsSinceLastPromotion": "years_since_last_promotion",
            "YearsWithCurrManager": "years_with_curr_manager",
        }
        df = df.rename(columns=mapping)
        front = ["employee_number", "first_name", "last_name", "email", "gender", "date_of_birth", "age"]
        return df[front + [c for c in df.columns if c not in front]]


# --------------------------------------------------------------------------- SCD2 history
class HistoryEngineer:
    """Builds employee_history: one row per version of (department, role, level, income).

    The IBM file only tells us where each employee is *now*. For a random subset of
    employees with 2+ years' tenure we walk backwards from that state and undo
    1-3 events — a promotion, a department transfer, or a salary revision — each
    dated between the hire date and the snapshot. Everyone else gets a single
    version that started on their hire date.

    Every employee's versions tile their tenure with no gaps or overlaps:
    version k ends the day before version k+1 starts, and the last version is
    open-ended (9999-12-31, is_current = 1). That is exactly the shape SCD2 needs.
    """

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg
        self.rng = cfg.rng

    def build(self, emp: pd.DataFrame) -> pd.DataFrame:
        r = self.rng
        eligible = emp["years_at_company"] >= 2
        chosen = eligible & (r.random(len(emp)) < self.cfg.history_fraction)
        log.info("Engineering SCD2 history for %s of %s employees", int(chosen.sum()), len(emp))

        rows: list[tuple] = []
        cols = ["employee_number", "department", "job_role", "job_level", "monthly_income",
                "hire_date", "years_at_company", "percent_salary_hike"]
        for e in emp.loc[chosen, cols].itertuples(index=False):
            rows.extend(self._versions_for(e))

        single = emp.loc[~chosen, ["employee_number", "department", "job_role", "job_level",
                                   "monthly_income", "hire_date"]].copy()
        single = single.rename(columns={"hire_date": "effective_start"})
        single["version_no"] = 1
        single["effective_end"] = OPEN_END
        single["is_current"] = 1
        single["change_reason"] = "HIRE"

        multi = pd.DataFrame(rows, columns=[
            "employee_number", "version_no", "department", "job_role", "job_level",
            "monthly_income", "effective_start", "effective_end", "is_current", "change_reason",
        ])
        hist = pd.concat([multi, single[multi.columns]], ignore_index=True)
        return hist.sort_values(["employee_number", "version_no"]).reset_index(drop=True)

    def _versions_for(self, e) -> list[tuple]:
        r, snap = self.rng, self.cfg.snapshot_date
        n_changes = int(min(r.choice([1, 2, 3], p=[0.6, 0.3, 0.1]), e.years_at_company - 1))
        n_changes = max(n_changes, 1)
        earliest = e.hire_date + timedelta(days=180)
        span = (snap - earliest).days
        offsets = np.sort(r.choice(np.arange(1, span), size=n_changes, replace=False))
        change_dates = [earliest + timedelta(days=int(o)) for o in offsets]

        # Walk backwards: state = version after the change, derive version before it.
        state = dict(department=e.department, job_role=e.job_role,
                     job_level=int(e.job_level), monthly_income=float(e.monthly_income))
        versions_newest_first = []
        for change_date in reversed(change_dates):
            event = self._pick_event(state)
            versions_newest_first.append((dict(state), change_date, event))
            state = self._undo(state, event, e.percent_salary_hike)
        versions_newest_first.append((dict(state), e.hire_date, "HIRE"))

        ordered = list(reversed(versions_newest_first))
        out = []
        for i, (s, start, reason) in enumerate(ordered, start=1):
            is_last = i == len(ordered)
            end = OPEN_END if is_last else ordered[i][1] - timedelta(days=1)
            out.append((e.employee_number, i, s["department"], s["job_role"], s["job_level"],
                        round(s["monthly_income"]), start, end, int(is_last), reason))
        return out

    def _pick_event(self, state: dict) -> str:
        options, weights = ["SALARY_REVISION", "DEPARTMENT_TRANSFER"], [0.45, 0.20]
        if state["job_level"] > 1:
            options.append("PROMOTION")
            weights.append(0.35)
        w = np.array(weights) / sum(weights)
        return str(self.rng.choice(options, p=w))

    def _undo(self, state: dict, event: str, hike_pct: float) -> dict:
        r, prev = self.rng, dict(state)
        if event == "PROMOTION":
            prev["job_level"] = state["job_level"] - 1
            prev["monthly_income"] = state["monthly_income"] / (1 + r.uniform(0.10, 0.20))
            if state["job_role"] in ("Manager", "Research Director"):
                prev["job_role"] = r.choice([x for x in DEPARTMENT_ROLES[state["department"]]
                                             if x not in ("Manager", "Research Director")])
        elif event == "DEPARTMENT_TRANSFER":
            prev["department"] = r.choice([d for d in DEPARTMENT_ROLES if d != state["department"]])
            prev["job_role"] = r.choice([x for x in DEPARTMENT_ROLES[prev["department"]] if x != "Manager"]
                                        or DEPARTMENT_ROLES[prev["department"]])
            prev["monthly_income"] = state["monthly_income"] / (1 + r.uniform(0.0, 0.06))
        else:  # SALARY_REVISION
            prev["monthly_income"] = state["monthly_income"] / (1 + hike_pct / 100)
        prev["monthly_income"] = max(prev["monthly_income"], 1_009)
        return prev


# --------------------------------------------------------------------------- projects
class ProjectSynthesizer:
    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg

    def build(self, emp: pd.DataFrame) -> pd.DataFrame:
        n, r, f, snap = self.cfg.n_projects, self.cfg.rng, self.cfg.faker, self.cfg.snapshot_date
        share = emp["department"].value_counts(normalize=True)
        dept = r.choice(share.index.to_numpy(), n, p=share.to_numpy())
        first_day, last_day = date(2019, 1, 1), snap - timedelta(days=60)
        start = [first_day + timedelta(days=int(d)) for d in r.integers(0, (last_day - first_day).days, n)]
        duration = r.integers(90, 730, n)
        end = [s + timedelta(days=int(d)) for s, d in zip(start, duration)]
        status = np.where(np.array(end) < snap, "Completed", "Active")
        flip = r.random(n)
        status = np.where((status == "Active") & (flip < 0.12), "On Hold", status)
        status = np.where((status == "Completed") & (flip < 0.04), "Cancelled", status)
        # Some projects run late: past their end date but still open (feeds bottleneck analysis).
        late = (np.array(end) < snap) & (np.array(end) > snap - timedelta(days=240)) & (flip > 0.80)
        status = np.where(late, "Active", status)
        clients = [f.company() for _ in range(250)]
        return pd.DataFrame({
            "project_code": [f"PRJ-{i:05d}" for i in range(1, n + 1)],
            "project_name": [f.catch_phrase().title()[:120] for _ in range(n)],
            "department": dept,
            "client_name": r.choice(clients, n),
            "start_date": start,
            "end_date": end,
            "budget": np.round(r.lognormal(13.2, 0.8, n), -3),
            "status": status,
            "priority": r.choice(["Low", "Medium", "High", "Critical"], n, p=[0.2, 0.45, 0.27, 0.08]),
        })


class AssignmentSynthesizer:
    """1-3 project assignments per employee, only on projects that overlap their tenure."""

    ROLES = ["Contributor", "Analyst", "Developer", "Lead", "Reviewer", "Coordinator"]

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg

    def build(self, emp: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
        r, snap = self.cfg.rng, pd.Timestamp(self.cfg.snapshot_date)
        k = r.choice([1, 2, 3], len(emp), p=[0.5, 0.35, 0.15])
        cand = emp.loc[emp.index.repeat(k), ["employee_number", "department", "hire_date", "termination_date"]]
        cand = cand.reset_index(drop=True)
        cand["emp_start"] = pd.to_datetime(cand["hire_date"])
        cand["emp_end"] = pd.to_datetime(cand["termination_date"]).fillna(snap)

        proj = projects.assign(p_start=pd.to_datetime(projects["start_date"]),
                               p_end=pd.to_datetime(projects["end_date"]))
        by_dept = {d: g.index.to_numpy() for d, g in proj.groupby("department")}
        chosen = np.full(len(cand), -1)
        pending = np.arange(len(cand))
        for _ in range(6):  # a few vectorised retry rounds for picks that miss the tenure window
            if not len(pending):
                break
            same_dept = r.random(len(pending)) < 0.8
            picks = np.where(
                same_dept,
                [r.choice(by_dept[d]) for d in cand.loc[pending, "department"]],
                r.integers(0, len(proj), len(pending)),
            )
            ok = (proj.loc[picks, "p_start"].to_numpy() <= cand.loc[pending, "emp_end"].to_numpy()) & \
                 (proj.loc[picks, "p_end"].to_numpy() >= cand.loc[pending, "emp_start"].to_numpy())
            chosen[pending[ok]] = picks[ok]
            pending = pending[~ok]

        cand["proj_idx"] = chosen
        cand = cand[cand["proj_idx"] >= 0]
        p = proj.loc[cand["proj_idx"]].reset_index(drop=True)
        cand = cand.reset_index(drop=True)
        out = pd.DataFrame({
            "employee_number": cand["employee_number"],
            "project_code": p["project_code"],
            "role_on_project": r.choice(self.ROLES, len(cand)),
            "allocation_pct": r.choice([25, 50, 75, 100], len(cand), p=[0.2, 0.35, 0.2, 0.25]),
            "start_date": np.maximum(p["p_start"], cand["emp_start"]).dt.date,
            "end_date": np.minimum(p["p_end"], cand["emp_end"]).dt.date,
        })
        return out.drop_duplicates(["employee_number", "project_code"]).reset_index(drop=True)


class ReviewSynthesizer:
    """One review per employee per December they were employed (review_start_year .. snapshot year).

    The most recent review matches the IBM PerformanceRating; earlier ones drift
    from it with a per-employee random walk so year-over-year trends exist.
    """

    BANDS = {1: (1.00, 1.99), 2: (2.00, 2.99), 3: (3.00, 3.99), 4: (4.00, 5.00)}

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg

    def build(self, emp: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
        r, years = self.cfg.rng, range(self.cfg.review_start_year, self.cfg.snapshot_date.year + 1)
        hire = pd.to_datetime(emp["hire_date"])
        term = pd.to_datetime(emp["termination_date"])
        frames = []
        for y in years:
            cutoff = pd.Timestamp(y, 12, 1)
            alive = (hire < cutoff) & (term.isna() | (term >= pd.Timestamp(y, 12, 28)))
            sub = emp.loc[alive, ["employee_number", "department", "performance_rating", "job_involvement"]].copy()
            sub["review_year"] = y
            frames.append(sub)
        rev = pd.concat(frames, ignore_index=True)
        rev["review_date"] = pd.to_datetime(dict(year=rev["review_year"], month=12,
                                                 day=r.integers(1, 21, len(rev)))).dt.date

        # Latest review score sits inside the band of the IBM rating; earlier years drift.
        lo = rev["performance_rating"].map(lambda x: self.BANDS[x][0])
        hi = rev["performance_rating"].map(lambda x: self.BANDS[x][1])
        anchor = lo + (hi - lo) * r.random(len(rev))
        years_back = rev.groupby("employee_number")["review_year"].transform("max") - rev["review_year"]
        drift = r.normal(-0.06, 0.28, len(rev)) * years_back   # slight upward company-wide trend
        involvement = (rev["job_involvement"] - 2.7) * 0.08
        rev["performance_score"] = np.clip(anchor + drift + involvement * (years_back > 0), 1.0, 5.0).round(2)
        rev["rating"] = np.select(
            [rev["performance_score"] < 2, rev["performance_score"] < 3, rev["performance_score"] < 4],
            [1, 2, 3], 4,
        )
        rev["goals_met_pct"] = np.clip(rev["performance_score"] * 19 + r.normal(0, 7, len(rev)), 0, 100).round(1)
        rev["comments"] = [r.choice(REVIEW_COMMENTS[x]) for x in rev["rating"]]

        rev = self._attach_project(rev, assignments)
        rev = self._attach_reviewer(rev, emp)
        rev = rev.sort_values(["review_date", "employee_number"]).reset_index(drop=True)
        rev.insert(0, "review_id", np.arange(1, len(rev) + 1))
        return rev[["review_id", "employee_number", "reviewer_employee_number", "project_code",
                    "review_date", "review_year", "performance_score", "rating",
                    "goals_met_pct", "comments"]]

    @staticmethod
    def _attach_project(rev: pd.DataFrame, asg: pd.DataFrame) -> pd.DataFrame:
        """The project the employee was on when reviewed (first match), else NULL."""
        rev = rev.reset_index(drop=True).assign(_rid=lambda d: d.index)
        m = rev[["_rid", "employee_number", "review_date"]].merge(
            asg[["employee_number", "project_code", "start_date", "end_date"]], on="employee_number")
        m = m[(m["start_date"] <= m["review_date"]) & (m["end_date"] >= m["review_date"])]
        m = m.drop_duplicates("_rid")[["_rid", "project_code"]]
        return rev.merge(m, on="_rid", how="left").drop(columns="_rid")

    def _attach_reviewer(self, rev: pd.DataFrame, emp: pd.DataFrame) -> pd.DataFrame:
        r = self.cfg.rng
        managers = emp.loc[emp["job_role"].isin(["Manager", "Research Director"]), ["employee_number", "department"]]
        pool = {d: g["employee_number"].to_numpy() for d, g in managers.groupby("department")}
        picks = [r.choice(pool[d]) if d in pool else None for d in rev["department"]]
        rev["reviewer_employee_number"] = pd.array(picks, dtype="Int64")
        rev.loc[rev["reviewer_employee_number"] == rev["employee_number"], "reviewer_employee_number"] = pd.NA
        return rev


# --------------------------------------------------------------------------- dirty data
class DirtyDataInjector:
    """Adds the kind of mess real extracts have, so the SQL cleaning step has work to do.

    * duplicate employee rows from a second, older extract (dedupe: ROW_NUMBER by extracted_at)
    * inconsistent casing/whitespace in gender and department (normalise: TRIM/UPPER/CASE)
    * exact duplicate review rows (dedupe: ROW_NUMBER by review_id)
    """

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg

    def apply(self, emp: pd.DataFrame, rev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        r, frac = self.cfg.rng, self.cfg.dirty_fraction
        snap = datetime.combine(self.cfg.snapshot_date, datetime.min.time())
        emp = emp.copy()
        emp["extracted_at"] = snap
        if frac <= 0:
            return emp, rev

        idx = r.choice(emp.index, int(len(emp) * frac), replace=False)
        stale = emp.loc[idx].copy()
        stale["extracted_at"] = snap - timedelta(days=30)
        stale["monthly_income"] = (stale["monthly_income"] * 0.95).round()

        messy = r.choice(emp.index, int(len(emp) * frac), replace=False)
        emp.loc[messy, "gender"] = emp.loc[messy, "gender"].map({"Male": " m", "Female": "female "})
        emp.loc[messy, "department"] = "  " + emp.loc[messy, "department"].str.upper() + " "

        dup_reviews = rev.sample(n=int(len(rev) * frac / 2), random_state=self.cfg.seed)
        log.info("Injected %s stale employee rows, %s messy rows, %s duplicate reviews",
                 len(stale), len(messy), len(dup_reviews))
        emp = pd.concat([emp, stale], ignore_index=True)
        rev = pd.concat([rev, dup_reviews], ignore_index=True)
        return emp, rev


# --------------------------------------------------------------------------- validation
class DataValidationError(ValueError):
    """The generated data broke an invariant; nothing is written."""


class DataValidator:
    """Checks the clean (pre-dirt) data before anything is published.

    Every rule here is something a later stage relies on. If the synthesizer ever
    produces data that breaks one, it is far cheaper to stop here than to find
    out from a reconciliation failure three stages later.
    """

    def __init__(self, employees: pd.DataFrame, history: pd.DataFrame, projects: pd.DataFrame,
                 assignments: pd.DataFrame, reviews: pd.DataFrame) -> None:
        self.e, self.h, self.p, self.a, self.r = employees, history, projects, assignments, reviews
        self.failures: list[str] = []

    def _check(self, name: str, bad: int) -> None:
        if bad:
            self.failures.append(f"{name}: {bad:,} violating rows")
        log.info("  check %-48s %s", name, "ok" if not bad else f"FAIL ({bad:,})")

    def validate(self) -> None:
        e, h, p, a, r = self.e, self.h, self.p, self.a, self.r
        log.info("Validating generated data")
        self._check("employee_number unique", int(e["employee_number"].duplicated().sum()))
        self._check("email unique", int(e["email"].duplicated().sum()))

        hs = h.sort_values(["employee_number", "effective_start"]).copy()
        hs["start"] = pd.to_datetime(hs["effective_start"])
        hs["end"] = pd.to_datetime(hs["effective_end"].map(lambda d: min(d, date(2262, 1, 1))))
        nxt = hs.groupby("employee_number")["start"].shift(-1)
        self._check("SCD2 versions have no gaps or overlaps",
                    int((nxt.notna() & (hs["end"] + pd.Timedelta(days=1) != nxt)).sum()))
        self._check("SCD2 start <= end", int((hs["start"] > hs["end"]).sum()))
        current = hs.groupby("employee_number")["is_current"].sum()
        self._check("exactly one current version per employee", int((current != 1).sum()))
        self._check("every employee has history", int((~e["employee_number"].isin(h["employee_number"])).sum()))
        first = hs.groupby("employee_number")["start"].first()
        hire = pd.to_datetime(e.set_index("employee_number")["hire_date"]).reindex(first.index)
        self._check("first version starts on hire date", int((first != hire).sum()))
        cur = hs[hs["is_current"] == 1].set_index("employee_number")
        ei = e.set_index("employee_number").reindex(cur.index)
        mismatch = sum(int((ei[c] != cur[c]).sum()) for c in ["department", "job_role", "job_level", "monthly_income"])
        self._check("current version equals employee row", mismatch)
        self._check("history (employee, start) unique", int(h.duplicated(["employee_number", "effective_start"]).sum()))

        self._check("project end >= start", int((p["end_date"] < p["start_date"]).sum()))
        self._check("project_code unique", int(p["project_code"].duplicated().sum()))
        self._check("assignment end >= start", int((a["end_date"] < a["start_date"]).sum()))
        self._check("assignment employee exists", int((~a["employee_number"].isin(e["employee_number"])).sum()))
        self._check("assignment project exists", int((~a["project_code"].isin(p["project_code"])).sum()))

        self._check("review_id unique", int(r["review_id"].duplicated().sum()))
        self._check("review employee exists", int((~r["employee_number"].isin(e["employee_number"])).sum()))
        self._check("review project exists (when set)",
                    int((r["project_code"].notna() & ~r["project_code"].isin(p["project_code"])).sum()))
        self._check("review score in 1..5", int((~r["performance_score"].between(1, 5)).sum()))
        derived = np.select([r["performance_score"] < 2, r["performance_score"] < 3, r["performance_score"] < 4],
                            [1, 2, 3], 4)
        self._check("review rating matches score band", int((derived != r["rating"]).sum()))
        rh = r.merge(e[["employee_number", "hire_date", "termination_date"]], on="employee_number")
        self._check("review not before hire", int((rh["review_date"] < rh["hire_date"]).sum()))
        self._check("review not after exit",
                    int((rh["termination_date"].notna() & (rh["review_date"] > rh["termination_date"])).sum()))
        if self.failures:
            raise DataValidationError("Generated data failed validation; nothing was written:\n  "
                                      + "\n  ".join(self.failures))


# --------------------------------------------------------------------------- export
class CsvExporter:
    """Publishes all CSVs atomically.

    Files are first written to a hidden temp directory, then each is moved into
    place with os.replace (atomic on one filesystem), and the manifest is written
    last. A crash mid-run therefore never leaves a mix of old and new CSVs that
    agree with no manifest — and the loader refuses files whose checksum does not
    match the manifest.
    """

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = Path(tempfile.mkdtemp(prefix=".publish-", dir=self.out_dir))
        self.files: dict[str, dict] = {}

    def write(self, name: str, df: pd.DataFrame) -> None:
        path = self.tmp_dir / f"{name}.csv"
        df.to_csv(path, index=False, date_format="%Y-%m-%d")
        self.files[name] = {"file": path.name, "rows": int(len(df)), "bytes": path.stat().st_size,
                            "sha256": sha256_file(path)}
        log.info("  %-20s %10s rows  %7.1f MB", path.name, f"{len(df):,}", path.stat().st_size / 1e6)

    def publish(self, manifest: dict) -> Path:
        manifest = {**manifest, "files": self.files}
        (self.tmp_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, default=str))
        old_manifest = self.out_dir / MANIFEST_NAME
        if old_manifest.exists():
            old_manifest.unlink()  # no manifest while files are being swapped -> loader refuses to run
        for meta in self.files.values():
            os.replace(self.tmp_dir / meta["file"], self.out_dir / meta["file"])
        os.replace(self.tmp_dir / MANIFEST_NAME, self.out_dir / MANIFEST_NAME)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        return self.out_dir / MANIFEST_NAME

    def abort(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DataSynthesizer:
    """Facade that runs the whole pipeline."""

    def __init__(self, cfg: SynthesizerConfig) -> None:
        self.cfg = cfg

    def run(self) -> dict[str, pd.DataFrame]:
        t0 = time.perf_counter()
        base_is_fallback = self.cfg.fallback_base and not self.cfg.base_path.exists()
        if base_is_fallback:
            log.warning("IBM CSV not found — generating a 1,470-row seed with the same schema (--fallback-base)")
            base = SeedDatasetGenerator(self.cfg).generate()
        else:
            base = BaseDatasetLoader(self.cfg.base_path).load()

        employees = EmployeeScaler(self.cfg).scale(base)
        history = HistoryEngineer(self.cfg).build(employees)
        # employees.* must equal each employee's current version
        cur = history[history["is_current"] == 1].set_index("employee_number")
        employees = employees.set_index("employee_number")
        for col in ["department", "job_role", "job_level", "monthly_income"]:
            employees[col] = cur[col]
        employees = employees.reset_index()

        projects = ProjectSynthesizer(self.cfg).build(employees)
        assignments = AssignmentSynthesizer(self.cfg).build(employees, projects)
        reviews = ReviewSynthesizer(self.cfg).build(employees, assignments)

        job_roles = (history[["department", "job_role"]].drop_duplicates()
                     .sort_values(["department", "job_role"]).reset_index(drop=True))
        DataValidator(employees, history, projects, assignments, reviews).validate()
        employees_out, reviews_out = DirtyDataInjector(self.cfg).apply(employees, reviews)

        tables = {
            "departments": DEPARTMENTS,
            "job_roles": job_roles,
            "employees": employees_out,
            "employee_history": history,
            "projects": projects,
            "assignments": assignments,
            "reviews": reviews_out,
        }
        # What the downstream stages should end up with once duplicates are removed.
        # load_staging.py and the SQL reconciliation check their counts against these.
        expected = {
            "departments": len(DEPARTMENTS),
            "job_roles": len(job_roles),
            "employees": int(employees["employee_number"].nunique()),
            "employee_duplicates_injected": int(len(employees_out) - len(employees)),
            "employee_history": len(history),
            "projects": len(projects),
            "assignments": len(assignments),
            "reviews": int(reviews["review_id"].nunique()),
            "review_duplicates_injected": int(len(reviews_out) - len(reviews)),
        }
        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generator": "scripts/data_synthesizer.py",
            "seed": self.cfg.seed,
            "rows_requested": self.cfg.target_rows,
            "base_dataset": "fallback-seed" if base_is_fallback else str(self.cfg.base_path.name),
            "snapshot_date": self.cfg.snapshot_date,
            "expected_after_dedup": expected,
            "control_totals": {
                "employees.monthly_income": f"{employees['monthly_income'].sum():.2f}",
                "reviews.performance_score": f"{sum(Decimal(str(v)) for v in reviews['performance_score']):.2f}",
            },
        }

        log.info("Writing CSVs to %s", self.cfg.output_dir)
        exporter = CsvExporter(self.cfg.output_dir)
        try:
            for name, df in tables.items():
                exporter.write(name, df)
            manifest_path = exporter.publish(manifest)
        except BaseException:
            exporter.abort()
            raise
        total = sum(len(df) for df in tables.values())
        log.info("Published %s rows across %s files + %s in %.1fs", f"{total:,}", len(tables),
                 manifest_path.name, time.perf_counter() - t0)
        return tables


def parse_args(argv: list[str] | None = None) -> SynthesizerConfig:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=100_000, help="number of employees to generate (default 100000)")
    p.add_argument("--projects", type=int, default=2_000)
    p.add_argument("--history-fraction", type=float, default=0.35)
    p.add_argument("--dirty-fraction", type=float, default=0.01, help="0 disables dirty-data injection")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--base", type=Path, default=DEFAULT_BASE, help="path to the IBM CSV")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--fallback-base", action="store_true",
                   help="generate an IBM-shaped seed if the real CSV is missing")
    a = p.parse_args(argv)
    return SynthesizerConfig(target_rows=a.rows, n_projects=a.projects, history_fraction=a.history_fraction,
                             dirty_fraction=a.dirty_fraction, seed=a.seed, base_path=a.base,
                             output_dir=a.out, fallback_base=a.fallback_base)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    try:
        DataSynthesizer(parse_args(argv)).run()
    except (FileNotFoundError, ValueError) as exc:  # includes DataValidationError
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
