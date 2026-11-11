-- =====================================================================
-- 06  OLTP -> Data Warehouse ETL (stored procedures)
--
--   sp_load_dim_date(start, end)             recursive CTE calendar
--   sp_load_dim_department()                 SCD 1 upsert
--   sp_load_dim_project()                    SCD 1 upsert
--   sp_load_dim_employee(employee_id|NULL)   SCD 2  (NULL = all employees)
--   sp_load_fact_performance_reviews(id|NULL) point-in-time lookup of the employee version
--   sp_run_full_etl()                        runs all of the above and writes etl_audit_log
--
-- Every procedure leaves its affected-row count in @etl_rows for the audit log.
--
-- Idempotency and safety:
--   * Re-running is a no-op when nothing changed (NOT EXISTS / hash compare /
--     unique review_id), verified by running twice and getting 0 rows.
--   * The multi-statement loads (dim_employee, fact) run in one transaction:
--     a failure between "expire old version" and "insert new version" rolls
--     both back, so an employee can never be left without a current row.
--   * GET_LOCK('hr_dw_etl') serialises loads, so the app's per-employee sync
--     and a full ETL run cannot interleave and write the same version twice.
--     MySQL named locks are re-entrant per session, so sp_run_full_etl can
--     hold the lock while calling the inner procedures.
-- =====================================================================
USE hr_dw;

DELIMITER $$

-- ---------------------------------------------------------------- helpers
DROP FUNCTION IF EXISTS fn_salary_band $$
CREATE FUNCTION fn_salary_band(p_income DECIMAL(10,2)) RETURNS VARCHAR(20)
DETERMINISTIC NO SQL
BEGIN
    RETURN CASE
        WHEN p_income <  3000 THEN 'A: < 3k'
        WHEN p_income <  6000 THEN 'B: 3k-6k'
        WHEN p_income < 10000 THEN 'C: 6k-10k'
        WHEN p_income < 15000 THEN 'D: 10k-15k'
        ELSE                       'E: 15k+'
    END;
END $$

DROP FUNCTION IF EXISTS fn_age_band $$
CREATE FUNCTION fn_age_band(p_dob DATE, p_as_of DATE) RETURNS VARCHAR(10)
DETERMINISTIC NO SQL
BEGIN
    DECLARE v_age INT DEFAULT TIMESTAMPDIFF(YEAR, p_dob, p_as_of);
    RETURN CASE
        WHEN v_age < 25 THEN '< 25'
        WHEN v_age < 35 THEN '25-34'
        WHEN v_age < 45 THEN '35-44'
        WHEN v_age < 55 THEN '45-54'
        ELSE                 '55+'
    END;
END $$

-- ---------------------------------------------------------------- dim_date
DROP PROCEDURE IF EXISTS sp_load_dim_date $$
CREATE PROCEDURE sp_load_dim_date(IN p_start DATE, IN p_end DATE)
BEGIN
    SET SESSION cte_max_recursion_depth = 100000;

    INSERT INTO hr_dw.dim_date (date_sk, full_date, day_of_month, day_name, day_of_week, week_of_year,
                                month_num, month_name, quarter, year, is_weekend)
    WITH RECURSIVE calendar (dt) AS (
        SELECT p_start
        UNION ALL
        SELECT dt + INTERVAL 1 DAY FROM calendar WHERE dt < p_end
    )
    SELECT CAST(DATE_FORMAT(dt, '%Y%m%d') AS UNSIGNED), dt, DAY(dt), DAYNAME(dt), DAYOFWEEK(dt),
           WEEK(dt, 3), MONTH(dt), MONTHNAME(dt), QUARTER(dt), YEAR(dt), DAYOFWEEK(dt) IN (1, 7)
    FROM calendar c
    WHERE NOT EXISTS (SELECT 1 FROM hr_dw.dim_date x WHERE x.full_date = c.dt);

    SET @etl_rows = ROW_COUNT();
