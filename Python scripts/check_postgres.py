#!/usr/bin/env python3
"""
check_postgres.py — PostgreSQL health check with a client-ready Markdown report.

Usage:
    pip install psycopg2-binary
    python check_postgres.py --dsn "postgresql://postgres:devpass@localhost:5432/shop"
    python check_postgres.py --dsn "..." -o report.md

Read-only: runs only SELECT / SHOW statements. Safe on production.
Each check returns a status (🟢 OK / 🟡 WARN / 🔴 CRIT), a finding, and a
recommendation — the format clients actually want.
"""

import argparse
import datetime
import sys

import psycopg2
import psycopg2.extras

OK, WARN, CRIT, INFO = "🟢 OK", "🟡 WARN", "🔴 CRIT", "ℹ️  INFO"

# Rough EOL map — update yearly (https://www.postgresql.org/support/versioning/)
EOL = {12: "2024-11", 13: "2025-11", 14: "2026-11", 15: "2027-11",
       16: "2028-11", 17: "2029-11"}


class Report:
    def __init__(self):
        self.sections = []

    def add(self, title, status, finding, recommendation="", detail=""):
        self.sections.append((title, status, finding, recommendation, detail))

    def render(self, dsn_label):
        crit = sum(1 for s in self.sections if s[1] == CRIT)
        warn = sum(1 for s in self.sections if s[1] == WARN)
        head = (
            f"# PostgreSQL Health Check\n\n"
            f"**Target:** `{dsn_label}`  \n"
            f"**Date:** {datetime.date.today().isoformat()}  \n"
            f"**Summary:** {crit} critical, {warn} warnings, "
            f"{len(self.sections) - crit - warn} passing\n\n---\n"
        )
        body = ""
        for title, status, finding, rec, detail in self.sections:
            body += f"\n## {status} — {title}\n\n{finding}\n"
            if rec:
                body += f"\n**Recommendation:** {rec}\n"
            if detail:
                body += f"\n<details><summary>details</summary>\n\n{detail}\n</details>\n"
        return head + body


