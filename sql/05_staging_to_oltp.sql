-- =====================================================================
-- 05  Staging -> OLTP load (clean, de-duplicate, resolve keys, reject)
--
-- Cleaning, all with CTEs + window functions:
--   * duplicate employee rows from older extracts -> ROW_NUMBER() ... ORDER BY extracted_at DESC, keep 1
--   * duplicate reviews / history / assignments    -> ROW_NUMBER() over the natural key, keep 1
--   * ' m' / 'female ' / 'MALE'                    -> CASE on UPPER(TRIM(gender))
--   * '  SALES ' department labels                 -> TRIM + case-insensitive join to departments
--
-- Every staged row either lands in OLTP or is written to hr_staging.stg_rejects
-- with a reason. Nothing is dropped silently and nothing is "fixed" silently
-- (out-of-range scores are rejected, not clamped), so reconciliation can prove
--     distinct staged keys = keys present in OLTP + keys rejected.
--
-- Idempotent: inserts skip keys that already exist, the reject list is rebuilt
-- each run, and everything runs in one transaction (all or nothing).
-- Run with:  CALL hr_oltp.sp_load_from_staging();
-- =====================================================================
USE hr_oltp;

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_load_from_staging $$
CREATE PROCEDURE sp_load_from_staging()
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        DROP TEMPORARY TABLE IF EXISTS tmp_emp_clean;
        RESIGNAL;
    END;

    START TRANSACTION;
    DELETE FROM hr_staging.stg_rejects;

    -- 1. Departments -------------------------------------------------------
    INSERT INTO hr_oltp.departments (department_code, department_name, cost_center, location)
    WITH ranked AS (
        SELECT UPPER(TRIM(department_code)) AS department_code,
               TRIM(department_name)        AS department_name,
               TRIM(cost_center)            AS cost_center,
               TRIM(location)               AS location,
               ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(department_code)) ORDER BY department_name) AS rn
        FROM hr_staging.stg_departments
    )
    SELECT r.department_code, r.department_name, r.cost_center, r.location
    FROM ranked r
    WHERE r.rn = 1
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.departments d WHERE d.department_code = r.department_code);

    -- 2. Job roles: every (department, role) pair seen anywhere in staging --
    INSERT INTO hr_oltp.job_roles (department_id, role_name)
    WITH pairs AS (
        SELECT TRIM(department) AS dept, TRIM(job_role) AS role FROM hr_staging.stg_job_roles
        UNION
        SELECT TRIM(department), TRIM(job_role) FROM hr_staging.stg_employees
        UNION
        SELECT TRIM(department), TRIM(job_role) FROM hr_staging.stg_employee_history
    )
    SELECT DISTINCT d.department_id, p.role
    FROM pairs p
    JOIN hr_oltp.departments d ON d.department_name = p.dept
    WHERE NOT EXISTS (SELECT 1 FROM hr_oltp.job_roles j
                      WHERE j.department_id = d.department_id AND j.role_name = p.role);

    -- 3. Employees: de-duplicate, clean and resolve once, into a temp table --
    DROP TEMPORARY TABLE IF EXISTS tmp_emp_clean;
    CREATE TEMPORARY TABLE tmp_emp_clean (PRIMARY KEY (employee_number)) AS
    SELECT x.*,
           CASE
               WHEN x.gender_clean  IS NULL THEN 'UNRECOGNISED_GENDER'
               WHEN x.department_id IS NULL THEN 'UNKNOWN_DEPARTMENT'
               WHEN x.job_role_id   IS NULL THEN 'UNKNOWN_ROLE'
               WHEN x.email_uses    > 1     THEN 'DUPLICATE_EMAIL_IN_BATCH'
               WHEN EXISTS (SELECT 1 FROM hr_oltp.employees o
                            WHERE o.email = x.email_clean AND o.employee_number <> x.employee_number)
                                            THEN 'EMAIL_USED_BY_OTHER_EMPLOYEE'
           END AS reject_reason
    FROM (
        WITH ranked AS (
            SELECT s.*,
                   ROW_NUMBER() OVER (PARTITION BY s.employee_number ORDER BY s.extracted_at DESC) AS rn
            FROM hr_staging.stg_employees s
            WHERE s.employee_number IS NOT NULL
        ),
        cleaned AS (
            SELECT r.*,
                   CASE WHEN UPPER(TRIM(r.gender)) IN ('M', 'MALE')   THEN 'Male'
                        WHEN UPPER(TRIM(r.gender)) IN ('F', 'FEMALE') THEN 'Female' END AS gender_clean,
                   LOWER(TRIM(r.email)) AS email_clean,
                   TRIM(r.department)   AS dept_clean,
                   TRIM(r.job_role)     AS role_clean
            FROM ranked r
            WHERE r.rn = 1
        )
        SELECT c.*, d.department_id, j.job_role_id,
               COUNT(*) OVER (PARTITION BY c.email_clean) AS email_uses
        FROM cleaned c
        LEFT JOIN hr_oltp.departments d ON d.department_name = c.dept_clean
        LEFT JOIN hr_oltp.job_roles   j ON j.department_id = d.department_id AND j.role_name = c.role_clean
    ) AS x;

    INSERT INTO hr_staging.stg_rejects (entity, source_key, reason)
    SELECT 'employees', CAST(t.employee_number AS CHAR), t.reject_reason
    FROM tmp_emp_clean t WHERE t.reject_reason IS NOT NULL;

    INSERT INTO hr_oltp.employees (
        employee_number, first_name, last_name, email, gender, date_of_birth, marital_status,
        education, education_field, city, hire_date, termination_date, department_id, job_role_id,
        job_level, monthly_income, daily_rate, hourly_rate, monthly_rate, percent_salary_hike,
        stock_option_level, business_travel, overtime, distance_from_home, total_working_years,
        num_companies_worked, training_times_last_year, years_in_current_role,
        years_since_last_promotion, years_with_curr_manager, attrition)
    SELECT c.employee_number, TRIM(c.first_name), TRIM(c.last_name), c.email_clean,
           c.gender_clean, c.date_of_birth, c.marital_status, c.education, c.education_field, c.city,
           c.hire_date, c.termination_date, c.department_id, c.job_role_id, c.job_level,
           c.monthly_income, c.daily_rate, c.hourly_rate, c.monthly_rate, c.percent_salary_hike,
           c.stock_option_level, c.business_travel, (c.overtime = 'Yes'), c.distance_from_home,
           c.total_working_years, c.num_companies_worked, c.training_times_last_year,
           c.years_in_current_role, c.years_since_last_promotion, c.years_with_curr_manager,
           (c.attrition = 'Yes')
    FROM tmp_emp_clean c
    WHERE c.reject_reason IS NULL
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.employees e WHERE e.employee_number = c.employee_number);

    -- 4. Engagement survey (1:1 with employees) ----------------------------
    INSERT INTO hr_oltp.employee_engagement (
        employee_id, environment_satisfaction, job_satisfaction, relationship_satisfaction,
        work_life_balance, job_involvement, surveyed_on)
    SELECT e.employee_id, c.environment_satisfaction, c.job_satisfaction, c.relationship_satisfaction,
           c.work_life_balance, c.job_involvement, DATE(c.extracted_at)
    FROM tmp_emp_clean c
    JOIN hr_oltp.employees e ON e.employee_number = c.employee_number
    WHERE c.reject_reason IS NULL
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.employee_engagement g WHERE g.employee_id = e.employee_id);

    DROP TEMPORARY TABLE tmp_emp_clean;

    -- 5. Employee history (the SCD2 source) --------------------------------
    INSERT INTO hr_staging.stg_rejects (entity, source_key, reason)
    WITH ranked AS (
        SELECT h.*, ROW_NUMBER() OVER (PARTITION BY h.employee_number, h.effective_start ORDER BY h.version_no) AS rn
        FROM hr_staging.stg_employee_history h
    )
    SELECT 'employee_history', CONCAT(h.employee_number, '@', h.effective_start),
           CASE WHEN e.employee_id   IS NULL THEN 'UNKNOWN_EMPLOYEE'
                WHEN d.department_id IS NULL THEN 'UNKNOWN_DEPARTMENT'
                ELSE 'UNKNOWN_ROLE' END
    FROM ranked h
    LEFT JOIN hr_oltp.employees   e ON e.employee_number = h.employee_number
    LEFT JOIN hr_oltp.departments d ON d.department_name = TRIM(h.department)
    LEFT JOIN hr_oltp.job_roles   j ON j.department_id = d.department_id AND j.role_name = TRIM(h.job_role)
    WHERE h.rn = 1 AND (e.employee_id IS NULL OR d.department_id IS NULL OR j.job_role_id IS NULL);

    INSERT INTO hr_oltp.employee_history (
        employee_id, department_id, job_role_id, job_level, monthly_income,
        effective_start, effective_end, is_current, change_reason)
    WITH ranked AS (
        SELECT h.*, ROW_NUMBER() OVER (PARTITION BY h.employee_number, h.effective_start ORDER BY h.version_no) AS rn
        FROM hr_staging.stg_employee_history h
    )
    SELECT e.employee_id, d.department_id, j.job_role_id, h.job_level, h.monthly_income,
           h.effective_start, h.effective_end, h.is_current, h.change_reason
    FROM ranked h
    JOIN hr_oltp.employees   e ON e.employee_number = h.employee_number
    JOIN hr_oltp.departments d ON d.department_name = TRIM(h.department)
    JOIN hr_oltp.job_roles   j ON j.department_id = d.department_id AND j.role_name = TRIM(h.job_role)
    WHERE h.rn = 1
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.employee_history x
                      WHERE x.employee_id = e.employee_id AND x.effective_start = h.effective_start);

    -- 6. Projects ----------------------------------------------------------
    INSERT INTO hr_staging.stg_rejects (entity, source_key, reason)
    SELECT DISTINCT 'projects', p.project_code, 'UNKNOWN_DEPARTMENT'
    FROM hr_staging.stg_projects p
    LEFT JOIN hr_oltp.departments d ON d.department_name = TRIM(p.department)
    WHERE d.department_id IS NULL;

    INSERT INTO hr_oltp.projects (project_code, project_name, department_id, client_name,
                                  start_date, end_date, budget, status, priority)
    WITH ranked AS (
        SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.project_code ORDER BY p.start_date) AS rn
        FROM hr_staging.stg_projects p
    )
    SELECT r.project_code, TRIM(r.project_name), d.department_id, r.client_name,
           r.start_date, r.end_date, r.budget, r.status, r.priority
    FROM ranked r
    JOIN hr_oltp.departments d ON d.department_name = TRIM(r.department)
    WHERE r.rn = 1
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.projects x WHERE x.project_code = r.project_code);

    -- 7. Assignments -------------------------------------------------------
    INSERT INTO hr_staging.stg_rejects (entity, source_key, reason)
    WITH ranked AS (
        SELECT a.*, ROW_NUMBER() OVER (PARTITION BY a.employee_number, a.project_code, a.start_date) AS rn
        FROM hr_staging.stg_assignments a
    )
    SELECT 'assignments', CONCAT(a.employee_number, '/', a.project_code, '@', a.start_date),
           IF(e.employee_id IS NULL, 'UNKNOWN_EMPLOYEE', 'UNKNOWN_PROJECT')
    FROM ranked a
    LEFT JOIN hr_oltp.employees e ON e.employee_number = a.employee_number
    LEFT JOIN hr_oltp.projects  p ON p.project_code = a.project_code
    WHERE a.rn = 1 AND (e.employee_id IS NULL OR p.project_id IS NULL);

    INSERT INTO hr_oltp.assignments (employee_id, project_id, role_on_project, allocation_pct,
                                     start_date, end_date)
    WITH ranked AS (
        SELECT a.*, ROW_NUMBER() OVER (PARTITION BY a.employee_number, a.project_code, a.start_date) AS rn
        FROM hr_staging.stg_assignments a
    )
    SELECT e.employee_id, p.project_id, a.role_on_project, a.allocation_pct, a.start_date, a.end_date
    FROM ranked a
    JOIN hr_oltp.employees e ON e.employee_number = a.employee_number
    JOIN hr_oltp.projects  p ON p.project_code = a.project_code
    WHERE a.rn = 1
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.assignments x
                      WHERE x.employee_id = e.employee_id AND x.project_id = p.project_id
                        AND x.start_date = a.start_date);

    -- 8. Reviews: drop exact duplicates, keep the source review_id ---------
    INSERT INTO hr_staging.stg_rejects (entity, source_key, reason)
    WITH ranked AS (
        SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.review_id ORDER BY r.review_date) AS rn
        FROM hr_staging.stg_reviews r
    )
    SELECT 'reviews', CAST(r.review_id AS CHAR),
           CASE WHEN e.employee_id IS NULL                       THEN 'UNKNOWN_EMPLOYEE'
                WHEN r.performance_score NOT BETWEEN 1 AND 5      THEN 'SCORE_OUT_OF_RANGE'
                WHEN r.rating NOT BETWEEN 1 AND 4                 THEN 'RATING_OUT_OF_RANGE'
                ELSE 'GOALS_OUT_OF_RANGE' END
    FROM ranked r
    LEFT JOIN hr_oltp.employees e ON e.employee_number = r.employee_number
    WHERE r.rn = 1
      AND (e.employee_id IS NULL OR r.performance_score NOT BETWEEN 1 AND 5
           OR r.rating NOT BETWEEN 1 AND 4 OR r.goals_met_pct NOT BETWEEN 0 AND 100);

    INSERT INTO hr_oltp.reviews (review_id, employee_id, reviewer_id, project_id, review_date,
                                 review_year, performance_score, rating, goals_met_pct, comments)
    WITH ranked AS (
        SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.review_id ORDER BY r.review_date) AS rn
        FROM hr_staging.stg_reviews r
    )
    SELECT r.review_id, e.employee_id, rv.employee_id, p.project_id, r.review_date, r.review_year,
           r.performance_score, r.rating, r.goals_met_pct, r.comments
    FROM ranked r
    JOIN hr_oltp.employees e       ON e.employee_number  = r.employee_number
    LEFT JOIN hr_oltp.employees rv ON rv.employee_number = r.reviewer_employee_number
    LEFT JOIN hr_oltp.projects  p  ON p.project_code     = r.project_code
    WHERE r.rn = 1
      AND r.performance_score BETWEEN 1 AND 5
      AND r.rating BETWEEN 1 AND 4
      AND r.goals_met_pct BETWEEN 0 AND 100
      AND NOT EXISTS (SELECT 1 FROM hr_oltp.reviews x WHERE x.review_id = r.review_id);

    COMMIT;

    -- Row counts and rejects so the caller can see what landed.
    SELECT 'departments' AS table_name, COUNT(*) AS row_count FROM hr_oltp.departments
    UNION ALL SELECT 'job_roles',           COUNT(*) FROM hr_oltp.job_roles
    UNION ALL SELECT 'employees',           COUNT(*) FROM hr_oltp.employees
    UNION ALL SELECT 'employee_engagement', COUNT(*) FROM hr_oltp.employee_engagement
    UNION ALL SELECT 'employee_history',    COUNT(*) FROM hr_oltp.employee_history
    UNION ALL SELECT 'projects',            COUNT(*) FROM hr_oltp.projects
    UNION ALL SELECT 'assignments',         COUNT(*) FROM hr_oltp.assignments
    UNION ALL SELECT 'reviews',             COUNT(*) FROM hr_oltp.reviews
    UNION ALL SELECT 'stg_rejects',         COUNT(*) FROM hr_staging.stg_rejects;
END $$

DELIMITER ;
