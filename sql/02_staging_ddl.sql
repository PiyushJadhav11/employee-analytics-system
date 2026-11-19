-- =====================================================================
-- 02  Staging schema — one table per synthesized CSV.
-- No primary keys or FKs on purpose: staging must accept duplicates and
-- messy values so the OLTP load (05) can show how they are cleaned.
-- Idempotent: CREATE ... IF NOT EXISTS, so re-running never drops data.
-- (Use `python scripts/setup_database.py --reset` to start over.)
-- Free-text columns that arrive dirty (gender, department) are VARCHAR.
-- =====================================================================
USE hr_staging;

SET SESSION sql_require_primary_key = 0;

CREATE TABLE IF NOT EXISTS stg_departments (
    department_code  VARCHAR(20),
    department_name  VARCHAR(100),
    cost_center      VARCHAR(20),
    location         VARCHAR(60)
);

CREATE TABLE IF NOT EXISTS stg_job_roles (
    department  VARCHAR(100),
    job_role    VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS stg_employees (
    employee_number             INT,
    first_name                  VARCHAR(60),
    last_name                   VARCHAR(60),
    email                       VARCHAR(150),
    gender                      VARCHAR(20),
    date_of_birth               DATE,
    age                         INT,
    attrition                   VARCHAR(5),
    business_travel             VARCHAR(30),
    daily_rate                  INT,
    department                  VARCHAR(100),
    distance_from_home          INT,
    education                   INT,
    education_field             VARCHAR(60),
    environment_satisfaction    INT,
    hourly_rate                 INT,
    job_involvement             INT,
    job_level                   INT,
    job_role                    VARCHAR(100),
    job_satisfaction            INT,
    marital_status              VARCHAR(20),
    monthly_income              DECIMAL(10,2),
    monthly_rate                INT,
    num_companies_worked        INT,
    overtime                    VARCHAR(5),
    percent_salary_hike         INT,
    performance_rating          INT,
    relationship_satisfaction   INT,
    stock_option_level          INT,
    total_working_years         INT,
    training_times_last_year    INT,
    work_life_balance           INT,
    years_at_company            INT,
    years_in_current_role       INT,
    years_since_last_promotion  INT,
    years_with_curr_manager     INT,
    city                        VARCHAR(80),
    hire_date                   DATE,
    termination_date            DATE,
    extracted_at                DATETIME,
    INDEX ix_stg_emp_number (employee_number)
);

CREATE TABLE IF NOT EXISTS stg_employee_history (
    employee_number  INT,
    version_no       INT,
    department       VARCHAR(100),
    job_role         VARCHAR(100),
    job_level        INT,
    monthly_income   DECIMAL(10,2),
    effective_start  DATE,
    effective_end    DATE,
    is_current       TINYINT,
    change_reason    VARCHAR(30),
    INDEX ix_stg_hist_emp (employee_number)
);

CREATE TABLE IF NOT EXISTS stg_projects (
    project_code  VARCHAR(20),
    project_name  VARCHAR(150),
    department    VARCHAR(100),
    client_name   VARCHAR(150),
    start_date    DATE,
    end_date      DATE,
    budget        DECIMAL(14,2),
    status        VARCHAR(20),
    priority      VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS stg_assignments (
    employee_number  INT,
    project_code     VARCHAR(20),
    role_on_project  VARCHAR(40),
    allocation_pct   INT,
    start_date       DATE,
    end_date         DATE
);

CREATE TABLE IF NOT EXISTS stg_reviews (
    review_id                 BIGINT,
    employee_number           INT,
    reviewer_employee_number  INT,
    project_code              VARCHAR(20),
    review_date               DATE,
    review_year               INT,
    performance_score         DECIMAL(4,2),
    rating                    INT,
    goals_met_pct             DECIMAL(5,1),
    comments                  VARCHAR(255),
    INDEX ix_stg_rev_id (review_id)
);

-- ---------------------------------------------------------------------
-- Load bookkeeping (written by scripts/load_staging.py)
-- One row per CSV per load attempt. Makes the staging load idempotent
-- (a file whose sha256 is already LOADED is skipped) and reconcilable
-- (CSV rows / control total vs. what actually landed in the table).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS load_batches (
    batch_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id          CHAR(36)     NOT NULL,
    table_name      VARCHAR(64)  NOT NULL,
    file_name       VARCHAR(255) NOT NULL,
    file_sha256     CHAR(64)     NOT NULL,
    csv_rows        INT          NOT NULL,
    staged_rows     INT          NULL,
    control_column  VARCHAR(64)  NULL,
    csv_control     DECIMAL(20,2) NULL,
    staged_control  DECIMAL(20,2) NULL,
    status          ENUM('LOADED','SKIPPED','FAILED','MISMATCH') NOT NULL,
    message         VARCHAR(255) NULL,
    started_at      DATETIME(3)  NOT NULL,
    finished_at     DATETIME(3)  NOT NULL,
    INDEX ix_batch_table (table_name, status, batch_id)
);

-- Rows sp_load_from_staging could not load, and why. Rebuilt on every run,
-- so it always describes the latest load. Reconciliation requires
--   distinct staged keys = keys present in OLTP + keys rejected here.
CREATE TABLE IF NOT EXISTS stg_rejects (
    reject_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity       VARCHAR(30)  NOT NULL,      -- employees, reviews, ...
    source_key   VARCHAR(100) NOT NULL,      -- natural key from the CSV
    reason       VARCHAR(40)  NOT NULL,
    rejected_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_reject_entity (entity, reason),
    INDEX ix_reject_key (entity, source_key)
);