def q(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def fmt_table(rows, headers):
    if not rows:
        return "_none_"
    out = "| " + " | ".join(headers) + " |\n"
    out += "|" + "---|" * len(headers) + "\n"
    for r in rows:
        out += "| " + " | ".join(str(x)[:120].replace("\n", " ") for x in r) + " |\n"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("-o", "--output", default="pg_health_report.md")
    args = ap.parse_args()

    conn = psycopg2.connect(args.dsn)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    rep = Report()

    # ---- 1. version & EOL -------------------------------------------------
    (ver_str,) = q(cur, "SELECT version()")[0]
    (major,) = q(cur, "SELECT current_setting('server_version_num')::int / 10000")[0]
    eol = EOL.get(major)
    if eol and eol < datetime.date.today().strftime("%Y-%m"):
        rep.add("Version", CRIT, f"{ver_str.split(',')[0]} — **past end of life**",
                "Plan an upgrade to a supported major version immediately.")
    elif major < max(EOL) - 1:
        rep.add("Version", WARN, f"{ver_str.split(',')[0]} (EOL {eol})",
                "Supported, but plan a major upgrade within the year.")
    else:
        rep.add("Version", OK, ver_str.split(",")[0])

    # ---- 2. cache hit ratio ------------------------------------------------
    rows = q(cur, """
        SELECT round(100.0 * sum(blks_hit) /
               nullif(sum(blks_hit) + sum(blks_read), 0), 2)
        FROM pg_stat_database""")
    ratio = rows[0][0] or 0
    status = OK if ratio >= 99 else WARN if ratio >= 95 else CRIT
    rep.add("Buffer cache hit ratio", status, f"{ratio}% of reads served from RAM",
            "" if status == OK else
            "Below 99%: consider raising `shared_buffers` (typically ~25% of RAM) "
            "or investigate large sequential scans (see slow queries below).")

    # ---- 3. key settings ----------------------------------------------------
    settings = dict(q(cur, """
        SELECT name, setting FROM pg_settings WHERE name IN
        ('shared_buffers','work_mem','effective_cache_size','max_connections',
         'autovacuum','wal_level','random_page_cost')"""))
    rep.add("Key settings", INFO,
            fmt_table(sorted(settings.items()), ["setting", "value"]),
            "Compare `shared_buffers` to server RAM (~25%), and "
            "`effective_cache_size` (~70% RAM). `random_page_cost` should be "
            "~1.1 on SSD (default 4 assumes spinning disks).")

    # ---- 4. connections -----------------------------------------------------
    (used, mx) = q(cur, """
        SELECT (SELECT count(*) FROM pg_stat_activity),
               current_setting('max_connections')::int""")[0]
    pct = 100 * used / mx
    status = OK if pct < 70 else WARN if pct < 90 else CRIT
    rep.add("Connections", status, f"{used}/{mx} in use ({pct:.0f}%)",
            "" if status == OK else
            "Approaching the limit — add pgBouncer for pooling rather than "
            "raising max_connections (each connection costs RAM).")

    # ---- 5. slowest queries (pg_stat_statements) ----------------------------
    try:
        rows = q(cur, """
            SELECT calls, round(mean_exec_time::numeric, 1) AS mean_ms,
                   round(total_exec_time::numeric / 1000, 1) AS total_s,
                   left(query, 90) AS query
            FROM pg_stat_statements
            ORDER BY total_exec_time DESC LIMIT 10""")
        worst_mean = max((r[1] for r in rows), default=0)
        status = OK if worst_mean < 100 else WARN if worst_mean < 1000 else CRIT
        rep.add("Top queries by total time", status,
                fmt_table(rows, ["calls", "mean ms", "total s", "query"]),
                "" if status == OK else
                "Run `EXPLAIN (ANALYZE, BUFFERS)` on the worst offenders; "
                "candidates for indexing or rewriting.")
    except psycopg2.Error:
        conn.rollback()
        rep.add("Top queries", WARN, "`pg_stat_statements` is not enabled.",
                "Add it to `shared_preload_libraries` and "
                "`CREATE EXTENSION pg_stat_statements;` — it is the single most "
                "useful diagnostic tool and has negligible overhead.")

    # ---- 6. unused indexes ---------------------------------------------------
    rows = q(cur, """
        SELECT schemaname || '.' || relname AS tbl, indexrelname,
               pg_size_pretty(pg_relation_size(indexrelid)) AS size
        FROM pg_stat_user_indexes
        WHERE idx_scan = 0 AND pg_relation_size(indexrelid) > 8192 * 16
        ORDER BY pg_relation_size(indexrelid) DESC LIMIT 15""")
    rep.add("Unused indexes", OK if not rows else WARN,
            fmt_table(rows, ["table", "index", "size"]),
            "" if not rows else
            "Zero scans since stats reset. Each one slows every write and uses "
            "RAM/disk. Verify against a full business cycle before dropping "
            "(some indexes serve monthly/annual jobs).")

    # ---- 7. tables likely missing indexes ------------------------------------
    rows = q(cur, """
        SELECT relname, seq_scan, idx_scan, n_live_tup
        FROM pg_stat_user_tables
        WHERE seq_scan > 1000 AND n_live_tup > 100000
          AND seq_scan > 5 * coalesce(idx_scan, 0)
        ORDER BY seq_scan DESC LIMIT 10""")
    rep.add("Possible missing indexes", OK if not rows else WARN,
            fmt_table(rows, ["table", "seq scans", "idx scans", "rows"]),
            "" if not rows else
            "Large tables read mostly by sequential scan — check the WHERE "
            "clauses hitting them in pg_stat_statements and index accordingly.")

    # ---- 8. dead tuples / vacuum health --------------------------------------
    rows = q(cur, """
        SELECT relname, n_live_tup, n_dead_tup,
               round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1)
                 AS dead_pct,
               coalesce(last_autovacuum::text, 'never') AS last_autovacuum
        FROM pg_stat_user_tables
        WHERE n_dead_tup > 10000
        ORDER BY n_dead_tup DESC LIMIT 10""")
    worst = max((r[3] or 0 for r in rows), default=0)
    status = OK if worst < 10 else WARN if worst < 25 else CRIT
    rep.add("Table bloat (dead tuples)", status,
            fmt_table(rows, ["table", "live", "dead", "dead %", "last autovacuum"]),
            "" if status == OK else
            "High dead-tuple ratios bloat tables and slow scans. Tune autovacuum "
            "(lower `autovacuum_vacuum_scale_factor` for big tables) or schedule "
            "manual VACUUM during low traffic.")

    # ---- 9. replication -------------------------------------------------------
    rows = q(cur, """
        SELECT application_name, state,
               pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn))
        FROM pg_stat_replication""")
    if rows:
        rep.add("Replication", OK, fmt_table(rows, ["replica", "state", "lag"]))
    else:
        rep.add("Replication", INFO, "No replicas connected.",
                "If this is production, a streaming replica is the cheapest "
                "insurance for both HA and safe read scaling.")

    # ---- 10. long-running / idle-in-transaction -------------------------------
    rows = q(cur, """
        SELECT pid, state, now() - xact_start AS duration, left(query, 70)
        FROM pg_stat_activity
        WHERE xact_start IS NOT NULL AND now() - xact_start > interval '5 minutes'
        ORDER BY xact_start LIMIT 10""")
    rep.add("Long transactions (>5 min)", OK if not rows else WARN,
            fmt_table(rows, ["pid", "state", "duration", "query"]),
            "" if not rows else
            "Long/idle transactions block vacuum and hold locks. "
            "Set `idle_in_transaction_session_timeout`.")

    # ---- 11. largest tables ----------------------------------------------------
    rows = q(cur, """
        SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC LIMIT 10""")
    rep.add("Largest tables", INFO, fmt_table(rows, ["table", "total size"]))

    out = rep.render(args.dsn.split("@")[-1])
    with open(args.output, "w") as f:
        f.write(out)
    print(f"Report written to {args.output}")
    if any(s[1] == CRIT for s in rep.sections):
        sys.exit(2)


if __name__ == "__main__":
    main()
