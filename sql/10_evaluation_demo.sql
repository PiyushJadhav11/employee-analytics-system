-- ====================================================================================================
-- ENTERPRISE EMPLOYEE ANALYTICS & DATA WAREHOUSE SYSTEM
-- 9 EVALUATION & VIVA DEMO QUERIES
-- ====================================================================================================
-- How to run in MySQL Workbench:
-- Open this file (File -> Open SQL Script -> sql/10_evaluation_demo.sql)
-- Highlight any query and click the Lightning Bolt (Execute) to show the evaluator.
-- ====================================================================================================

-- ----------------------------------------------------------------------------------------------------
-- QUERY 1: 3-TIER ARCHITECTURE & 100,000+ RECORD ROW COUNTS
-- Proves data flow: Raw Staging (101k) -> Clean 3NF OLTP (100k) -> Career History (142k) -> DW Star Schema (405k)
-- ----------------------------------------------------------------------------------------------------
SELECT '1. Staging (Raw IBM Scaled)' AS layer, COUNT(*) AS total_rows FROM hr_staging.stg_employees
UNION ALL
SELECT '2. OLTP 3NF (Active Employees)', COUNT(*) FROM hr_oltp.employees
UNION ALL
SELECT '3. OLTP (Career History)', COUNT(*) FROM hr_oltp.employee_history
UNION ALL
SELECT '4. Data Warehouse (SCD Type 2)', COUNT(*) FROM hr_dw.dim_employee
UNION ALL
SELECT '5. Data Warehouse (Reviews Fact)', COUNT(*) FROM hr_dw.fact_performance_reviews;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 2: SLOWLY CHANGING DIMENSIONS (SCD TYPE 2) CAREER TIMELINE
-- Shows past career version (is_current = 0, specific end_date) vs active version (is_current = 1, 9999-12-31)
-- ----------------------------------------------------------------------------------------------------
SELECT 
    employee_sk, 
    employee_id,
    version_no, 
    department_name, 
    job_role, 
    job_level, 
    monthly_income,
    start_date, 
    end_date, 
    is_current, 
    change_reason
FROM hr_dw.dim_employee
WHERE employee_id = (
    SELECT employee_id 
    FROM hr_dw.dim_employee
    WHERE is_current = 0 
    ORDER BY employee_id LIMIT 1
)
ORDER BY version_no;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 3: POINT-IN-TIME TEMPORAL QUERY (HISTORICAL HEADCOUNT)
-- Proves Kimball SCD2 capability: "Which department was everyone in on exactly 2023-06-30?"
-- ----------------------------------------------------------------------------------------------------
SELECT department_name, COUNT(*) AS headcount
FROM hr_dw.dim_employee
WHERE DATE '2023-06-30' BETWEEN start_date AND end_date
  AND hire_date <= DATE '2023-06-30'
  AND (termination_date IS NULL OR termination_date > DATE '2023-06-30')
GROUP BY department_name;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 4: DEPARTMENT TRANSFERS TRACKING (WINDOW FUNCTION: LAG)
-- Identifies employees who transferred departments with their previous and new departments
-- ----------------------------------------------------------------------------------------------------
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


-- ----------------------------------------------------------------------------------------------------
-- QUERY 5: SALARY GROWTH ACROSS VERSIONS (WINDOW FUNCTIONS: FIRST_VALUE / LAST_VALUE)
-- Calculates true career salary growth % across all historical promotion versions
-- ----------------------------------------------------------------------------------------------------
SELECT DISTINCT 
    employee_id, 
    full_name,
    FIRST_VALUE(monthly_income) OVER w AS initial_salary,
    LAST_VALUE(monthly_income)  OVER w AS current_salary,
    ROUND(100 * (LAST_VALUE(monthly_income) OVER w / FIRST_VALUE(monthly_income) OVER w - 1), 1) AS growth_pct
FROM hr_dw.dim_employee
WINDOW w AS (
    PARTITION BY employee_id 
    ORDER BY start_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
)
ORDER BY growth_pct DESC
LIMIT 20;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 6: TOP 5 PERFORMERS PER DEPARTMENT (WINDOW FUNCTION: DENSE_RANK)
-- Implements Phase 3 requirement: DENSE_RANK() OVER (PARTITION BY department_name, review_year ORDER BY avg_score DESC)
-- ----------------------------------------------------------------------------------------------------
SELECT 
    review_year, 
    department_name, 
    dept_rank, 
    full_name, 
    current_role, 
    avg_score
FROM hr_dw.vw_top_performers
WHERE review_year = (SELECT MAX(review_year) FROM hr_dw.fact_performance_reviews) 
  AND dept_rank <= 5
ORDER BY department_name, dept_rank;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 7: YEAR-OVER-YEAR PERFORMANCE TREND (WINDOW FUNCTION: LAG)
-- Implements Phase 3 requirement: LAG(avg_score) OVER (PARTITION BY department_name ORDER BY review_year)
-- ----------------------------------------------------------------------------------------------------
SELECT 
    department_name, 
    review_year, 
    reviews, 
    avg_score, 
    prev_year_avg_score, 
    yoy_change_pct
FROM hr_dw.vw_yoy_performance 
ORDER BY department_name, review_year;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 8: ATTRITION RISK TIERS PER DEPARTMENT
-- Aggregates active workforce by calculated attrition risk tiers (High / Medium / Low)
-- ----------------------------------------------------------------------------------------------------
SELECT 
    department_name, 
    risk_tier, 
    COUNT(*) AS employees
FROM hr_dw.vw_attrition_risk 
WHERE attrition_flag = 0
GROUP BY department_name, risk_tier 
ORDER BY department_name, risk_tier;


-- ----------------------------------------------------------------------------------------------------
-- QUERY 9: ETL EXECUTION AUDIT & RECONCILIATION LOG
-- Proves automated stored procedure execution (sp_run_full_etl) and tracks duration & rows affected
-- ----------------------------------------------------------------------------------------------------
SELECT 
    log_id, 
    run_id, 
    step_name, 
    rows_affected, 
    started_at, 
    finished_at
FROM hr_dw.etl_audit_log 
ORDER BY log_id DESC 
LIMIT 20;
