"""
Entity classes. Each one validates its own data on construction and on every
property assignment, so an invalid Employee/Project/Review can never reach the
database layer. Managers only ever persist these objects.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)


class ValidationError(ValueError):
    """Bad input from a form; the message is shown to the user as-is."""


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValidationError(message)


class Employee:
    GENDERS = ("Male", "Female")
    MARITAL = ("Single", "Married", "Divorced")
    TRAVEL = ("Non-Travel", "Travel_Rarely", "Travel_Frequently")

    def __init__(
        self,
        first_name: str,
        last_name: str,
        email: str,
        gender: str,
        date_of_birth: date,
        hire_date: date,
        department_id: int,
        job_role_id: int,
        job_level: int,
        monthly_income: float,
        marital_status: str = "Single",
        education: int = 3,
        education_field: str = "Other",
        city: str | None = None,
        business_travel: str = "Travel_Rarely",
        overtime: bool = False,
        distance_from_home: int = 5,
        total_working_years: int = 0,
        employee_number: int | None = None,
        employee_id: int | None = None,
    ) -> None:
        self.employee_id = employee_id
        self.employee_number = employee_number
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.gender = gender
        self._date_of_birth = date_of_birth
        self.hire_date = hire_date  # validates against date_of_birth
        self.department_id = department_id
        self.job_role_id = job_role_id
        self.job_level = job_level
        self.monthly_income = monthly_income
        self.marital_status = marital_status
        self.education = education
        self.education_field = education_field
        self.city = city
        self.business_travel = business_travel
        self.overtime = bool(overtime)
        self.distance_from_home = distance_from_home
        self.total_working_years = total_working_years

    # --- validated properties -------------------------------------------------
    @property
    def first_name(self) -> str:
        return self._first_name

    @first_name.setter
    def first_name(self, value: str) -> None:
        value = (value or "").strip()
        _require(1 <= len(value) <= 60, "First name is required (max 60 characters).")
        self._first_name = value

    @property
    def last_name(self) -> str:
        return self._last_name

    @last_name.setter
    def last_name(self, value: str) -> None:
        value = (value or "").strip()
        _require(1 <= len(value) <= 60, "Last name is required (max 60 characters).")
        self._last_name = value

    @property
    def email(self) -> str:
        return self._email

    @email.setter
    def email(self, value: str) -> None:
        value = (value or "").strip().lower()
        _require(bool(EMAIL_RE.match(value)), f"'{value}' is not a valid email address.")
        self._email = value

    @property
    def gender(self) -> str:
        return self._gender

    @gender.setter
    def gender(self, value: str) -> None:
        _require(value in self.GENDERS, f"Gender must be one of {self.GENDERS}.")
        self._gender = value

    @property
    def hire_date(self) -> date:
        return self._hire_date

    @hire_date.setter
    def hire_date(self, value: date) -> None:
        _require(value <= date.today(), "Hire date cannot be in the future.")
        _require(self.age_on(value) >= 18, "Employee must be at least 18 on the hire date.")
        self._hire_date = value

    @property
    def job_level(self) -> int:
        return self._job_level

    @job_level.setter
    def job_level(self, value: int) -> None:
        _require(1 <= int(value) <= 5, "Job level must be between 1 and 5.")
        self._job_level = int(value)

    @property
    def monthly_income(self) -> float:
        return self._monthly_income

    @monthly_income.setter
    def monthly_income(self, value: float) -> None:
        _require(float(value) > 0, "Monthly income must be positive.")
        self._monthly_income = round(float(value), 2)

    @property
    def marital_status(self) -> str:
        return self._marital_status

    @marital_status.setter
    def marital_status(self, value: str) -> None:
        _require(value in self.MARITAL, f"Marital status must be one of {self.MARITAL}.")
        self._marital_status = value

    @property
    def business_travel(self) -> str:
        return self._business_travel

    @business_travel.setter
    def business_travel(self, value: str) -> None:
        _require(value in self.TRAVEL, f"Business travel must be one of {self.TRAVEL}.")
        self._business_travel = value

    # --- behaviour --------------------------------------------------------------
    @property
    def date_of_birth(self) -> date:
        return self._date_of_birth

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def age_on(self, on: date) -> int:
        dob = self._date_of_birth
        return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))

    @property
    def age(self) -> int:
        return self.age_on(date.today())

    @property
    def tenure_years(self) -> float:
        return round((date.today() - self.hire_date).days / 365.25, 1)

    def to_record(self) -> dict[str, Any]:
        """Column -> value mapping for hr_oltp.employees."""
        return {
            "employee_number": self.employee_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "gender": self.gender,
            "date_of_birth": self.date_of_birth,
            "marital_status": self.marital_status,
            "education": self.education,
            "education_field": self.education_field,
            "city": self.city,
            "hire_date": self.hire_date,
            "department_id": self.department_id,
            "job_role_id": self.job_role_id,
            "job_level": self.job_level,
            "monthly_income": self.monthly_income,
            "business_travel": self.business_travel,
            "overtime": self.overtime,
            "distance_from_home": self.distance_from_home,
            "total_working_years": self.total_working_years,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Employee":
        keys = ("first_name", "last_name", "email", "gender", "date_of_birth", "hire_date",
                "department_id", "job_role_id", "job_level", "monthly_income", "marital_status",
                "education", "education_field", "city", "business_travel", "overtime",
                "distance_from_home", "total_working_years", "employee_number", "employee_id")
        return cls(**{k: row[k] for k in keys if k in row})

    def __repr__(self) -> str:
        return f"Employee(#{self.employee_number}, {self.full_name!r}, level={self.job_level})"


class Project:
    STATUSES = ("Planned", "Active", "On Hold", "Completed", "Cancelled")
    PRIORITIES = ("Low", "Medium", "High", "Critical")

    def __init__(
        self,
        project_code: str,
        project_name: str,
        department_id: int,
        start_date: date,
        end_date: date | None = None,
        budget: float = 0.0,
        status: str = "Planned",
        priority: str = "Medium",
        client_name: str | None = None,
        project_id: int | None = None,
    ) -> None:
        self.project_id = project_id
        self.project_code = project_code
        self.project_name = project_name
        self.department_id = department_id
        self._start_date = start_date
        self.end_date = end_date
        self.budget = budget
        self.status = status
        self.priority = priority
        self.client_name = client_name

    @property
    def project_code(self) -> str:
        return self._project_code

    @project_code.setter
    def project_code(self, value: str) -> None:
        value = (value or "").strip().upper()
        _require(bool(re.fullmatch(r"[A-Z0-9-]{3,20}", value)), "Project code: 3-20 letters, digits or dashes.")
        self._project_code = value

    @property
    def project_name(self) -> str:
        return self._project_name

    @project_name.setter
    def project_name(self, value: str) -> None:
        value = (value or "").strip()
        _require(3 <= len(value) <= 150, "Project name must be 3-150 characters.")
        self._project_name = value

    @property
    def start_date(self) -> date:
        return self._start_date

    @property
    def end_date(self) -> date | None:
        return self._end_date

    @end_date.setter
    def end_date(self, value: date | None) -> None:
        _require(value is None or value >= self._start_date, "End date must be on or after the start date.")
        self._end_date = value

    @property
    def budget(self) -> float:
        return self._budget

    @budget.setter
    def budget(self, value: float) -> None:
        _require(float(value) >= 0, "Budget cannot be negative.")
        self._budget = float(value)

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        _require(value in self.STATUSES, f"Status must be one of {self.STATUSES}.")
        self._status = value

    @property
    def priority(self) -> str:
        return self._priority

    @priority.setter
    def priority(self, value: str) -> None:
        _require(value in self.PRIORITIES, f"Priority must be one of {self.PRIORITIES}.")
        self._priority = value

    @property
    def duration_days(self) -> int | None:
        return (self.end_date - self.start_date).days if self.end_date else None

    def is_overdue(self, today: date | None = None) -> bool:
        today = today or date.today()
        return self.status in ("Active", "On Hold") and self.end_date is not None and self.end_date < today

    def to_record(self) -> dict[str, Any]:
        return {
            "project_code": self.project_code,
            "project_name": self.project_name,
            "department_id": self.department_id,
            "client_name": self.client_name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "budget": self.budget,
            "status": self.status,
            "priority": self.priority,
        }

    def __repr__(self) -> str:
        return f"Project({self.project_code!r}, {self.status})"


class Review:
    """A performance review. The 1-4 rating is derived from the 1-5 score, never entered separately,
    so the two can't disagree."""

    def __init__(
        self,
        employee_id: int,
        review_date: date,
        performance_score: float,
        goals_met_pct: float,
        comments: str = "",
        reviewer_id: int | None = None,
        project_id: int | None = None,
        review_id: int | None = None,
    ) -> None:
        self.review_id = review_id
        self.employee_id = employee_id
        self.reviewer_id = reviewer_id
        self.project_id = project_id
        self.review_date = review_date
        self.performance_score = performance_score
        self.goals_met_pct = goals_met_pct
        self.comments = comments

    @property
    def review_date(self) -> date:
        return self._review_date

    @review_date.setter
    def review_date(self, value: date) -> None:
        _require(value <= date.today(), "Review date cannot be in the future.")
        self._review_date = value

    @property
    def performance_score(self) -> float:
        return self._performance_score

    @performance_score.setter
    def performance_score(self, value: float) -> None:
        _require(1.0 <= float(value) <= 5.0, "Performance score must be between 1.0 and 5.0.")
        self._performance_score = round(float(value), 2)

    @property
    def goals_met_pct(self) -> float:
        return self._goals_met_pct

    @goals_met_pct.setter
    def goals_met_pct(self, value: float) -> None:
        _require(0 <= float(value) <= 100, "Goals met must be 0-100%.")
        self._goals_met_pct = round(float(value), 1)

    @property
    def comments(self) -> str:
        return self._comments

    @comments.setter
    def comments(self, value: str) -> None:
        value = (value or "").strip()
        _require(len(value) <= 255, "Comments are limited to 255 characters.")
        self._comments = value

    @property
    def rating(self) -> int:
        s = self.performance_score
        return 1 if s < 2 else 2 if s < 3 else 3 if s < 4 else 4

    @property
    def rating_label(self) -> str:
        return {1: "Low", 2: "Good", 3: "Excellent", 4: "Outstanding"}[self.rating]

    def to_record(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "reviewer_id": self.reviewer_id,
            "project_id": self.project_id,
            "review_date": self.review_date,
            "review_year": self.review_date.year,
            "performance_score": self.performance_score,
            "rating": self.rating,
            "goals_met_pct": self.goals_met_pct,
            "comments": self.comments or None,
        }

    def __repr__(self) -> str:
        return f"Review(employee={self.employee_id}, {self.review_date}, score={self.performance_score})"
