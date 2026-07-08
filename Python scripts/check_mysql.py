#!/usr/bin/env python3
"""
check_mysql.py — MySQL 8.x health check with a client-ready Markdown report.

Usage:
    pip install pymysql
    python check_mysql.py --host localhost --user root --password devpass
    python check_mysql.py ... -o report.md

Read-only (SELECT / SHOW only). Safe on production.
"""

import argparse
import datetime
import sys

import pymysql

OK, WARN, CRIT, INFO = "🟢 OK", "🟡 WARN", "🔴 CRIT", "ℹ️  INFO"


class Report:
    def __init__(self):
        self.sections = []

    def add(self, title, status, finding, recommendation=""):
        self.sections.append((title, status, finding, recommendation))

    def render(self, target):
        crit = sum(1 for s in self.sections if s[1] == CRIT)
        warn = sum(1 for s in self.sections if s[1] == WARN)
        out = (f"# MySQL Health Check\n\n**Target:** `{target}`  \n"
               f"**Date:** {datetime.date.today().isoformat()}  \n"
               f"**Summary:** {crit} critical, {warn} warnings, "
               f"{len(self.sections) - crit - warn} passing\n\n---\n")
        for title, status, finding, rec in self.sections:
            out += f"\n## {status} — {title}\n\n{finding}\n"
            if rec:
                out += f"\n**Recommendation:** {rec}\n"
        return out