END $$

-- ---------------------------------------------------------------- dim_department (SCD 1)
DROP PROCEDURE IF EXISTS sp_load_dim_department $$
CREATE PROCEDURE sp_load_dim_department()
BEGIN
    DECLARE v_ins INT DEFAULT 0;

    INSERT INTO hr_dw.dim_department (department_id, department_code, department_name, cost_center, location)
    SELECT d.department_id, d.department_code, d.department_name, d.cost_center, d.location
    FROM hr_oltp.departments d
    WHERE NOT EXISTS (SELECT 1 FROM hr_dw.dim_department x WHERE x.department_id = d.department_id);
    SET v_ins = ROW_COUNT();

    UPDATE hr_dw.dim_department x
    JOIN hr_oltp.departments d ON d.department_id = x.department_id
    SET x.department_code = d.department_code,
        x.department_name = d.department_name,
        x.cost_center     = d.cost_center,
        x.location        = d.location
    WHERE NOT (x.department_name <=> d.department_name AND x.department_code <=> d.department_code
               AND x.cost_center <=> d.cost_center AND x.location <=> d.location);

    SET @etl_rows = v_ins + ROW_COUNT();
END $$

-- ---------------------------------------------------------------- dim_project (SCD 1)
DROP PROCEDURE IF EXISTS sp_load_dim_project $$
CREATE PROCEDURE sp_load_dim_project()
BEGIN
    DECLARE v_ins INT DEFAULT 0;

    INSERT INTO hr_dw.dim_project (project_id, project_code, project_name, department_name, client_name,
                                   status, priority, budget, start_date, end_date, duration_days)
    SELECT p.project_id, p.project_code, p.project_name, d.department_name, p.client_name,
           p.status, p.priority, p.budget, p.start_date, p.end_date, DATEDIFF(p.end_date, p.start_date)
    FROM hr_oltp.projects p
    JOIN hr_oltp.departments d ON d.department_id = p.department_id
    WHERE NOT EXISTS (SELECT 1 FROM hr_dw.dim_project x WHERE x.project_id = p.project_id);
    SET v_ins = ROW_COUNT();

    UPDATE hr_dw.dim_project x
    JOIN hr_oltp.projects p    ON p.project_id = x.project_id
    JOIN hr_oltp.departments d ON d.department_id = p.department_id
    SET x.project_name = p.project_name, x.department_name = d.department_name,
        x.client_name = p.client_name, x.status = p.status, x.priority = p.priority,
        x.budget = p.budget, x.start_date = p.start_date, x.end_date = p.end_date,
        x.duration_days = DATEDIFF(p.end_date, p.start_date)
    WHERE NOT (x.project_name <=> p.project_name AND x.status <=> p.status AND x.priority <=> p.priority
               AND x.budget <=> p.budget AND x.end_date <=> p.end_date
               AND x.department_name <=> d.department_name AND x.client_name <=> p.client_name);

    SET @etl_rows = v_ins + ROW_COUNT();
END $$

