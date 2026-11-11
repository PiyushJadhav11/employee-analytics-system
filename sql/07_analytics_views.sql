-- =====================================================================
-- 07  Analytical views over the star schema (used by the dashboard and
--     handy for ad-hoc queries in MySQL Workbench)
-- =====================================================================
USE hr_dw;

-- Year-over-year performance per department, plus an "All departments" line.
-- LAG() gives the previous year's average so the % change is a single expression.
CREATE OR REPLACE VIEW vw_yoy_performance AS
WITH yearly AS (
    SELECT dd.department_name, f.review_year,
           AVG(f.performance_score)   AS avg_score,
           AVG(f.goals_met_pct)       AS avg_goals_met_pct,
           AVG(f.is_top_rating) * 100 AS top_rating_pct,
           COUNT(*)                   AS reviews
    FROM fact_performance_reviews f
    JOIN dim_department dd ON dd.department_sk = f.department_sk
    GROUP BY dd.department_name, f.review_year
    UNION ALL
    SELECT 'All departments', f.review_year, AVG(f.performance_score), AVG(f.goals_met_pct),
           AVG(f.is_top_rating) * 100, COUNT(*)
    FROM fact_performance_reviews f
    GROUP BY f.review_year
)
SELECT y.department_name, y.review_year, ROUND(y.avg_score, 3) AS avg_score,
       ROUND(y.avg_goals_met_pct, 1) AS avg_goals_met_pct, ROUND(y.top_rating_pct, 1) AS top_rating_pct,
       y.reviews,
       ROUND(LAG(y.avg_score) OVER w, 3) AS prev_year_avg_score,
       ROUND(100 * (y.avg_score - LAG(y.avg_score) OVER w) / LAG(y.avg_score) OVER w, 2) AS yoy_change_pct
FROM yearly y
WINDOW w AS (PARTITION BY y.department_name ORDER BY y.review_year);

-- Top performers: employees ranked inside (department, year) with DENSE_RANK().
-- Department is the one the employee was in when reviewed (SCD2 version on the fact).
CREATE OR REPLACE VIEW vw_top_performers AS
WITH employee_year AS (
    SELECT de.employee_id, f.review_year, dd.department_name,
           AVG(f.performance_score) AS avg_score,
           AVG(f.goals_met_pct)     AS avg_goals_met_pct,
           COUNT(*)                 AS reviews
    FROM fact_performance_reviews f
    JOIN dim_employee   de ON de.employee_sk   = f.employee_sk
    JOIN dim_department dd ON dd.department_sk = f.department_sk
    GROUP BY de.employee_id, f.review_year, dd.department_name
),
ranked AS (
    SELECT ey.*,
           DENSE_RANK()   OVER (PARTITION BY ey.department_name, ey.review_year
                                ORDER BY ey.avg_score DESC, ey.avg_goals_met_pct DESC)                       AS dept_rank,
           PERCENT_RANK() OVER (PARTITION BY ey.department_name, ey.review_year ORDER BY ey.avg_score)      AS dept_percentile
    FROM employee_year ey
)
SELECT r.review_year, r.department_name, r.dept_rank, ROUND(r.dept_percentile * 100, 1) AS percentile,
       cur.employee_number, cur.full_name, cur.job_role AS current_role, cur.department_name AS current_department,
       ROUND(r.avg_score, 2) AS avg_score, ROUND(r.avg_goals_met_pct, 1) AS avg_goals_met_pct
FROM ranked r
JOIN dim_employee cur ON cur.employee_id = r.employee_id AND cur.is_current = 1;

