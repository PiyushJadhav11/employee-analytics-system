-- =====================================================================
-- 01  Schemas
--   hr_staging : raw synthesized CSVs, loaded as-is (dirty data included)
--   hr_oltp    : normalized application database (3NF) the Streamlit forms write to
--   hr_dw      : star-schema data warehouse the dashboards read from
-- Requires MySQL 8.0+ (CTEs, window functions, recursive CTEs, CHECK constraints)
-- =====================================================================
CREATE DATABASE IF NOT EXISTS hr_staging CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS hr_oltp    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS hr_dw      CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
