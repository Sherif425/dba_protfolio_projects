# The DBA Workflow — Working the Lab Without Touching App Code

You are the DBA. The Django app is "the application team's code" — a black box that
generates traffic. Your tools are `psql`, the `mysql` shell, the statistics views,
and DDL. This is exactly how you'll work on client engagements, where you often
never see the application source at all.

---

## The loop you repeat for every case study

```
OBSERVE  →  DIAGNOSE  →  FIX  →  VERIFY
(stats)     (EXPLAIN)    (DDL/    (stats again,
                          config)  before/after)
```

### 1. OBSERVE — find the pain from the database side

**PostgreSQL — your main instrument is pg_stat_statements:**
```sql
-- reset counters, then let the app/benchmark run for a while
SELECT pg_stat_statements_reset();

-- the money query: where does the server actually spend its time?
SELECT calls,
       round(mean_exec_time::numeric, 1)      AS mean_ms,
       round(total_exec_time::numeric/1000,1) AS total_s,
       rows / nullif(calls, 0)                AS rows_per_call,
       left(query, 100)                       AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 15;
```

**MySQL — performance_schema digests + slow query log:**
```sql
SELECT count_star AS calls,
       round(avg_timer_wait/1e9, 1)  AS mean_ms,
       round(sum_timer_wait/1e12, 1) AS total_s,
       left(digest_text, 100)        AS query
FROM performance_schema.events_statements_summary_by_digest
WHERE schema_name = 'shop'
ORDER BY sum_timer_wait DESC LIMIT 15;
```
```bash
# and the classic tool every MySQL DBA should demo:
pt-query-digest /var/lib/mysql/*-slow.log | head -50
```

### 2. DIAGNOSE — read the plan

```sql
-- PostgreSQL: ALWAYS with BUFFERS — it shows I/O, not just estimates
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ;              -- paste the query from pg_stat_statements

-- MySQL 8:
EXPLAIN ANALYZE SELECT ... ;
EXPLAIN FORMAT=JSON SELECT ... ;   -- cost details
```

What you're looking for (this is the skill clients pay for):
- `Seq Scan` on a big table with a selective WHERE → missing index
- `Sort` node spilling (`external merge Disk:` in PG, `Using filesort` in MySQL)
  → index matching the ORDER BY, or work_mem/sort_buffer tuning
- `Rows Removed by Filter: 4,900,000` → the index isn't selective enough / wrong
  column order
- Heap fetches on an Index Scan → covering index (`INCLUDE`) opportunity

### 3. FIX — with DDL and configuration, not code

Everything in `sql/indexes_after.sql` is a DBA-side fix: composite indexes,
DESC indexes, covering (INCLUDE) indexes, partial indexes, GIN/FULLTEXT indexes,
the materialized view. Apply them like production: `CREATE INDEX CONCURRENTLY`
(PG) and note MySQL 8's online DDL (`ALGORITHM=INPLACE, LOCK=NONE`).

### 4. VERIFY — numbers, not vibes

Re-run step 1's query. Screenshot before/after `pg_stat_statements` rows and the
two EXPLAIN plans. That pair of screenshots IS the portfolio artifact.

---

## How a DBA recognizes APPLICATION problems from the database side

Two of the five case studies (N+1, deep OFFSET) are ultimately app-side fixes —
and that's a feature, not a bug, because identifying them from pure database
telemetry and writing the recommendation is core senior-DBA work:

**The N+1 signature:** in pg_stat_statements you'll see
`SELECT ... FROM auth_user WHERE id = $1` with an absurd call count (e.g. 30,000
calls, 0.3ms each) right next to one feed query with 300 calls. Tiny mean time,
huge call count, calls ≈ 100× the parent query = the app is looping.
Your deliverable as DBA: *"The review feed issues ~301 queries per request;
recommend the application join these (in Django: select_related). No index can
fix this."* Diagnosing it without seeing the code is the impressive part.

**The deep-OFFSET signature:** slow log shows `... ORDER BY id LIMIT 20 OFFSET
900000`, EXPLAIN shows 900k rows read and discarded. Recommendation: keyset
pagination. Again — you identified it from the log alone.

Frame both case studies this way in your writeups. It positions you as the DBA
who partners with dev teams, which is precisely what Upwork clients want.

---

## Extra DBA-only exercises on the same seeded data (no app involved)

These use the app's data but not its endpoints — pure administration practice:

1. **Configuration tuning pass.** Benchmark `top_customers` query in psql, then
   tune and re-measure: `work_mem` (watch the sort stop spilling), 
   `random_page_cost` 4 → 1.1 (watch the planner start choosing index scans),
   `shared_buffers` / `innodb_buffer_pool_size` sizing. Document each change's
   measured effect — config tuning with numbers is a rare portfolio item.

2. **Vacuum/bloat drill (PG).** Run a mass UPDATE on shop_order, watch
   `n_dead_tup` climb, observe autovacuum behavior, tune
   `autovacuum_vacuum_scale_factor` for the big table, compare `pg_relation_size`
   before/after. MySQL twin: `OPTIMIZE TABLE` and fragmentation measurement.

3. **Lock/blocking analysis.** Open a transaction that updates a row and forget
   to commit (real-world classic); from another session, find the blocker with
   `pg_blocking_pids()` / `pg_locks`, and in MySQL via
   `sys.innodb_lock_waits`. Write the runbook for identifying and killing it.

4. **Index maintenance audit.** After creating all the case-study indexes, run
   your own check_postgres.py / check_mysql.py — find which indexes the workload
   actually uses, measure their write cost (`pgbench`/`sysbench` insert rate with
   and without them), and drop the losers. "Indexes are not free" with measured
   write penalties is a senior-level case study.

5. **Upgrade drill.** Spin a PG 15 container, restore your data into it, practice
   `pg_upgrade` (or logical dump/restore) to 16. MySQL: 8.0 → 8.4 in-place.
   Downtime measured and documented.

---

## What this means for your Upwork positioning

Your case studies should read like DBA incident reports, not dev tutorials:

> "pg_stat_statements showed one query consuming 61% of total server time.
> EXPLAIN (ANALYZE, BUFFERS) revealed a sequential scan over 5M rows with a sort
> spilling 400MB to disk. I added a partial covering index
> (CREATE INDEX CONCURRENTLY, no write lock); p95 dropped from 12.2s to 180ms and
> total server CPU fell 40%. Where the root cause was application behavior (an
> N+1 pattern), I documented it with query-log evidence and provided the dev
> team a concrete recommendation."

That last sentence — knowing the boundary between DBA fixes and app fixes, and
handling both sides professionally — is what separates a $25/hr profile from a
$50/hr one.