-- ---------------------------------------------------------------- dim_employee (SCD 2)
--
-- (a) Employees never seen by the warehouse: copy every version from
--     hr_oltp.employee_history, preserving its dates (historical backfill).
-- (b) Employees with no history rows at all: one current row from hire_date.
-- (c) Employees already in the warehouse whose Type 2 attributes changed
--     (scd2_hash differs from the current row): close the current row the
--     day before the change and insert a new current row. The change date is
--     taken from the new employee_history row when there is one, else today.
-- (d) Type 1 attributes: overwrite on every version when scd1_hash differs.
DROP PROCEDURE IF EXISTS sp_load_dim_employee $$
CREATE PROCEDURE sp_load_dim_employee(IN p_employee_id INT)
BEGIN
    DECLARE v_rows INT DEFAULT 0;
    DECLARE v_today DATE DEFAULT CURDATE();
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        DROP TEMPORARY TABLE IF EXISTS tmp_src_employee, tmp_new_employee, tmp_changed;
        DO RELEASE_LOCK('hr_dw_etl');
        RESIGNAL;
    END;

    IF COALESCE(GET_LOCK('hr_dw_etl', 120), 0) <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Another warehouse load is running (lock hr_dw_etl); try again';
    END IF;
    START TRANSACTION;

    -- Current source state, with hashes, as a keyed temp table.
    DROP TEMPORARY TABLE IF EXISTS tmp_src_employee;
    CREATE TEMPORARY TABLE tmp_src_employee (PRIMARY KEY (employee_id)) AS
    SELECT src.*,
           SHA2(CONCAT_WS('|', src.department_name, src.job_role, src.job_level, src.monthly_income), 256) AS scd2_hash,
           SHA2(CONCAT_WS('|', src.full_name, src.gender, IFNULL(src.termination_date, '-'), src.attrition_flag,
                          src.overtime_flag, src.business_travel, src.distance_from_home,
                          IFNULL(src.job_satisfaction, '-'), IFNULL(src.environment_satisfaction, '-'),
                          IFNULL(src.work_life_balance, '-'), IFNULL(src.years_since_last_promotion, '-'),
                          src.age_band, src.marital_status, src.education_field), 256)          AS scd1_hash
    FROM (
        SELECT e.employee_id, e.employee_number,
               CONCAT(e.first_name, ' ', e.last_name)          AS full_name,
               e.gender, e.date_of_birth,
               hr_dw.fn_age_band(e.date_of_birth, v_today)    AS age_band,
               e.marital_status, e.education_field, e.hire_date, e.termination_date,
               e.attrition                                    AS attrition_flag,
               e.overtime                                     AS overtime_flag,
               e.business_travel, e.distance_from_home,
               g.job_satisfaction, g.environment_satisfaction, g.work_life_balance,
               e.years_since_last_promotion,
               d.department_name, j.role_name AS job_role, e.job_level, e.monthly_income,
               h.effective_start AS hist_start, h.change_reason AS hist_reason
        FROM hr_oltp.employees e
        JOIN hr_oltp.departments d ON d.department_id = e.department_id
        JOIN hr_oltp.job_roles   j ON j.job_role_id   = e.job_role_id
        LEFT JOIN hr_oltp.employee_engagement g ON g.employee_id = e.employee_id
        LEFT JOIN hr_oltp.employee_history    h ON h.employee_id = e.employee_id AND h.is_current = 1
        WHERE p_employee_id IS NULL OR e.employee_id = p_employee_id
    ) AS src;

    DROP TEMPORARY TABLE IF EXISTS tmp_new_employee;
    CREATE TEMPORARY TABLE tmp_new_employee (PRIMARY KEY (employee_id)) AS
    SELECT s.employee_id FROM tmp_src_employee s
    WHERE NOT EXISTS (SELECT 1 FROM hr_dw.dim_employee x WHERE x.employee_id = s.employee_id);

    -- (a) historical backfill for new employees
    INSERT INTO hr_dw.dim_employee (
        employee_id, employee_number, full_name, gender, date_of_birth, age_band, marital_status,
        education_field, hire_date, termination_date, attrition_flag, overtime_flag, business_travel,
        distance_from_home, job_satisfaction, environment_satisfaction, work_life_balance,
        years_since_last_promotion, department_name, job_role, job_level, monthly_income, salary_band,
        start_date, end_date, is_current, version_no, change_reason, scd2_hash, scd1_hash)
    WITH versions AS (
        SELECT h.employee_id, d.department_name, j.role_name AS job_role, h.job_level, h.monthly_income,
               h.effective_start, h.effective_end, h.is_current, h.change_reason,
               ROW_NUMBER() OVER (PARTITION BY h.employee_id ORDER BY h.effective_start) AS version_no
        FROM hr_oltp.employee_history h
        JOIN tmp_new_employee n    ON n.employee_id   = h.employee_id
        JOIN hr_oltp.departments d ON d.department_id = h.department_id
        JOIN hr_oltp.job_roles   j ON j.job_role_id   = h.job_role_id
    )
    SELECT s.employee_id, s.employee_number, s.full_name, s.gender, s.date_of_birth, s.age_band,
           s.marital_status, s.education_field, s.hire_date, s.termination_date, s.attrition_flag,
           s.overtime_flag, s.business_travel, s.distance_from_home, s.job_satisfaction,
           s.environment_satisfaction, s.work_life_balance, s.years_since_last_promotion,
           v.department_name, v.job_role, v.job_level, v.monthly_income, hr_dw.fn_salary_band(v.monthly_income),
           v.effective_start, v.effective_end, v.is_current, v.version_no, v.change_reason,
           SHA2(CONCAT_WS('|', v.department_name, v.job_role, v.job_level, v.monthly_income), 256),
           s.scd1_hash
    FROM versions v
    JOIN tmp_src_employee s ON s.employee_id = v.employee_id;
    SET v_rows = v_rows + ROW_COUNT();

    -- (b) new employees with no history at all
    INSERT INTO hr_dw.dim_employee (
        employee_id, employee_number, full_name, gender, date_of_birth, age_band, marital_status,
        education_field, hire_date, termination_date, attrition_flag, overtime_flag, business_travel,
        distance_from_home, job_satisfaction, environment_satisfaction, work_life_balance,
        years_since_last_promotion, department_name, job_role, job_level, monthly_income, salary_band,
        start_date, end_date, is_current, version_no, change_reason, scd2_hash, scd1_hash)
    SELECT s.employee_id, s.employee_number, s.full_name, s.gender, s.date_of_birth, s.age_band,
           s.marital_status, s.education_field, s.hire_date, s.termination_date, s.attrition_flag,
           s.overtime_flag, s.business_travel, s.distance_from_home, s.job_satisfaction,
           s.environment_satisfaction, s.work_life_balance, s.years_since_last_promotion,
           s.department_name, s.job_role, s.job_level, s.monthly_income, hr_dw.fn_salary_band(s.monthly_income),
           s.hire_date, '9999-12-31', TRUE, 1, 'HIRE', s.scd2_hash, s.scd1_hash
    FROM tmp_src_employee s
    JOIN tmp_new_employee n ON n.employee_id = s.employee_id
    WHERE NOT EXISTS (SELECT 1 FROM hr_oltp.employee_history h WHERE h.employee_id = s.employee_id);
    SET v_rows = v_rows + ROW_COUNT();

    -- (c) Type 2 change detection
    DROP TEMPORARY TABLE IF EXISTS tmp_changed;
    CREATE TEMPORARY TABLE tmp_changed (PRIMARY KEY (employee_sk)) AS
    SELECT x.employee_sk, x.employee_id, x.version_no,
           CASE WHEN s.hist_start > x.start_date THEN s.hist_start
                ELSE GREATEST(v_today, x.start_date + INTERVAL 1 DAY) END        AS effective_from,
           CASE WHEN s.hist_start > x.start_date THEN s.hist_reason
                ELSE 'ATTRIBUTE_CHANGE' END                                      AS change_reason
    FROM hr_dw.dim_employee x
    JOIN tmp_src_employee s ON s.employee_id = x.employee_id
    WHERE x.is_current = 1
      AND x.scd2_hash <> s.scd2_hash;

    UPDATE hr_dw.dim_employee x
    JOIN tmp_changed c ON c.employee_sk = x.employee_sk
    SET x.end_date   = c.effective_from - INTERVAL 1 DAY,
        x.is_current = FALSE;

    INSERT INTO hr_dw.dim_employee (
        employee_id, employee_number, full_name, gender, date_of_birth, age_band, marital_status,
        education_field, hire_date, termination_date, attrition_flag, overtime_flag, business_travel,
        distance_from_home, job_satisfaction, environment_satisfaction, work_life_balance,
        years_since_last_promotion, department_name, job_role, job_level, monthly_income, salary_band,
        start_date, end_date, is_current, version_no, change_reason, scd2_hash, scd1_hash)
    SELECT s.employee_id, s.employee_number, s.full_name, s.gender, s.date_of_birth, s.age_band,
           s.marital_status, s.education_field, s.hire_date, s.termination_date, s.attrition_flag,
           s.overtime_flag, s.business_travel, s.distance_from_home, s.job_satisfaction,
           s.environment_satisfaction, s.work_life_balance, s.years_since_last_promotion,
           s.department_name, s.job_role, s.job_level, s.monthly_income, hr_dw.fn_salary_band(s.monthly_income),
           c.effective_from, '9999-12-31', TRUE, c.version_no + 1, c.change_reason, s.scd2_hash, s.scd1_hash
    FROM tmp_changed c
    JOIN tmp_src_employee s ON s.employee_id = c.employee_id;
    SET v_rows = v_rows + ROW_COUNT();

    -- (d) Type 1 overwrite on all versions
    UPDATE hr_dw.dim_employee x
    JOIN tmp_src_employee s ON s.employee_id = x.employee_id
    SET x.full_name = s.full_name, x.gender = s.gender, x.age_band = s.age_band,
        x.marital_status = s.marital_status, x.education_field = s.education_field,
        x.termination_date = s.termination_date, x.attrition_flag = s.attrition_flag,
        x.overtime_flag = s.overtime_flag, x.business_travel = s.business_travel,
        x.distance_from_home = s.distance_from_home, x.job_satisfaction = s.job_satisfaction,
        x.environment_satisfaction = s.environment_satisfaction, x.work_life_balance = s.work_life_balance,
        x.years_since_last_promotion = s.years_since_last_promotion, x.scd1_hash = s.scd1_hash
    WHERE x.scd1_hash <> s.scd1_hash;
    SET v_rows = v_rows + ROW_COUNT();

    COMMIT;
    DROP TEMPORARY TABLE IF EXISTS tmp_src_employee, tmp_new_employee, tmp_changed;
    DO RELEASE_LOCK('hr_dw_etl');
    SET @etl_rows = v_rows;
