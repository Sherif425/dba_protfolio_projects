-- ======================================================================
-- "AFTER" physical design. Apply per case study, one at a time,
-- benchmarking before and after each. CONCURRENTLY avoids write locks
-- (PostgreSQL; run outside a transaction).
-- ======================================================================

-- Case study 1: user order history ------------------------------------
-- PostgreSQL
CREATE INDEX CONCURRENTLY idx_order_user_created
    ON shop_order (user_id, created_at DESC);
-- covering variant (index-only scan, PG11+):
-- CREATE INDEX CONCURRENTLY idx_order_user_created_cov
--     ON shop_order (user_id, created_at DESC) INCLUDE (status, total);

-- MySQL (InnoDB, 8.0+ supports DESC indexes)
CREATE INDEX idx_order_user_created ON shop_order (user_id, created_at DESC);

-- Case study 3: full-text search --------------------------------------
-- PostgreSQL: expression GIN index (or move to a SearchVectorField column)
CREATE INDEX CONCURRENTLY idx_product_fts
    ON shop_product USING GIN (to_tsvector('english', description));
-- MySQL:
CREATE FULLTEXT INDEX idx_product_fts ON shop_product (description);

-- Case study 5: dashboard aggregation ----------------------------------
-- PostgreSQL: partial covering index for the hot predicate
CREATE INDEX CONCURRENTLY idx_order_delivered_created
    ON shop_order (created_at) INCLUDE (user_id, total)
    WHERE status = 'delivered';
-- MySQL has no partial indexes; use a composite instead:
CREATE INDEX idx_order_status_created ON shop_order (status, created_at, user_id, total);
