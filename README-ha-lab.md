# 🔁 pg-mysql-ha-lab

**High-availability database clusters you can destroy. Kill the primary — writes
continue in under 30 seconds. All on your laptop with Docker Compose.**

Two production-pattern clusters, one repo:

- **PostgreSQL:** 3× Patroni nodes + etcd (consensus) + HAProxy (routing) + pgBouncer
  (pooling), monitored by Prometheus + Grafana
- **MySQL:** 3-node Group Replication (single-primary) + MySQL Router, same monitoring

🎬 **[Failover demo recording](#)** — a writer script inserts one row per second while
I `docker kill` the primary. The gap in inserts *is* the failover time. Measured, not
claimed.

---

## Architecture

```
                        ┌─────────────┐
   app / psql  ───────▶ │   HAProxy    │  port 5000 = primary (writes)
                        │              │  port 5001 = replicas (reads)
                        └──────┬───────┘
              ┌────────────────┼────────────────┐
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │ patroni-1  │   │ patroni-2  │   │ patroni-3  │
        │ (leader)   │   │ (replica)  │   │ (replica)  │
        └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
              └────────────────┼────────────────┘
                        ┌─────▼─────┐
                        │   etcd     │  leader election & cluster state
                        └───────────┘
```

(Full draw.io diagrams for both clusters in `docs/diagrams/`.)

## The chaos drills

```bash
./chaos/kill_primary.sh        # hard-kill the leader → automatic failover
./chaos/lag_replica.sh         # inject 5s network delay → watch lag alerts fire
./chaos/split_brain_test.sh    # partition etcd → verify Patroni refuses split-brain
./chaos/rejoin_old_primary.sh  # old primary returns → rewound & rejoined as replica
```

Each drill prints a timeline: `T+0.0s kill … T+11.2s new leader elected … T+14.8s
first successful write`. Results from my runs are committed in `chaos/results/`.

## What each component is for (and what breaks without it)

- **etcd** — consensus store; Patroni nodes race for a lock in it. Without a proper
  quorum you get split-brain. Demo included.
- **Patroni** — the failover brain: health-checks PostgreSQL, promotes replicas,
  rewinds failed primaries with `pg_rewind`.
- **HAProxy** — apps connect to one address forever; HAProxy asks Patroni's REST API
  who the leader is (`/primary` health check) and routes accordingly.
- **pgBouncer** — connection pooling; also demoed: 2,000 client connections served
  through 40 server connections.
- **MySQL Group Replication** — Paxos-based; the cluster itself elects a primary,
  MySQL Router follows it automatically.

## Monitoring included

Prometheus + Grafana + `postgres_exporter` / `mysqld_exporter` with dashboards for:
replication lag (bytes & seconds), TPS per node, connection pool saturation,
failover events annotated on graphs. Alert rules: lag > 10s, node down, no primary.

## Run it

```bash
git clone https://github.com/<you>/pg-mysql-ha-lab && cd pg-mysql-ha-lab
cd postgres-patroni && docker compose up -d      # ~1 min to converge
./status.sh                                       # patronictl list — see the cluster
./chaos/kill_primary.sh                           # the fun part
```

Grafana: `localhost:3000` (admin/admin).

## 📜 License

MIT.

---

*Built by [Your Name], MySQL/PostgreSQL DBA — [Upwork profile link].*
