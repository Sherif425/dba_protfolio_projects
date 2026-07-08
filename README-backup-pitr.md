# 🛡 backup-pitr-toolkit

**Automated MySQL & PostgreSQL backups with *tested* restores and a live
point-in-time recovery demo: I drop a production table on purpose — and get every
row back, recovered to the exact second before the disaster.**

A backup you've never restored is just a hope. This repo treats restore as the
product and backup as the implementation detail.

🎬 **[Watch the 3-minute PITR demo (asciinema)](#)** ← record this; it's the best
portfolio artifact in the whole repo.

---

## What's demonstrated

| Capability | PostgreSQL | MySQL |
|---|---|---|
| Full physical backups | pgBackRest | Percona XtraBackup |
| Incremental/differential | pgBackRest diff/incr | XtraBackup incremental |
| Continuous WAL/binlog archiving | `archive_command` → pgBackRest | binlog + `mysqlbinlog` |
| Point-in-time recovery | `--type=time` restore | replay binlogs to timestamp |
| Automated restore verification | `verify_restore.sh` | `verify_restore.sh` |
| Retention & encryption | 7d/4w/3m policy, AES-256 | same |
| Off-site copy | rclone → S3-compatible bucket | same |

## The disaster drill (the demo)

```bash
./drill.sh postgres
# 1. seeds a table with 1M rows, inserts a "last known good" marker row
# 2. takes a full backup, keeps WAL archiving on
# 3. inserts 5,000 more rows over 60 seconds (simulated live traffic)
# 4. 💥 DROP TABLE orders;  -- 14:32:07
# 5. restores to 14:32:06 into a recovery container
# 6. diffs row counts + checksums against expected state → ✅ PASS
```

The same drill exists for MySQL using XtraBackup + binlog replay.

## Restore verification, automated

`verify_restore.sh` runs weekly from cron:
1. Pulls the latest backup into a throwaway Docker container
2. Restores it fully
3. Row-counts every table and checksums 3 random tables against the source
4. Posts the result to a webhook (Slack/Discord/email)
5. Exits non-zero on any mismatch — so a broken backup pages you *before* you need it

## Repo layout

```
backup-pitr-toolkit/
├── postgres/
│   ├── docker-compose.yml       # pg16 + pgbackrest sidecar
│   ├── pgbackrest.conf
│   ├── drill.sh                 # the disaster demo
│   └── verify_restore.sh
├── mysql/
│   ├── docker-compose.yml       # mysql8 + xtrabackup
│   ├── backup.sh / restore_pitr.sh
│   ├── drill.sh
│   └── verify_restore.sh
├── cron/                        # example schedules + retention policy
└── docs/
    ├── runbook-postgres-pitr.md # step-by-step ops runbook (client deliverable style)
    └── runbook-mysql-pitr.md
```

The two runbooks are written exactly like the documentation I hand to clients:
numbered steps, expected output at each step, and a rollback plan.

## Quick start

```bash
git clone https://github.com/<you>/backup-pitr-toolkit && cd backup-pitr-toolkit
cd postgres && docker compose up -d
./drill.sh          # full disaster → recovery cycle, ~4 minutes
```

## 📜 License

MIT.

---

*Built by [Your Name], MySQL/PostgreSQL DBA — [Upwork profile link].*