def fmt_table(rows, headers):
    if not rows:
        return "_none_"
    out = "| " + " | ".join(headers) + " |\n" + "|" + "---|" * len(headers) + "\n"
    for r in rows:
        out += "| " + " | ".join(str(x)[:110].replace("\n", " ") for x in r) + " |\n"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("-o", "--output", default="mysql_health_report.md")
    args = ap.parse_args()

    conn = pymysql.connect(host=args.host, port=args.port, user=args.user,
                           password=args.password)
    cur = conn.cursor()

    def q(sql):
        cur.execute(sql)
        return cur.fetchall()

    def status_vars(*names):
        placeholders = ",".join(f"'{n}'" for n in names)
        cur.execute(f"SHOW GLOBAL STATUS WHERE Variable_name IN ({placeholders})")
        return {k: float(v) if str(v).replace('.', '', 1).isdigit() else v
                for k, v in cur.fetchall()}

    def sys_vars(*names):
        placeholders = ",".join(f"'{n}'" for n in names)
        cur.execute(f"SHOW GLOBAL VARIABLES WHERE Variable_name IN ({placeholders})")
        return dict(cur.fetchall())

    rep = Report()

    # ---- 1. version ---------------------------------------------------------
    (ver,) = q("SELECT VERSION()")[0]
    major = ver.split(".")[0]
    if major == "5":
        rep.add("Version", CRIT, f"MySQL {ver} — 5.7 reached EOL in Oct 2023.",
                "Upgrade to 8.0/8.4 LTS. This is a security issue, not a preference.")
    else:
        rep.add("Version", OK, f"MySQL {ver}")

    # ---- 2. buffer pool -------------------------------------------------------
    s = status_vars("Innodb_buffer_pool_read_requests", "Innodb_buffer_pool_reads")
    reqs = s.get("Innodb_buffer_pool_read_requests", 0)
    misses = s.get("Innodb_buffer_pool_reads", 0)
    ratio = 100 * (1 - misses / reqs) if reqs else 0
    v = sys_vars("innodb_buffer_pool_size")
    pool_gb = int(v["innodb_buffer_pool_size"]) / 1024**3
    st = OK if ratio >= 99 else WARN if ratio >= 95 else CRIT
    rep.add("InnoDB buffer pool", st,
            f"Hit ratio {ratio:.2f}%, pool size {pool_gb:.1f} GB",
            "" if st == OK else
            "Below 99%: working set exceeds the pool. Raise "
            "`innodb_buffer_pool_size` (~70% of RAM on a dedicated DB server).")

    # ---- 3. connections --------------------------------------------------------
    s = status_vars("Threads_connected", "Max_used_connections",
                    "Aborted_connects")
    mx = int(sys_vars("max_connections")["max_connections"])
    used_peak = int(s.get("Max_used_connections", 0))
    pct = 100 * used_peak / mx
    st = OK if pct < 70 else WARN if pct < 90 else CRIT
    rep.add("Connections", st,
            f"Now: {int(s.get('Threads_connected',0))}, peak: {used_peak}/{mx} "
            f"({pct:.0f}% of max), aborted connects: "
            f"{int(s.get('Aborted_connects',0))}",
            "" if st == OK else
            "Peak usage near the limit — investigate connection leaks or add "
            "pooling (ProxySQL / application-side pool).")

    # ---- 4. slowest queries (performance_schema) --------------------------------
    try:
        rows = q("""
            SELECT count_star AS calls,
                   round(avg_timer_wait/1e9, 1)  AS mean_ms,
                   round(sum_timer_wait/1e12, 1) AS total_s,
                   LEFT(digest_text, 90)         AS query
            FROM performance_schema.events_statements_summary_by_digest
            WHERE schema_name NOT IN ('mysql','performance_schema','sys')
            ORDER BY sum_timer_wait DESC LIMIT 10""")
        worst = max((r[1] for r in rows), default=0)
        st = OK if worst < 100 else WARN if worst < 1000 else CRIT
        rep.add("Top queries by total time", st,
                fmt_table(rows, ["calls", "mean ms", "total s", "digest"]),
                "" if st == OK else
                "Run EXPLAIN ANALYZE on the worst digests; index or rewrite.")
    except pymysql.Error:
        rep.add("Top queries", WARN, "performance_schema not accessible.",
                "Enable performance_schema (default ON in 8.x) and grant "
                "SELECT on it to the monitoring user.")

    # ---- 5. unused / redundant indexes -------------------------------------------
    try:
        rows = q("""SELECT object_schema, object_name, index_name
                    FROM sys.schema_unused_indexes LIMIT 15""")
        rep.add("Unused indexes", OK if not rows else WARN,
                fmt_table(rows, ["schema", "table", "index"]),
                "" if not rows else
                "No reads since server start. Verify over a full business cycle, "
                "then drop — every index taxes every write.")
        rows = q("""SELECT table_schema, table_name, redundant_index_name,
                           dominant_index_name
                    FROM sys.schema_redundant_indexes LIMIT 15""")
        if rows:
            rep.add("Redundant indexes", WARN,
                    fmt_table(rows, ["schema", "table", "redundant", "covered by"]),
                    "These are prefixes of other indexes — safe to drop after "
                    "verification.")
    except pymysql.Error:
        rep.add("Index usage", WARN, "sys schema not accessible.",
                "Grant access to the `sys` schema for index-usage analysis.")

    # ---- 6. temp tables & sorting ---------------------------------------------
    s = status_vars("Created_tmp_disk_tables", "Created_tmp_tables",
                    "Sort_merge_passes")
    tmp, disk = s.get("Created_tmp_tables", 0), s.get("Created_tmp_disk_tables", 0)
    pct = 100 * disk / tmp if tmp else 0
    st = OK if pct < 10 else WARN if pct < 25 else CRIT
    rep.add("Temp tables on disk", st,
            f"{pct:.0f}% of temp tables spilled to disk "
            f"({int(disk):,}/{int(tmp):,}); sort merge passes: "
            f"{int(s.get('Sort_merge_passes',0)):,}",
            "" if st == OK else
            "Queries with big GROUP BY/ORDER BY are spilling. Raise "
            "`tmp_table_size`/`max_heap_table_size`, or better: index/rewrite "
            "the offending queries (TEXT/BLOB columns always spill).")

    # ---- 7. slow query log --------------------------------------------------------
    v = sys_vars("slow_query_log", "long_query_time")
    if v.get("slow_query_log") == "ON":
        rep.add("Slow query log", OK,
                f"Enabled, threshold {v['long_query_time']}s")
    else:
        rep.add("Slow query log", WARN, "Disabled.",
                "Enable it (`slow_query_log=ON`, `long_query_time=0.5`) — "
                "essential visibility at negligible cost.")

    # ---- 8. replication -------------------------------------------------------------
    rows = q("SHOW REPLICAS") if major >= "8" else q("SHOW SLAVE HOSTS")
    if rows:
        rep.add("Replication", OK, f"{len(rows)} replica(s) registered.")
    else:
        rep.add("Replication", INFO, "No replicas.",
                "For production, a replica is the cheapest HA + safe-reads win.")

    # ---- 9. largest tables ------------------------------------------------------------
    rows = q("""
        SELECT table_schema, table_name,
               round((data_length + index_length)/1024/1024/1024, 2) AS size_gb,
               table_rows
        FROM information_schema.tables
        WHERE table_schema NOT IN ('mysql','sys','performance_schema',
                                   'information_schema')
        ORDER BY data_length + index_length DESC LIMIT 10""")
    rep.add("Largest tables", INFO,
            fmt_table(rows, ["schema", "table", "size GB", "~rows"]))

    out = rep.render(f"{args.host}:{args.port}")
    with open(args.output, "w") as f:
        f.write(out)
    print(f"Report written to {args.output}")
    if any(s[1] == CRIT for s in rep.sections):
        sys.exit(2)


if __name__ == "__main__":
    main()