-- Attrition risk for every employee's current version.
-- Points come from drivers that are known to correlate with leaving in the
-- IBM data (overtime, low satisfaction, stalled promotion, junior level, ...).
-- Leavers are kept (attrition_flag = 1) so the score can be sanity-checked:
-- leavers should score higher than stayers on average.
CREATE OR REPLACE VIEW vw_attrition_risk AS
WITH latest_review AS (
    SELECT f.employee_sk, f.performance_score, f.score_change_vs_prev,
           ROW_NUMBER() OVER (PARTITION BY de.employee_id ORDER BY f.date_sk DESC) AS rn,
           de.employee_id
    FROM fact_performance_reviews f
    JOIN dim_employee de ON de.employee_sk = f.employee_sk
),
scored AS (
    SELECT e.employee_id, e.employee_number, e.full_name, e.department_name, e.job_role, e.job_level,
           e.salary_band, e.age_band, e.attrition_flag, e.overtime_flag, e.job_satisfaction,
           e.environment_satisfaction, e.work_life_balance, e.years_since_last_promotion,
           lr.performance_score AS latest_score, lr.score_change_vs_prev AS latest_score_change,
           LEAST(100,
                 25 * e.overtime_flag
               + CASE e.job_satisfaction WHEN 1 THEN 15 WHEN 2 THEN 7 ELSE 0 END
               + CASE e.environment_satisfaction WHEN 1 THEN 10 WHEN 2 THEN 4 ELSE 0 END
               + CASE e.work_life_balance WHEN 1 THEN 10 WHEN 2 THEN 4 ELSE 0 END
               + CASE WHEN e.years_since_last_promotion >= 5 THEN 8 ELSE 0 END
               + CASE WHEN e.job_level = 1 THEN 10 ELSE 0 END
               + CASE WHEN e.age_band = '< 25' THEN 6 ELSE 0 END
               + CASE WHEN e.business_travel = 'Travel_Frequently' THEN 8 ELSE 0 END
               + CASE WHEN e.distance_from_home > 20 THEN 4 ELSE 0 END
               + CASE WHEN e.salary_band LIKE 'A%' THEN 6 ELSE 0 END
               + CASE WHEN lr.score_change_vs_prev < -0.30 THEN 8 ELSE 0 END
           ) AS risk_score
    FROM dim_employee e
    LEFT JOIN latest_review lr ON lr.employee_id = e.employee_id AND lr.rn = 1
    WHERE e.is_current = 1
)
SELECT s.*,
       CASE WHEN s.risk_score >= 50 THEN 'High' WHEN s.risk_score >= 30 THEN 'Medium' ELSE 'Low' END AS risk_tier,
       NTILE(10) OVER (ORDER BY s.risk_score) AS risk_decile
FROM scored s;

-- Department attrition summary
CREATE OR REPLACE VIEW vw_department_attrition AS
SELECT department_name,
       COUNT(*)                                    AS headcount_ever,
       SUM(attrition_flag)                         AS leavers,
       ROUND(100 * AVG(attrition_flag), 2)         AS attrition_rate_pct,
       ROUND(100 * AVG(overtime_flag), 2)          AS overtime_pct,
       ROUND(AVG(monthly_income), 0)               AS avg_monthly_income
FROM dim_employee
WHERE is_current = 1
GROUP BY department_name;

-- Project health: how reviewed staff on each project perform, ranked within the department.
CREATE OR REPLACE VIEW vw_project_performance AS
WITH per_project AS (
    SELECT dp.project_sk, dp.project_code, dp.project_name, dp.department_name, dp.status, dp.priority,
           dp.budget, COUNT(*) AS reviews, COUNT(DISTINCT f.employee_sk) AS reviewed_staff,
           AVG(f.performance_score) AS avg_score, AVG(f.goals_met_pct) AS avg_goals_met_pct
    FROM fact_performance_reviews f
    JOIN dim_project dp ON dp.project_sk = f.project_sk
    WHERE dp.project_sk <> -1
    GROUP BY dp.project_sk, dp.project_code, dp.project_name, dp.department_name, dp.status, dp.priority, dp.budget
)
SELECT p.*, ROUND(p.avg_score, 2) AS avg_score_rounded,
       RANK() OVER (PARTITION BY p.department_name ORDER BY p.avg_score ASC) AS weakest_rank_in_dept
FROM per_project p;