END $$

-- ---------------------------------------------------------------- fact_performance_reviews
--
-- employee_sk is the version of the employee that was valid ON review_date
-- (review_date BETWEEN start_date AND end_date). A review written in 2022,
-- before a 2024 transfer, therefore stays attributed to the 2022 department.
DROP PROCEDURE IF EXISTS sp_load_fact_performance_reviews $$
CREATE PROCEDURE sp_load_fact_performance_reviews(IN p_employee_id INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        DO RELEASE_LOCK('hr_dw_etl');
        RESIGNAL;
    END;

    IF COALESCE(GET_LOCK('hr_dw_etl', 120), 0) <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Another warehouse load is running (lock hr_dw_etl); try again';
    END IF;
    START TRANSACTION;
    INSERT INTO hr_dw.fact_performance_reviews (
        review_id, employee_sk, department_sk, project_sk, date_sk, review_year,
        performance_score, rating, goals_met_pct, score_change_vs_prev, is_top_rating)
    WITH scored AS (
        -- LAG runs over the employee's full review history, so the delta is right
        -- even when only one new review is being loaded.
        SELECT r.review_id, r.employee_id, r.project_id, r.review_date, r.review_year,
               r.performance_score, r.rating, r.goals_met_pct,
               r.performance_score - LAG(r.performance_score)
                   OVER (PARTITION BY r.employee_id ORDER BY r.review_date, r.review_id) AS score_change
        FROM hr_oltp.reviews r
        WHERE p_employee_id IS NULL OR r.employee_id = p_employee_id
    ),
    pending AS (
        SELECT s.* FROM scored s
        WHERE NOT EXISTS (SELECT 1 FROM hr_dw.fact_performance_reviews f WHERE f.review_id = s.review_id)
    )
    SELECT p.review_id, de.employee_sk, COALESCE(dd.department_sk, -1), COALESCE(dp.project_sk, -1),
           CAST(DATE_FORMAT(p.review_date, '%Y%m%d') AS UNSIGNED), p.review_year,
           p.performance_score, p.rating, p.goals_met_pct, p.score_change, p.rating = 4
    FROM pending p
    JOIN hr_dw.dim_employee de
         ON de.employee_id = p.employee_id
        AND p.review_date BETWEEN de.start_date AND de.end_date
    LEFT JOIN hr_dw.dim_department dd ON dd.department_name = de.department_name
    LEFT JOIN hr_dw.dim_project    dp ON dp.project_id      = p.project_id;

    SET @etl_rows = ROW_COUNT();
    COMMIT;
    DO RELEASE_LOCK('hr_dw_etl');
END $$

-- ---------------------------------------------------------------- orchestration
DROP PROCEDURE IF EXISTS sp_log_step $$
CREATE PROCEDURE sp_log_step(IN p_run_id VARCHAR(36), IN p_step VARCHAR(60), IN p_started DATETIME(3))
BEGIN
    INSERT INTO hr_dw.etl_audit_log (run_id, step_name, rows_affected, started_at, finished_at)
    VALUES (p_run_id, p_step, @etl_rows, p_started, NOW(3));
END $$

DROP PROCEDURE IF EXISTS sp_run_full_etl $$
CREATE PROCEDURE sp_run_full_etl()
BEGIN
    DECLARE v_run VARCHAR(36) DEFAULT UUID();
    DECLARE v_t DATETIME(3);
    DECLARE v_min DATE;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        DO RELEASE_LOCK('hr_dw_etl');
        RESIGNAL;
    END;

    IF COALESCE(GET_LOCK('hr_dw_etl', 120), 0) <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Another warehouse load is running (lock hr_dw_etl); try again';
    END IF;

    SELECT LEAST(COALESCE(MIN(hire_date), '2000-01-01'), '2000-01-01') INTO v_min FROM hr_oltp.employees;

    SET v_t = NOW(3); CALL hr_dw.sp_load_dim_date(MAKEDATE(YEAR(v_min), 1), '2030-12-31');
    CALL hr_dw.sp_log_step(v_run, 'dim_date', v_t);

    SET v_t = NOW(3); CALL hr_dw.sp_load_dim_department();
    CALL hr_dw.sp_log_step(v_run, 'dim_department', v_t);

    SET v_t = NOW(3); CALL hr_dw.sp_load_dim_project();
    CALL hr_dw.sp_log_step(v_run, 'dim_project', v_t);

    SET v_t = NOW(3); CALL hr_dw.sp_load_dim_employee(NULL);
    CALL hr_dw.sp_log_step(v_run, 'dim_employee (SCD2)', v_t);

    SET v_t = NOW(3); CALL hr_dw.sp_load_fact_performance_reviews(NULL);
    CALL hr_dw.sp_log_step(v_run, 'fact_performance_reviews', v_t);

    DO RELEASE_LOCK('hr_dw_etl');

    -- Result set 1: what each step wrote
    SELECT run_id, step_name, rows_affected,
           ROUND(TIMESTAMPDIFF(MICROSECOND, started_at, finished_at) / 1e6, 2) AS seconds
    FROM hr_dw.etl_audit_log WHERE run_id = v_run ORDER BY log_id;

    -- Result set 2: reconciliation of every layer for this run (sql/08)
    CALL hr_dw.sp_reconcile(v_run, NULL);
END $$

DELIMITER ;
