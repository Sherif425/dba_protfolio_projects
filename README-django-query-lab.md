# ⚡ Django Query Optimization Lab

**A realistic e-commerce backend with 10 million rows — and a documented journey of
taking its worst endpoints from seconds to milliseconds on both PostgreSQL and MySQL.**

Every optimization in this repo is a separate commit with **measured before/after
numbers**, the relevant `EXPLAIN ANALYZE` output, and a short case study in
[`docs/case-studies/`](docs/case-studies/).

| Endpoint | Before | After | Technique |
|---|---|---|---|
| `GET /api/orders/?user=<id>` | 8.4 s | 45 ms | Composite index + covering index |
| `GET /api/products/search/` | 3.1 s | 60 ms | GIN full-text index (PG) / FULLTEXT (MySQL) |
| `GET /api/dashboard/top-customers/` | 12.2 s | 180 ms | Materialized aggregate + index-only scan |
| `GET /api/reviews/feed/` | 5.6 s | 90 ms | Fixed N+1 with `select_related`/`prefetch_related` |
| `GET /api/orders/export/` | OOM crash | streams in 40 s | Server-side cursor + `iterator()` |

> ⚠️ Replace the numbers above with YOUR actual measured results after running the lab.
> Do not publish placeholder numbers.

---

## 🏗 What's inside

```
django-query-lab/
├── docker-compose.yml        # PostgreSQL 16 + MySQL 8 + app + Grafana/Prometheus
├── app/
│   ├── shop/models.py        # User, Product, Category, Order, OrderItem, Review
│   ├── shop/views_slow.py    # the "before" endpoints (kept for comparison)
│   ├── shop/views_fast.py    # the optimized versions
│   └── shop/management/commands/seed.py   # bulk-seeds 10M rows in ~10 min
├── benchmarks/
│   ├── bench.py              # locust/pytest-benchmark harness, JSON results
│   └── results/              # committed benchmark runs
├── docs/case-studies/
│   ├── 01-composite-indexes.md
│   ├── 02-n-plus-one.md
│   ├── 03-fulltext-search.md
│   ├── 04-pagination-at-scale.md
│   └── 05-aggregation-strategies.md
└── sql/                      # raw EXPLAIN outputs, index DDL, pg_stat_statements dumps
```

## 📊 Data model & scale

- 100k users · 1M products · 5M orders · 8M order items · 2M reviews
- Seeded with `bulk_create(batch_size=10000)` + Faker; deterministic seed for
  reproducible benchmarks
- Skewed data distribution on purpose (80/20 rule) — uniform random data hides
  real-world index problems

## 🔬 Case studies (the interesting part)

### 1. Composite & covering indexes
`orders(user_id, created_at DESC)` — why column *order* in the index matters, when
PostgreSQL chooses an index-only scan, and how `INCLUDE (total)` removed the heap
fetch entirely.

### 2. Killing N+1 queries
The review feed made **1 + 2N queries** (Django's silent default). Django Debug
Toolbar screenshots show 4,201 queries → 3 queries after
`select_related("user")` + `prefetch_related("product__category")`.

### 3. Full-text search, wrong then right
`icontains` (sequential scan, 3.1s) → PostgreSQL `tsvector` + GIN index (60ms) and
MySQL `FULLTEXT ... MATCH AGAINST`. Includes the trigram (`pg_trgm`) alternative for
fuzzy matching and when to pick which.

### 4. Pagination at scale
Why `OFFSET 900000 LIMIT 20` reads and throws away 900k rows, with keyset (seek)
pagination as the fix — including the Django implementation.

### 5. Aggregation strategies
The "top customers this month" dashboard: naive `annotate()` on 5M rows vs a
covering index vs an incrementally-refreshed materialized view. Trade-offs measured.

## 🚀 Run it yourself

```bash
git clone https://github.com/<you>/django-query-lab && cd django-query-lab
docker compose up -d
docker compose exec app python manage.py migrate
docker compose exec app python manage.py seed --scale full   # ~10 min, 10M rows
docker compose exec app python benchmarks/bench.py --suite before
docker compose exec app python benchmarks/bench.py --suite after
```

Grafana at `localhost:3000` shows live `pg_stat_statements` / `performance_schema`
dashboards while benchmarks run.

## 🧰 Tooling demonstrated

Django Debug Toolbar · `EXPLAIN (ANALYZE, BUFFERS)` · `pg_stat_statements` ·
MySQL `performance_schema` & slow query log · `pg_trgm` · Prometheus exporters ·
Grafana · locust

## 📜 License

MIT — use anything here in your own projects.

---

*Built by [Your Name], MySQL/PostgreSQL DBA. I do this professionally — profile:
[your Upwork link].*
