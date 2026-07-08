# django-query-lab — working scaffold

Runnable Django project for the query-optimization portfolio piece.
Full portfolio README: see README-django-query-lab.md (repo root when you publish).

## Quick start

```bash
pip install -r requirements.txt
docker compose up -d                     # PostgreSQL 16 + MySQL 8.4

# PostgreSQL (default alias)
python manage.py migrate
docker compose exec pg psql -U postgres -d shop \
  -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
python manage.py seed --scale small      # ~2 min; use --scale full for 5M orders

# MySQL (second alias)
python manage.py migrate --database mysql
python manage.py seed --scale small --database mysql

# zero-dependency smoke test (no docker needed)
USE_SQLITE=1 python manage.py migrate
USE_SQLITE=1 python manage.py seed --scale tiny
```

## Benchmark the before/after

```bash
python manage.py runserver               # terminal 1
python benchmarks/bench.py --suite both -o benchmarks/results/run1.json   # terminal 2
```

Endpoints live at `/api/slow/...` and `/api/fast/...` (see shop/urls.py).
The fast index-dependent endpoints only show their full speedup after you apply
`sql/indexes_after.sql` — apply one case study at a time, benchmarking between.

## Workflow (one git commit per fix)

1. Benchmark the slow suite, save EXPLAIN output to sql/before/
2. Apply ONE fix (index from sql/indexes_after.sql, or the views_fast technique)
3. Re-benchmark, commit with before/after numbers in the message
4. Write docs/case-studies/NN-name.md
