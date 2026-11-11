-- =====================================================================
-- 08  Reconciliation — prove each layer matches the one before it
--
--   CALL hr_dw.sp_reconcile(NULL, NULL);             -- all layers, new run id
--   CALL hr_dw.sp_reconcile(NULL, 'STAGING_OLTP');   -- one layer
--
-- Layers (the CSV -> staging layer is checked in Python by load_staging.py,
-- because only Python can read the files; it writes to the same log):
--
--   STAGING_OLTP  every distinct staged key is either in OLTP or in stg_rejects
--                 ("accounted for"), and immutable values survived the trip
--                 (CRC32 fingerprints, control totals)
--   OLTP_DW       row counts and control totals match between OLTP and the
--                 warehouse; every review is in the fact table
--   DW_INTEGRITY  SCD2 rules hold: one current version per employee, no gaps,
--                 no overlaps, current version equals OLTP, every fact points at
--                 the version valid on its review date
--
-- Status: PASS (matches), FAIL (must be fixed), WARN (explainable difference),
-- INFO (reported for context), SKIP (layer has no data, e.g. staging emptied).
-- Results go to hr_dw.reconciliation_log and are returned as a result set.
-- Read-only apart from the log, so it is safe to run at any time.
-- =====================================================================
USE hr_dw;

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_rec_add $$
CREATE PROCEDURE sp_rec_add(IN p_run CHAR(36), IN p_layer VARCHAR(20), IN p_check VARCHAR(80),
                            IN p_expected DECIMAL(24,2), IN p_actual DECIMAL(24,2),
                            IN p_on_mismatch VARCHAR(4), IN p_details VARCHAR(255))
BEGIN
    INSERT INTO hr_dw.reconciliation_log (run_id, layer, check_name, expected_value, actual_value, status, details)
    VALUES (p_run, p_layer, p_check, p_expected, p_actual,
            CASE WHEN p_on_mismatch IN ('INFO', 'SKIP') THEN p_on_mismatch
                 WHEN p_expected <=> p_actual          THEN 'PASS'
                 ELSE p_on_mismatch END,
            p_details);
END $$

