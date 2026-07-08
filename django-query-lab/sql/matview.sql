-- Case study 5, step 2 (PostgreSQL): precompute the dashboard.
CREATE MATERIALIZED VIEW top_customers_month AS
SELECT u.username, SUM(o.total) AS spent
FROM shop_order o JOIN auth_user u ON u.id = o.user_id
WHERE o.status = 'delivered'
  AND o.created_at >= date_trunc('month', now())
GROUP BY u.username
ORDER BY spent DESC
LIMIT 100;

CREATE UNIQUE INDEX ON top_customers_month (username);
-- refresh from cron (non-blocking):
--   REFRESH MATERIALIZED VIEW CONCURRENTLY top_customers_month;
-- MySQL equivalent: a summary table maintained by an EVENT or app-side job.
