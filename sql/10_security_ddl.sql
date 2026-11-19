-- =====================================================================
-- 10  Authentication, authorization and security audit (hr_oltp)
--
-- Run after 03_oltp_ddl.sql because users.employee_id references employees
-- and user_departments.department_id references departments.
-- Safe to re-run: tables are created if missing and seeds use INSERT IGNORE.
-- This file does not create users or assign an initial administrator.
-- =====================================================================
USE hr_oltp;

-- ---------------------------------------------------------------------
-- Roles: users may hold multiple roles.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    role_id       SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_name     VARCHAR(40) NOT NULL,
    description   VARCHAR(255),
    PRIMARY KEY (role_id),
    UNIQUE KEY uq_role_name (role_name)
) ENGINE=InnoDB;

INSERT IGNORE INTO roles (role_name, description) VALUES
    ('SYSTEM_ADMIN', 'Platform and user administration'),
    ('HR_ADMIN', 'Employee and HR transaction administration'),
    ('HR_MANAGER', 'HR oversight and approved HR operations'),
    ('DEPARTMENT_MANAGER', 'Departmental people and project management'),
    ('EMPLOYEE', 'Personal employee access');

-- ---------------------------------------------------------------------
-- Local authentication accounts. SSO fields are intentionally deferred
-- until the optional production SSO phase. password_hash is nullable so
-- accounts can later be provisioned through a trusted identity provider.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email            VARCHAR(150) NOT NULL,
    display_name     VARCHAR(125) NOT NULL,
    password_hash    VARCHAR(255) NULL,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    employee_id      INT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    failed_logins    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    locked_until     DATETIME NULL,
    last_login_at    DATETIME NULL,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                     ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_users_email (email),
    KEY ix_users_employee (employee_id),
    CONSTRAINT fk_users_employee
        FOREIGN KEY (employee_id)
        REFERENCES employees (employee_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- User-to-role grants. granted_by is nullable for controlled bootstrap
-- provisioning; subsequent grants should record the acting administrator.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_roles (
    user_id      BIGINT UNSIGNED NOT NULL,
    role_id      SMALLINT UNSIGNED NOT NULL,
    granted_by   BIGINT UNSIGNED NULL,
    granted_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    KEY ix_user_roles_role (role_id),
    CONSTRAINT fk_user_roles_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role
        FOREIGN KEY (role_id) REFERENCES roles (role_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_granter
        FOREIGN KEY (granted_by) REFERENCES users (user_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Department scope. A department manager's permissions must still be
-- intersected with these assignments in every OLTP and warehouse query.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_departments (
    user_id        BIGINT UNSIGNED NOT NULL,
    department_id  INT NOT NULL,
    can_manage     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (user_id, department_id),
    KEY ix_user_departments_department (department_id),
    CONSTRAINT fk_user_departments_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_user_departments_department
        FOREIGN KEY (department_id) REFERENCES departments (department_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Permission catalogue. Include the self/all and reconciliation keys used
-- by the permission matrix, in addition to the initial key list.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    permission_id   SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    permission_key  VARCHAR(80) NOT NULL,
    description     VARCHAR(255),
    PRIMARY KEY (permission_id),
    UNIQUE KEY uq_permission_key (permission_key)
) ENGINE=InnoDB;

INSERT IGNORE INTO permissions (permission_key, description) VALUES
    ('employee.view', 'View employee records allowed by the principal scope'),
    ('employee.view_all', 'View employee records across all departments'),
    ('employee.view_department', 'View employee records in assigned departments'),
    ('employee.view_self', 'View the signed-in employee profile'),
    ('employee.create', 'Create employee records'),
    ('employee.transfer', 'Transfer employees between departments or roles'),
    ('employee.terminate', 'Terminate employee records'),
    ('project.create', 'Create projects within the authorized scope'),
    ('project.assign', 'Assign employees to projects within the authorized scope'),
    ('review.create', 'Create performance reviews within the authorized scope'),
    ('review.view_department', 'View reviews in assigned departments'),
    ('review.view_self', 'View the signed-in employee reviews'),
    ('analytics.view_all', 'View organization-wide analytics'),
    ('analytics.view_department', 'View analytics for assigned departments'),
    ('etl.run', 'Execute warehouse ETL'),
    ('reconciliation.run', 'Execute data reconciliation'),
    ('user.manage', 'Create, update and deactivate user accounts'),
    ('role.manage', 'Grant and revoke user roles'),
    ('audit.view', 'View security audit records');

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id        SMALLINT UNSIGNED NOT NULL,
    permission_id  SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    KEY ix_role_permissions_permission (permission_id),
    CONSTRAINT fk_role_permissions_role
        FOREIGN KEY (role_id) REFERENCES roles (role_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_permission
        FOREIGN KEY (permission_id) REFERENCES permissions (permission_id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- Baseline grants derived from auth.txt's permission matrix.
-- Department-scoped grants are not sufficient by themselves: application
-- queries must also enforce user_departments and object-level ownership.
-- SYSTEM_ADMIN is intentionally not granted HR transaction write access.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
JOIN permissions p ON p.permission_key IN (
    'employee.view_all', 'analytics.view_all', 'etl.run',
    'reconciliation.run', 'user.manage', 'role.manage', 'audit.view'
)
WHERE r.role_name = 'SYSTEM_ADMIN';

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
JOIN permissions p ON p.permission_key IN (
    'employee.view', 'employee.view_all', 'employee.view_department',
    'employee.create', 'employee.transfer', 'employee.terminate',
    'project.create', 'project.assign', 'review.create',
    'review.view_department', 'analytics.view_all', 'analytics.view_department'
)
WHERE r.role_name = 'HR_ADMIN';

-- HR_MANAGER's all-department view and write grants follow the supplied
-- matrix. The approved-department restriction described elsewhere in auth.txt
-- still needs a product decision before manager-level enforcement is coded.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
JOIN permissions p ON p.permission_key IN (
    'employee.view', 'employee.view_all', 'employee.view_department',
    'employee.create', 'employee.transfer',
    'project.create', 'project.assign', 'review.create',
    'review.view_department', 'analytics.view_all', 'analytics.view_department'
)
WHERE r.role_name = 'HR_MANAGER';

-- The specification labels project/review operations as "Limited" for
-- department managers. These grants enable the capability; implementation
-- must enforce department and project membership on every operation.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
JOIN permissions p ON p.permission_key IN (
    'employee.view_department', 'project.create', 'project.assign',
    'review.create', 'review.view_department', 'analytics.view_department'
)
WHERE r.role_name = 'DEPARTMENT_MANAGER';

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id
FROM roles r
JOIN permissions p ON p.permission_key IN (
    'employee.view_self', 'review.view_self'
)
WHERE r.role_name = 'EMPLOYEE';

-- ---------------------------------------------------------------------
-- Security audit trail. Do not write passwords, hashes, session secrets or
-- other authentication credentials into details.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS security_audit_log (
    audit_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id         BIGINT UNSIGNED NULL,
    action          VARCHAR(80) NOT NULL,
    resource_type   VARCHAR(60) NULL,
    resource_id     VARCHAR(100) NULL,
    outcome         ENUM('SUCCESS','DENIED','FAILED') NOT NULL,
    ip_address      VARCHAR(45) NULL,
    details         VARCHAR(500) NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    KEY ix_audit_user_time (user_id, created_at),
    KEY ix_audit_action_time (action, created_at),
    CONSTRAINT fk_audit_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON DELETE SET NULL
) ENGINE=InnoDB;