DROP PROCEDURE IF EXISTS sp_reconcile $$
CREATE PROCEDURE sp_reconcile(IN p_run_id CHAR(36), IN p_layer VARCHAR(20))
BEGIN
    DECLARE v_run CHAR(36) DEFAULT COALESCE(p_run_id, UUID());
    DECLARE v_exp, v_act DECIMAL(24,2);

    -- ================================================================ STAGING -> OLTP
    IF p_layer IS NULL OR p_layer = 'STAGING_OLTP' THEN
      IF (SELECT COUNT(*) FROM hr_staging.stg_employees) = 0 THEN
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'staging is empty', NULL, NULL, 'SKIP',
                        'Nothing staged; run scripts/load_staging.py to reconcile this layer');
      ELSE
        -- employees: every distinct staged employee_number is loaded or rejected
        SELECT COUNT(*),
               SUM(EXISTS (SELECT 1 FROM hr_oltp.employees e WHERE e.employee_number = s.employee_number)
                   OR EXISTS (SELECT 1 FROM hr_staging.stg_rejects r
                              WHERE r.entity = 'employees' AND r.source_key = CAST(s.employee_number AS CHAR)))
          INTO v_exp, v_act
        FROM (SELECT DISTINCT employee_number FROM hr_staging.stg_employees WHERE employee_number IS NOT NULL) s;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'employees: staged keys accounted for', v_exp, v_act, 'FAIL',
                        'expected = distinct staged employee_number; actual = in OLTP or in stg_rejects');

        -- employees: immutable attributes survived cleaning (row-level fingerprint)
        WITH latest AS (
            SELECT s.employee_number, s.email, s.date_of_birth, s.hire_date,
                   ROW_NUMBER() OVER (PARTITION BY s.employee_number ORDER BY s.extracted_at DESC) AS rn
            FROM hr_staging.stg_employees s
        )
        SELECT SUM(CRC32(CONCAT_WS('|', l.employee_number, LOWER(TRIM(l.email)), l.date_of_birth, l.hire_date))),
               SUM(CRC32(CONCAT_WS('|', e.employee_number, e.email, e.date_of_birth, e.hire_date)))
          INTO v_exp, v_act
        FROM latest l
        JOIN hr_oltp.employees e ON e.employee_number = l.employee_number
        WHERE l.rn = 1;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'employees: fingerprint of immutable columns', v_exp, v_act, 'FAIL',
                        'SUM(CRC32(number|email|dob|hire_date)); a mismatch means OLTP holds different people under the same numbers');

        -- employee_history
        SELECT COUNT(*),
               SUM(EXISTS (SELECT 1 FROM hr_oltp.employee_history x
                           JOIN hr_oltp.employees e ON e.employee_id = x.employee_id
                           WHERE e.employee_number = s.employee_number AND x.effective_start = s.effective_start)
                   OR EXISTS (SELECT 1 FROM hr_staging.stg_rejects r
                              WHERE r.entity = 'employee_history'
                                AND r.source_key = CONCAT(s.employee_number, '@', s.effective_start)))
          INTO v_exp, v_act
        FROM (SELECT DISTINCT employee_number, effective_start FROM hr_staging.stg_employee_history) s;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'employee_history: staged keys accounted for', v_exp, v_act, 'FAIL',
                        'key = (employee_number, effective_start)');

        WITH st AS (
            SELECT h.employee_number, h.effective_start, h.monthly_income,
                   ROW_NUMBER() OVER (PARTITION BY h.employee_number, h.effective_start ORDER BY h.version_no) AS rn
            FROM hr_staging.stg_employee_history h
        )
        SELECT SUM(st.monthly_income), SUM(x.monthly_income) INTO v_exp, v_act
        FROM st
        JOIN hr_oltp.employees e         ON e.employee_number = st.employee_number
        JOIN hr_oltp.employee_history x  ON x.employee_id = e.employee_id AND x.effective_start = st.effective_start
        WHERE st.rn = 1;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'employee_history: control total monthly_income', v_exp, v_act, 'FAIL',
                        'sum over versions present in both layers');

        -- projects
        SELECT COUNT(*),
               SUM(EXISTS (SELECT 1 FROM hr_oltp.projects p WHERE p.project_code = s.project_code)
                   OR EXISTS (SELECT 1 FROM hr_staging.stg_rejects r
                              WHERE r.entity = 'projects' AND r.source_key = s.project_code))
          INTO v_exp, v_act
        FROM (SELECT DISTINCT project_code FROM hr_staging.stg_projects) s;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'projects: staged keys accounted for', v_exp, v_act, 'FAIL', NULL);

        -- assignments
        SELECT COUNT(*),
               SUM(EXISTS (SELECT 1 FROM hr_oltp.assignments a
                           JOIN hr_oltp.employees e ON e.employee_id = a.employee_id
                           JOIN hr_oltp.projects  p ON p.project_id  = a.project_id
                           WHERE e.employee_number = s.employee_number AND p.project_code = s.project_code
                             AND a.start_date = s.start_date)
                   OR EXISTS (SELECT 1 FROM hr_staging.stg_rejects r
                              WHERE r.entity = 'assignments'
                                AND r.source_key = CONCAT(s.employee_number, '/', s.project_code, '@', s.start_date)))
          INTO v_exp, v_act
        FROM (SELECT DISTINCT employee_number, project_code, start_date FROM hr_staging.stg_assignments) s;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'assignments: staged keys accounted for', v_exp, v_act, 'FAIL',
                        'key = (employee_number, project_code, start_date)');

        -- reviews
        SELECT COUNT(*),
               SUM(EXISTS (SELECT 1 FROM hr_oltp.reviews x WHERE x.review_id = s.review_id)
                   OR EXISTS (SELECT 1 FROM hr_staging.stg_rejects r
                              WHERE r.entity = 'reviews' AND r.source_key = CAST(s.review_id AS CHAR)))
          INTO v_exp, v_act
        FROM (SELECT DISTINCT review_id FROM hr_staging.stg_reviews) s;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'reviews: staged keys accounted for', v_exp, v_act, 'FAIL', NULL);

        WITH st AS (
            SELECT r.review_id, r.performance_score,
                   ROW_NUMBER() OVER (PARTITION BY r.review_id ORDER BY r.review_date) AS rn
            FROM hr_staging.stg_reviews r
        )
        SELECT SUM(st.performance_score), SUM(x.performance_score) INTO v_exp, v_act
        FROM st JOIN hr_oltp.reviews x ON x.review_id = st.review_id
        WHERE st.rn = 1;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'reviews: control total performance_score', v_exp, v_act, 'FAIL',
                        'a mismatch means a review_id already in OLTP holds a different review');

        -- context: duplicates removed and rows rejected
        SELECT COUNT(*) - COUNT(DISTINCT employee_number) INTO v_act FROM hr_staging.stg_employees;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'employees: duplicate rows removed', NULL, v_act, 'INFO',
                        'older extracts dropped by ROW_NUMBER() ... ORDER BY extracted_at DESC');
        SELECT COUNT(*) - COUNT(DISTINCT review_id) INTO v_act FROM hr_staging.stg_reviews;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'reviews: duplicate rows removed', NULL, v_act, 'INFO', NULL);
        SELECT COUNT(*) INTO v_act FROM hr_staging.stg_rejects;
        CALL sp_rec_add(v_run, 'STAGING_OLTP', 'rows rejected (see hr_staging.stg_rejects)', 0, v_act, 'WARN',
                        'rejected rows are accounted for, but someone should look at why');
      END IF;
    END IF;

    -- ================================================================ OLTP -> DW
    IF p_layer IS NULL OR p_layer = 'OLTP_DW' THEN
        SELECT (SELECT COUNT(*) FROM hr_oltp.departments),
               (SELECT COUNT(*) FROM hr_dw.dim_department WHERE department_sk <> -1) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'dim_department rows = departments', v_exp, v_act, 'FAIL', 'excludes unknown member -1');

        SELECT (SELECT COUNT(*) FROM hr_oltp.projects),
               (SELECT COUNT(*) FROM hr_dw.dim_project WHERE project_sk <> -1) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'dim_project rows = projects', v_exp, v_act, 'FAIL', 'excludes unknown member -1');

        SELECT (SELECT COUNT(*) FROM hr_oltp.employees),
               (SELECT COUNT(DISTINCT employee_id) FROM hr_dw.dim_employee) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'dim_employee employees = employees', v_exp, v_act, 'FAIL', NULL);

        SELECT (SELECT COUNT(*) FROM hr_oltp.employee_history),
               (SELECT COUNT(*) FROM hr_dw.dim_employee) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'dim_employee versions = employee_history rows', v_exp, v_act, 'WARN',
                        'differs only if employee attributes changed without a history row (ATTRIBUTE_CHANGE)');

        SELECT (SELECT COUNT(*) FROM hr_oltp.reviews),
               (SELECT COUNT(*) FROM hr_dw.fact_performance_reviews) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'fact rows = reviews', v_exp, v_act, 'FAIL', NULL);

        SELECT (SELECT SUM(performance_score) FROM hr_oltp.reviews),
               (SELECT SUM(performance_score) FROM hr_dw.fact_performance_reviews) INTO v_exp, v_act;
        CALL sp_rec_add(v_run, 'OLTP_DW', 'fact control total performance_score', v_exp, v_act, 'FAIL', NULL);

        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM hr_oltp.reviews r
        WHERE NOT EXISTS (SELECT 1 FROM hr_dw.fact_performance_reviews f WHERE f.review_id = r.review_id);
        CALL sp_rec_add(v_run, 'OLTP_DW', 'reviews missing from fact', v_exp, v_act, 'FAIL',
                        'usually a review dated outside every employee version, or the ETL has not run');

        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM hr_dw.fact_performance_reviews f
        WHERE NOT EXISTS (SELECT 1 FROM hr_oltp.reviews r WHERE r.review_id = f.review_id);
        CALL sp_rec_add(v_run, 'OLTP_DW', 'orphan facts (review deleted in OLTP)', v_exp, v_act, 'FAIL',
                        'the fact load is insert-only; delete these after confirming the OLTP delete was intended');

        -- ============================================================ DW integrity (SCD2)
        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM (SELECT employee_id FROM hr_dw.dim_employee GROUP BY employee_id HAVING SUM(is_current) <> 1) x;
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'employees without exactly one current version', v_exp, v_act, 'FAIL', NULL);

        WITH v AS (
            SELECT employee_id, start_date, end_date,
                   LEAD(start_date) OVER (PARTITION BY employee_id ORDER BY start_date) AS next_start
            FROM hr_dw.dim_employee
        )
        SELECT 0, SUM(next_start <= end_date) INTO v_exp, v_act FROM v WHERE next_start IS NOT NULL;
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'overlapping versions', v_exp, COALESCE(v_act, 0), 'FAIL', NULL);

        WITH v AS (
            SELECT employee_id, start_date, end_date,
                   LEAD(start_date) OVER (PARTITION BY employee_id ORDER BY start_date) AS next_start
            FROM hr_dw.dim_employee
        )
        SELECT 0, SUM(next_start > end_date + INTERVAL 1 DAY) INTO v_exp, v_act FROM v WHERE next_start IS NOT NULL;
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'gaps between versions', v_exp, COALESCE(v_act, 0), 'FAIL',
                        'a version must end the day before the next one starts');

        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM hr_oltp.employees e
        JOIN hr_oltp.departments d ON d.department_id = e.department_id
        JOIN hr_oltp.job_roles   j ON j.job_role_id   = e.job_role_id
        JOIN hr_dw.dim_employee  x ON x.employee_id   = e.employee_id AND x.is_current = 1
        WHERE x.scd2_hash <> SHA2(CONCAT_WS('|', d.department_name, j.role_name, e.job_level, e.monthly_income), 256);
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'current version differs from OLTP', v_exp, v_act, 'FAIL',
                        'dept/role/level/income of the current dim row vs hr_oltp.employees; run the ETL');

        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM hr_dw.fact_performance_reviews f
        JOIN hr_dw.dim_employee e ON e.employee_sk = f.employee_sk
        JOIN hr_dw.dim_date     d ON d.date_sk     = f.date_sk
        WHERE d.full_date NOT BETWEEN e.start_date AND e.end_date;
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'facts pointing at a version not valid on review date', v_exp, v_act, 'FAIL', NULL);

        SELECT 0, COUNT(*) INTO v_exp, v_act
        FROM hr_dw.fact_performance_reviews f
        JOIN hr_dw.dim_employee   e ON e.employee_sk   = f.employee_sk
        JOIN hr_dw.dim_department d ON d.department_sk = f.department_sk
        WHERE d.department_name <> e.department_name;
        CALL sp_rec_add(v_run, 'DW_INTEGRITY', 'fact department differs from its employee version', v_exp, v_act, 'FAIL', NULL);
    END IF;

    SELECT run_id, layer, check_name, expected_value, actual_value, status, details
    FROM hr_dw.reconciliation_log WHERE run_id = v_run ORDER BY log_id;
END $$

DELIMITER ;
