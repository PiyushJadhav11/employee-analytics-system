-- =====================================================================
-- 03  OLTP schema (3NF) — the application's system of record.
--
--   departments 1─* job_roles 1─* employees 1─1 employee_engagement
--   employees   1─* employee_history   (every version of dept/role/level/salary)
--   departments 1─* projects 1─* assignments *─1 employees
--   employees   1─* reviews  (as reviewee and as reviewer), reviews *─1 projects
--
-- Idempotent: CREATE ... IF NOT EXISTS, so re-running never drops data.
--
-- Derived values (age, tenure) are NOT stored; they are computed from
-- date_of_birth / hire_date so they can never go stale.
-- =====================================================================
USE hr_oltp;


CREATE TABLE IF NOT EXISTS departments (
    department_id    INT AUTO_INCREMENT PRIMARY KEY,
    department_code  VARCHAR(10)  NOT NULL UNIQUE,
    department_name  VARCHAR(60)  NOT NULL UNIQUE,
    cost_center      VARCHAR(20),
    location         VARCHAR(60),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS job_roles (
    job_role_id    INT AUTO_INCREMENT PRIMARY KEY,
    department_id  INT NOT NULL,
    role_name      VARCHAR(60) NOT NULL,
    CONSTRAINT uq_job_role UNIQUE (department_id, role_name),
    CONSTRAINT fk_role_dept FOREIGN KEY (department_id) REFERENCES departments (department_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS employees (
    employee_id                 INT AUTO_INCREMENT PRIMARY KEY,
    employee_number             INT          NOT NULL UNIQUE,
    first_name                  VARCHAR(60)  NOT NULL,
    last_name                   VARCHAR(60)  NOT NULL,
    email                       VARCHAR(150) NOT NULL UNIQUE,
    gender                      ENUM('Male','Female') NOT NULL,
    date_of_birth               DATE         NOT NULL,
    marital_status              ENUM('Single','Married','Divorced'),
    education                   TINYINT      CHECK (education BETWEEN 1 AND 5),
    education_field             VARCHAR(60),
    city                        VARCHAR(80),
    hire_date                   DATE         NOT NULL,
    termination_date            DATE         NULL,
    department_id               INT          NOT NULL,
    job_role_id                 INT          NOT NULL,
    job_level                   TINYINT      NOT NULL CHECK (job_level BETWEEN 1 AND 5),
    monthly_income              DECIMAL(10,2) NOT NULL CHECK (monthly_income > 0),
    daily_rate                  INT,
    hourly_rate                 INT,
    monthly_rate                INT,
    percent_salary_hike         TINYINT,
    stock_option_level          TINYINT      CHECK (stock_option_level BETWEEN 0 AND 3),
    business_travel             ENUM('Non-Travel','Travel_Rarely','Travel_Frequently'),
    overtime                    BOOLEAN      NOT NULL DEFAULT FALSE,
    distance_from_home          SMALLINT,
    total_working_years         TINYINT,
    num_companies_worked        TINYINT,
    training_times_last_year    TINYINT,
    years_in_current_role       TINYINT,
    years_since_last_promotion  TINYINT,
    years_with_curr_manager     TINYINT,
    attrition                   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT chk_emp_dates CHECK (termination_date IS NULL OR termination_date >= hire_date),
    CONSTRAINT fk_emp_dept FOREIGN KEY (department_id) REFERENCES departments (department_id),
    CONSTRAINT fk_emp_role FOREIGN KEY (job_role_id)   REFERENCES job_roles (job_role_id),
    INDEX ix_emp_dept (department_id),
    INDEX ix_emp_name (last_name, first_name)
) ENGINE=InnoDB;

-- Survey answers (1-4 / 1-5 scales) live apart from the core employee record:
-- they are refreshed by engagement surveys, not by HR transactions.
CREATE TABLE IF NOT EXISTS employee_engagement (
    employee_id                INT PRIMARY KEY,
    environment_satisfaction   TINYINT CHECK (environment_satisfaction BETWEEN 1 AND 4),
    job_satisfaction           TINYINT CHECK (job_satisfaction BETWEEN 1 AND 4),
    relationship_satisfaction  TINYINT CHECK (relationship_satisfaction BETWEEN 1 AND 4),
    work_life_balance          TINYINT CHECK (work_life_balance BETWEEN 1 AND 4),
    job_involvement            TINYINT CHECK (job_involvement BETWEEN 1 AND 4),
    surveyed_on                DATE,
    CONSTRAINT fk_eng_emp FOREIGN KEY (employee_id) REFERENCES employees (employee_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Source of truth for SCD Type 2: one row per version of the tracked attributes.
-- Versions of an employee tile their tenure: end = next start - 1 day; open end = 9999-12-31.
CREATE TABLE IF NOT EXISTS employee_history (
    history_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id      INT          NOT NULL,
    department_id    INT          NOT NULL,
    job_role_id      INT          NOT NULL,
    job_level        TINYINT      NOT NULL,
    monthly_income   DECIMAL(10,2) NOT NULL,
    effective_start  DATE         NOT NULL,
    effective_end    DATE         NOT NULL DEFAULT '9999-12-31',
    is_current       BOOLEAN      NOT NULL DEFAULT TRUE,
    change_reason    VARCHAR(30)  NOT NULL,
    recorded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_hist_version UNIQUE (employee_id, effective_start),
    CONSTRAINT chk_hist_dates CHECK (effective_end >= effective_start),
    CONSTRAINT fk_hist_emp  FOREIGN KEY (employee_id)   REFERENCES employees (employee_id) ON DELETE CASCADE,
    CONSTRAINT fk_hist_dept FOREIGN KEY (department_id) REFERENCES departments (department_id),
    CONSTRAINT fk_hist_role FOREIGN KEY (job_role_id)   REFERENCES job_roles (job_role_id),
    INDEX ix_hist_current (employee_id, is_current)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS projects (
    project_id     INT AUTO_INCREMENT PRIMARY KEY,
    project_code   VARCHAR(20)  NOT NULL UNIQUE,
    project_name   VARCHAR(150) NOT NULL,
    department_id  INT          NOT NULL,
    client_name    VARCHAR(150),
    start_date     DATE         NOT NULL,
    end_date       DATE,
    budget         DECIMAL(14,2) CHECK (budget >= 0),
    status         ENUM('Planned','Active','On Hold','Completed','Cancelled') NOT NULL DEFAULT 'Planned',
    priority       ENUM('Low','Medium','High','Critical') NOT NULL DEFAULT 'Medium',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_proj_dates CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT fk_proj_dept FOREIGN KEY (department_id) REFERENCES departments (department_id),
    INDEX ix_proj_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id      INT     NOT NULL,
    project_id       INT     NOT NULL,
    role_on_project  VARCHAR(40) NOT NULL,
    allocation_pct   TINYINT NOT NULL CHECK (allocation_pct BETWEEN 1 AND 100),
    start_date       DATE    NOT NULL,
    end_date         DATE,
    CONSTRAINT uq_assignment UNIQUE (employee_id, project_id, start_date),
    CONSTRAINT chk_asg_dates CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT fk_asg_emp  FOREIGN KEY (employee_id) REFERENCES employees (employee_id) ON DELETE CASCADE,
    CONSTRAINT fk_asg_proj FOREIGN KEY (project_id)  REFERENCES projects (project_id),
    INDEX ix_asg_project (project_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS reviews (
    review_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    employee_id        INT          NOT NULL,
    reviewer_id        INT          NULL,
    project_id         INT          NULL,
    review_date        DATE         NOT NULL,
    review_year        SMALLINT     NOT NULL,
    performance_score  DECIMAL(3,2) NOT NULL CHECK (performance_score BETWEEN 1 AND 5),
    rating             TINYINT      NOT NULL CHECK (rating BETWEEN 1 AND 4),
    goals_met_pct      DECIMAL(5,1) CHECK (goals_met_pct BETWEEN 0 AND 100),
    comments           VARCHAR(255),
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rev_emp      FOREIGN KEY (employee_id) REFERENCES employees (employee_id) ON DELETE CASCADE,
    CONSTRAINT fk_rev_reviewer FOREIGN KEY (reviewer_id) REFERENCES employees (employee_id) ON DELETE SET NULL,
    CONSTRAINT fk_rev_proj     FOREIGN KEY (project_id)  REFERENCES projects (project_id),
    INDEX ix_rev_emp_date (employee_id, review_date),
    INDEX ix_rev_year (review_year)
) ENGINE=InnoDB;

-- Idempotency keys for application writes. A form submission carries a key;
-- the manager inserts it in the SAME transaction as the write. A retry or
-- double-click with the same key hits the primary key, and the manager returns
-- the original result instead of writing twice. If the write fails, the
-- transaction rolls back and the key goes with it, so the retry can succeed.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    request_key  CHAR(36)    PRIMARY KEY,
    operation    VARCHAR(40) NOT NULL,
    entity_id    BIGINT      NULL,
    response     VARCHAR(255) NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_idem_created (created_at)
) ENGINE=InnoDB;
