-- =====================================================================
-- 09  Sample queries for MySQL Workbench (read-only, safe to run any time)
-- =====================================================================

-- 1. Every version of one employee (SCD Type 2)
SELECT employee_sk, version_no, department_name, job_role, job_level, monthly_income,
       start_date, end_date, is_current, change_reason
FROM hr_dw.dim_employee
WHERE employee_id = (SELECT employee_id FROM hr_dw.dim_employee
                     WHERE is_current = 0 ORDER BY employee_id LIMIT 1)
ORDER BY start_date;

-- 2. Point-in-time: which department was everyone in on 2023-06-30?
SELECT department_name, COUNT(*) AS headcount
FROM hr_dw.dim_employee
WHERE DATE '2023-06-30' BETWEEN start_date AND end_date
  AND hire_date <= DATE '2023-06-30'
  AND (termination_date IS NULL OR termination_date > DATE '2023-06-30')
GROUP BY department_name;

-- 3. Employees who changed department, with before/after (LAG over versions)
WITH v AS (
    SELECT employee_id, full_name, start_date, department_name,
           LAG(department_name) OVER (PARTITION BY employee_id ORDER BY start_date) AS previous_department
    FROM hr_dw.dim_employee
)
SELECT employee_id, full_name, start_date AS moved_on, previous_department, department_name AS new_department
FROM v
WHERE previous_department IS NOT NULL AND previous_department <> department_name
ORDER BY moved_on DESC
LIMIT 20;

-- 4. Salary growth per employee across versions (FIRST_VALUE / LAST_VALUE)
SELECT DISTINCT employee_id, full_name,
       FIRST_VALUE(monthly_income) OVER w AS first_income,
       LAST_VALUE(monthly_income)  OVER w AS latest_income,
       ROUND(100 * (LAST_VALUE(monthly_income) OVER w / FIRST_VALUE(monthly_income) OVER w - 1), 1) AS growth_pct
FROM hr_dw.dim_employee
WINDOW w AS (PARTITION BY employee_id ORDER BY start_date
             ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
ORDER BY growth_pct DESC
LIMIT 20;

-- 5. Top 5 per department in the latest year (DENSE_RANK)
SELECT * FROM hr_dw.vw_top_performers
WHERE review_year = (SELECT MAX(review_year) FROM hr_dw.fact_performance_reviews) AND dept_rank <= 5
ORDER BY department_name, dept_rank;

-- 6. Year-over-year trend
SELECT * FROM hr_dw.vw_yoy_performance ORDER BY department_name, review_year;

-- 7. Attrition risk tiers per department (active employees)
SELECT department_name, risk_tier, COUNT(*) AS employees
FROM hr_dw.vw_attrition_risk WHERE attrition_flag = 0
GROUP BY department_name, risk_tier ORDER BY department_name, risk_tier;

-- 8. ETL history
SELECT * FROM hr_dw.etl_audit_log ORDER BY log_id DESC LIMIT 20;


SELECT 'staging' AS layer, COUNT(*) FROM hr_staging.stg_employees
UNION ALL SELECT 'oltp employees', COUNT(*) FROM hr_oltp.employees
UNION ALL SELECT 'dim_employee', COUNT(*) FROM hr_dw.dim_employee
UNION ALL SELECT 'fact reviews', COUNT(*) FROM hr_dw.fact_performance_reviews;

SELECT employee_sk, version_no, department_name, job_role, monthly_income,
       start_date, end_date, is_current, change_reason
FROM hr_dw.dim_employee
WHERE full_name LIKE 'Priya%'
ORDER BY employee_id, start_date;
