-- =====================================================================
-- 04  Data warehouse — star schema
--
--                    dim_date
--                       │
--   dim_employee ── fact_performance_reviews ── dim_project
--     (SCD 2)           │
--                 dim_department
--
-- * Every dimension has a surrogate key (*_sk) independent of the OLTP id.
-- * dim_employee is SCD Type 2 on department, job_role, job_level and
--   monthly_income (start_date / end_date / is_current). Other attributes
--   (name, satisfaction, attrition) are Type 1: overwritten on every version.
-- * Unknown members use surrogate key -1 so facts never need a NULL FK.
-- * Idempotent: CREATE ... IF NOT EXISTS, so re-running never drops data.
-- =====================================================================
USE hr_dw;


CREATE TABLE IF NOT EXISTS dim_date (
    date_sk       INT PRIMARY KEY,               -- smart key YYYYMMDD
    full_date     DATE NOT NULL UNIQUE,
    day_of_month  TINYINT NOT NULL,
    day_name      VARCHAR(10) NOT NULL,
    day_of_week   TINYINT NOT NULL,              -- 1 = Sunday (MySQL DAYOFWEEK)
    week_of_year  TINYINT NOT NULL,
    month_num     TINYINT NOT NULL,
    month_name    VARCHAR(10) NOT NULL,
    quarter       TINYINT NOT NULL,
    year          SMALLINT NOT NULL,
    is_weekend    BOOLEAN NOT NULL,
    INDEX ix_date_year (year, month_num)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_department (
    department_sk    INT AUTO_INCREMENT PRIMARY KEY,
    department_id    INT NOT NULL UNIQUE,         -- natural key from hr_oltp
    department_code  VARCHAR(10),
    department_name  VARCHAR(60) NOT NULL,
    cost_center      VARCHAR(20),
    location         VARCHAR(60),
    loaded_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_dimdept_name (department_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_project (
    project_sk       INT AUTO_INCREMENT PRIMARY KEY,
    project_id       INT NOT NULL UNIQUE,
    project_code     VARCHAR(20),
    project_name     VARCHAR(150),
    department_name  VARCHAR(60),
    client_name      VARCHAR(150),
    status           VARCHAR(20),
    priority         VARCHAR(20),
    budget           DECIMAL(14,2),
    start_date       DATE,
    end_date         DATE,
    duration_days    INT,
    loaded_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dim_employee (
    employee_sk                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id                 INT NOT NULL,              -- natural key; repeats once per version
    employee_number             INT NOT NULL,
    -- Type 1 attributes (overwritten on all versions)
    full_name                   VARCHAR(125),
    gender                      VARCHAR(10),
    date_of_birth               DATE,
    age_band                    VARCHAR(10),
    marital_status              VARCHAR(10),
    education_field             VARCHAR(60),
    hire_date                   DATE,
    termination_date            DATE,
    attrition_flag              BOOLEAN,
    overtime_flag               BOOLEAN,
    business_travel             VARCHAR(20),
    distance_from_home          SMALLINT,
    job_satisfaction            TINYINT,
    environment_satisfaction    TINYINT,
    work_life_balance           TINYINT,
    years_since_last_promotion  TINYINT,
    -- Type 2 attributes (a change creates a new row)
    department_name             VARCHAR(60) NOT NULL,
    job_role                    VARCHAR(60) NOT NULL,
    job_level                   TINYINT NOT NULL,
    monthly_income              DECIMAL(10,2) NOT NULL,
    salary_band                 VARCHAR(20),
    -- SCD 2 housekeeping
    start_date                  DATE NOT NULL,
    end_date                    DATE NOT NULL DEFAULT '9999-12-31',
    is_current                  BOOLEAN NOT NULL DEFAULT TRUE,
    version_no                  SMALLINT NOT NULL DEFAULT 1,
    change_reason               VARCHAR(30),
    scd2_hash                   CHAR(64) NOT NULL,         -- SHA-256 of the Type 2 attributes
    scd1_hash                   CHAR(64) NOT NULL,         -- SHA-256 of the Type 1 attributes
    loaded_at                   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_dimemp_version UNIQUE (employee_id, start_date),
    INDEX ix_dimemp_current (employee_id, is_current),
    INDEX ix_dimemp_range (employee_id, start_date, end_date),
    INDEX ix_dimemp_dept (department_name, is_current)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fact_performance_reviews (
    review_sk             BIGINT AUTO_INCREMENT PRIMARY KEY,
    review_id             BIGINT NOT NULL UNIQUE,      -- degenerate dimension (OLTP id)
    employee_sk           BIGINT NOT NULL,             -- the employee VERSION valid on review_date
    department_sk         INT    NOT NULL,             -- department as of review_date (via that version)
    project_sk            INT    NOT NULL,
    date_sk               INT    NOT NULL,
    review_year           SMALLINT NOT NULL,
    performance_score     DECIMAL(3,2) NOT NULL,
    rating                TINYINT NOT NULL,
    goals_met_pct         DECIMAL(5,1),
    score_change_vs_prev  DECIMAL(4,2) NULL,           -- LAG() over the employee's prior review
    is_top_rating         BOOLEAN NOT NULL,
    loaded_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_fact_emp  FOREIGN KEY (employee_sk)   REFERENCES dim_employee (employee_sk),
    CONSTRAINT fk_fact_dept FOREIGN KEY (department_sk) REFERENCES dim_department (department_sk),
    CONSTRAINT fk_fact_proj FOREIGN KEY (project_sk)    REFERENCES dim_project (project_sk),
    CONSTRAINT fk_fact_date FOREIGN KEY (date_sk)       REFERENCES dim_date (date_sk),
    INDEX ix_fact_year_dept (review_year, department_sk),
    INDEX ix_fact_emp (employee_sk)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS etl_audit_log (
    log_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id         VARCHAR(36) NOT NULL,
    step_name      VARCHAR(60) NOT NULL,
    rows_affected  INT,
    started_at     DATETIME(3) NOT NULL,
    finished_at    DATETIME(3) NOT NULL,
    INDEX ix_audit_run (run_id)
) ENGINE=InnoDB;

-- Unknown members (surrogate key -1). INSERT IGNORE keeps re-runs harmless.
INSERT IGNORE INTO dim_department (department_sk, department_id, department_code, department_name)
VALUES (-1, -1, 'UNK', 'Unknown');
INSERT IGNORE INTO dim_project (project_sk, project_id, project_code, project_name, department_name, status)
VALUES (-1, -1, 'NONE', 'Not on a project', 'Unknown', 'N/A');

-- Reconciliation results: one row per check per run (sql/08_reconciliation.sql,
-- plus the CSV -> staging checks written by scripts/load_staging.py).
CREATE TABLE IF NOT EXISTS reconciliation_log (
    log_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id          CHAR(36)     NOT NULL,
    layer           VARCHAR(20)  NOT NULL,     -- CSV_STAGING | STAGING_OLTP | OLTP_DW | DW_INTEGRITY
    check_name      VARCHAR(80)  NOT NULL,
    expected_value  DECIMAL(24,2) NULL,
    actual_value    DECIMAL(24,2) NULL,
    status          ENUM('PASS','FAIL','WARN','INFO','SKIP') NOT NULL,
    details         VARCHAR(255) NULL,
    checked_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX ix_recon_run (run_id),
    INDEX ix_recon_status (status, checked_at)
) ENGINE=InnoDB;
