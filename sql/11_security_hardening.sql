-- Security hardening migration. Safe to run repeatedly on an existing database.
USE hr_oltp;
SET @has_must_change_password = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = 'hr_oltp' AND table_name = 'users' AND column_name = 'must_change_password'
);
SET @ddl = IF(@has_must_change_password = 0,
    'ALTER TABLE hr_oltp.users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE AFTER password_hash',
    'SELECT 1');
PREPARE security_stmt FROM @ddl;
EXECUTE security_stmt;
DEALLOCATE PREPARE security_stmt;
