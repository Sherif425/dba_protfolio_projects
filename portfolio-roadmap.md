# DBA Portfolio Roadmap — 4 Real Projects You Can Build Yourself

These four projects cover the exact skills clients hire DBAs for. Each one produces
GitHub-visible artifacts (code, docs, benchmark numbers, screenshots) that you can link
in your Upwork portfolio. Build them in this order — difficulty and impressiveness both
increase as you go.

| # | Project | Proves you can... | Time estimate |
|---|---------|-------------------|---------------|
| 1 | **db-health-check** | Audit any MySQL/PostgreSQL server and produce a client-ready report | 1 weekend |
| 2 | **django-query-optimization-lab** (flagship) | Find and fix slow queries with measurable before/after numbers | 1–2 weeks |
| 3 | **backup-pitr-toolkit** | Set up backups that restore, including point-in-time recovery | 1 week |
| 4 | **pg-mysql-ha-lab** | Build replication + automatic failover | 1–2 weeks |

Everything runs in Docker on a single machine — you do NOT need multiple servers or a
cloud account (though a $6/mo VPS makes screenshots more "production-real").

---

## Project 1 — db-health-check

**What it is:** A pair of scripts (one for MySQL, one for PostgreSQL) that connect to a
server and generate a Markdown/HTML health report: version & EOL status, config sanity
(buffer pool / shared_buffers sizing, max_connections), top 10 slowest queries, unused
and missing indexes, table bloat, replication lag, backup recency, dangerous privileges.

**Why it's a great first project:** it becomes your actual Upwork productized service
("Database Health Check — $200"). You build it once and sell it forever.

**Stack:** Python + `psycopg2` / `PyMySQL`, Jinja2 template for the report.

**Key queries to include:**

PostgreSQL:
- `pg_stat_statements` for slowest queries (enable the extension first)
- `pg_stat_user_indexes` where `idx_scan = 0` → unused indexes
- `pg_stat_user_tables` `n_dead_tup` vs `n_live_tup` → bloat/vacuum health
- `pg_settings` checks: `shared_buffers` (~25% RAM), `work_mem`, `effective_cache_size`
- `pg_stat_replication` → replica lag

MySQL:
- `performance_schema.events_statements_summary_by_digest` → slowest queries
- `sys.schema_unused_indexes` and `sys.schema_redundant_indexes`
- `SHOW GLOBAL STATUS` vs `SHOW VARIABLES`: buffer pool hit ratio, tmp tables on disk,
  connection usage
- `information_schema.tables` → fragmentation estimate

**Deliverable for portfolio:** a sample generated report (PDF/screenshot) run against
your own loaded test database from Project 2.

**Steps:**
1. `docker compose up` a MySQL 8 and PostgreSQL 16 container.
2. Write `check_postgres.py` — connect, run the queries above, collect results in a dict.
3. Render `report.md` via a Jinja2 template with a traffic-light system (🟢🟡🔴) per check.
4. Repeat for MySQL. Share the report template between both.
5. Add `--format html` output. Screenshot it for your portfolio.

---

## Project 2 — django-query-optimization-lab (FLAGSHIP)

Full README drafted separately: `README-django-query-lab.md`.

**What it is:** A realistic Django e-commerce backend seeded with **5–10 million rows**,
with deliberately slow endpoints that you then optimize one by one — N+1 queries,
missing indexes, bad pagination, unindexed foreign keys, `SELECT *` waste, full-text
search done wrong then right. Every fix is a git commit with before/after benchmark
numbers in the commit message and a `docs/case-studies/` writeup.

**Why it's the flagship:** it produces the exact artifact clients love — "query went
from 8.4s to 45ms" with EXPLAIN screenshots. It also proves you understand how
*applications* misuse databases, which pure-DBA candidates often can't show.

---

## Project 3 — backup-pitr-toolkit

Full README drafted separately: `README-backup-pitr.md`.

**What it is:** Automated backup setup for both engines with **tested, scripted
restores** and a point-in-time recovery demo: you insert data, take a backup, simulate
a disaster (`DROP TABLE orders;`), then recover to the second *before* the disaster.
Record the terminal session (asciinema) — that recording is portfolio gold.

**Stack:** pgBackRest (PostgreSQL), Percona XtraBackup + binlogs (MySQL), cron, a
`verify_restore.sh` that restores into a scratch container and row-counts every table.

---

## Project 4 — pg-mysql-ha-lab

Full README drafted separately: `README-ha-lab.md`.

**What it is:** Docker Compose environments for high availability:
- **PostgreSQL:** 3-node Patroni cluster + etcd + HAProxy + pgBouncer. Demo: kill the
  primary, watch automatic failover in <30s while a test writer script keeps running.
- **MySQL:** Group Replication (or classic async primary + 2 replicas + orchestrator).
  Same kill-the-primary demo.

**Deliverable:** architecture diagram (draw.io), failover demo recording, replication
lag Grafana dashboard. Add Prometheus + Grafana with `postgres_exporter` and
`mysqld_exporter` — this doubles as your "monitoring" portfolio item.

---

## How to present these on Upwork

For each project, the portfolio item should contain:
1. **One number in the title** — "Cut query time 99.4%: Django + PostgreSQL case study"
2. **One image** — EXPLAIN before/after, Grafana dashboard, or architecture diagram
3. **3–5 sentence story** — problem → what you did → measured result
4. **GitHub link** — the README does the deep selling

Pin Project 2 first — application performance work gets the most client attention.
