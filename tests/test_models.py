"""Unit tests for the entity classes and SQL splitter. No database needed."""
from datetime import date, timedelta

import pytest

from hr_analytics.etl import SqlScriptRunner
from hr_analytics.models import Employee, Project, Review, ValidationError


def make_employee(**overrides):
    data = dict(first_name="Asha", last_name="Rao", email="asha.rao@greenfield-corp.com", gender="Female",
                date_of_birth=date(1995, 4, 2), hire_date=date(2022, 1, 10), department_id=1,
                job_role_id=1, job_level=2, monthly_income=5200)
    data.update(overrides)
    return Employee(**data)


def test_employee_valid_and_derived_fields():
    e = make_employee()
    assert e.full_name == "Asha Rao"
    assert e.age_on(date(2025, 4, 1)) == 29 and e.age_on(date(2025, 4, 2)) == 30
    assert e.to_record()["email"] == "asha.rao@greenfield-corp.com"


@pytest.mark.parametrize("field,value", [
    ("email", "not-an-email"),
    ("gender", "X"),
    ("job_level", 6),
    ("monthly_income", 0),
    ("first_name", "  "),
    ("hire_date", date.today() + timedelta(days=1)),
    ("hire_date", date(2005, 1, 1)),  # employee would be 9
])
def test_employee_rejects_bad_input(field, value):
    with pytest.raises(ValidationError):
        make_employee(**{field: value})


def test_employee_setter_validates_after_construction():
    e = make_employee()
    with pytest.raises(ValidationError):
        e.job_level = 0
    assert e.job_level == 2


@pytest.mark.parametrize("score,rating", [(1.0, 1), (1.99, 1), (2.0, 2), (3.5, 3), (3.99, 3), (4.0, 4), (5.0, 4)])
def test_review_rating_is_derived_from_score(score, rating):
    r = Review(employee_id=1, review_date=date(2025, 12, 1), performance_score=score, goals_met_pct=50)
    assert r.rating == rating


def test_review_rejects_out_of_range():
    with pytest.raises(ValidationError):
        Review(employee_id=1, review_date=date(2025, 12, 1), performance_score=5.5, goals_met_pct=50)
    with pytest.raises(ValidationError):
        Review(employee_id=1, review_date=date(2025, 12, 1), performance_score=3, goals_met_pct=101)


def test_project_dates_and_code():
    p = Project("prj-123", "Data platform", 1, date(2025, 1, 1), date(2025, 6, 30))
    assert p.project_code == "PRJ-123" and p.duration_days == 180
    with pytest.raises(ValidationError):
        Project("PRJ-1", "Bad dates", 1, date(2025, 6, 1), date(2025, 1, 1))
    active = Project("PRJ-2", "Late one", 1, date(2024, 1, 1), date(2024, 6, 1), status="Active")
    assert active.is_overdue(today=date(2025, 1, 1))


def test_sql_splitter_handles_delimiter_blocks():
    script = """
-- header comment;
CREATE TABLE a (x INT);
DELIMITER $$
CREATE PROCEDURE p()
BEGIN
    SELECT 1;
    SELECT 2;
END $$
DELIMITER ;
SELECT 3;
"""
    stmts = SqlScriptRunner.split(script)
    assert len(stmts) == 3
    assert stmts[1].startswith("CREATE PROCEDURE") and "SELECT 2;" in stmts[1]


# --------------------------------------------------------------------------- synthesizer validation
def _tiny_dataset():
    import pandas as pd
    e = pd.DataFrame({"employee_number": [1, 2], "email": ["a@x.com", "b@x.com"],
                      "hire_date": [date(2020, 1, 1), date(2021, 1, 1)], "termination_date": [None, None],
                      "department": ["Sales", "Sales"], "job_role": ["Manager", "Manager"],
                      "job_level": [3, 3], "monthly_income": [5000, 6000]})
    h = pd.DataFrame({"employee_number": [1, 2], "department": ["Sales", "Sales"], "job_role": ["Manager", "Manager"],
                      "job_level": [3, 3], "monthly_income": [5000, 6000],
                      "effective_start": [date(2020, 1, 1), date(2021, 1, 1)],
                      "effective_end": [date(9999, 12, 31)] * 2, "is_current": [1, 1]})
    p = pd.DataFrame({"project_code": ["P1"], "start_date": [date(2020, 1, 1)], "end_date": [date(2020, 6, 1)]})
    a = pd.DataFrame({"employee_number": [1], "project_code": ["P1"],
                      "start_date": [date(2020, 1, 1)], "end_date": [date(2020, 6, 1)]})
    r = pd.DataFrame({"review_id": [1], "employee_number": [1], "project_code": [None],
                      "review_date": [date(2021, 12, 1)], "performance_score": [3.5], "rating": [3]})
    return e, h, p, a, r


def test_data_validator_accepts_consistent_data():
    from scripts.data_synthesizer import DataValidator
    DataValidator(*_tiny_dataset()).validate()


@pytest.mark.parametrize("corrupt", ["two_current", "gap", "rating_mismatch", "orphan_review", "dup_review"])
def test_data_validator_catches_broken_data(corrupt):
    import pandas as pd
    from scripts.data_synthesizer import DataValidationError, DataValidator
    e, h, p, a, r = _tiny_dataset()
    if corrupt == "two_current":
        h = pd.concat([h, h.iloc[[0]].assign(effective_start=date(2022, 1, 1))], ignore_index=True)
    elif corrupt == "gap":
        h.loc[0, "effective_end"] = date(2021, 1, 1)
        h = pd.concat([h, h.iloc[[0]].assign(effective_start=date(2022, 1, 1), effective_end=date(9999, 12, 31))],
                      ignore_index=True)
        h.loc[0, "is_current"] = 0
    elif corrupt == "rating_mismatch":
        r.loc[0, "rating"] = 4
    elif corrupt == "orphan_review":
        r.loc[0, "employee_number"] = 99
    elif corrupt == "dup_review":
        r = pd.concat([r, r], ignore_index=True)
    with pytest.raises(DataValidationError):
        DataValidator(e, h, p, a, r).validate()


def test_check_result_compare():
    from decimal import Decimal
    from hr_analytics.etl import CheckResult
    assert CheckResult.compare("L", "x", 10, Decimal("10.00")).status == "PASS"
    assert CheckResult.compare("L", "x", 10, 11).status == "FAIL"
    assert CheckResult.compare("L", "x", 10, 11, on_mismatch="WARN").status == "WARN"
    assert CheckResult.compare("L", "x", None, 11).status == "FAIL"
