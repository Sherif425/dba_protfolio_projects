# Build Guide — django-query-optimization-lab

Concrete, copy-pasteable steps to build the flagship project on your own machine or a
cheap VPS. Estimated time: 1–2 weeks working evenings.

---

## Step 0 — Environment (30 min)

```yaml
# docker-compose.yml
services:
  pg:
    image: postgres:16
    environment: { POSTGRES_PASSWORD: devpass, POSTGRES_DB: shop }
    ports: ["5432:5432"]
    command: >
      postgres -c shared_preload_libraries=pg_stat_statements
               -c pg_stat_statements.track=all
               -c shared_buffers=1GB
    volumes: [pgdata:/var/lib/postgresql/data]

  mysql:
    image: mysql:8.4
    environment: { MYSQL_ROOT_PASSWORD: devpass, MYSQL_DATABASE: shop }
    ports: ["3306:3306"]
    command: >
      --slow-query-log=ON --long-query-time=0.5
      --innodb-buffer-pool-size=1G
    volumes: [mysqldata:/var/lib/mysql]

volumes: { pgdata: {}, mysqldata: {} }
```

```bash
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install django psycopg2-binary mysqlclient faker django-debug-toolbar \
            djangorestframework locust
django-admin startproject config . && python manage.py startapp shop
```

Enable `pg_stat_statements` once: `CREATE EXTENSION pg_stat_statements;`

Django tip: define two database aliases in `settings.py` (`default` = postgres,
`mysql` = mysql) so every benchmark can run against both engines with
`--database mysql`.

## Step 1 — Models (1 hour)

```python
# shop/models.py
class Category(models.Model):
    name = models.CharField(max_length=100)

class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

class Order(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20)          # pending/paid/shipped/...
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(db_index=False)  # deliberately no index yet!

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField()
    body = models.TextField()
    created_at = models.DateTimeField()
```

**Important:** start with NO extra indexes. The "before" state must be genuinely naive.

## Step 2 — Seed 10M rows (half a day incl. runtime)

Key techniques for the `seed` management command:
- `bulk_create(objs, batch_size=10_000)` — never `.save()` in a loop
- Skewed distributions: `random.paretovariate(1.16)` to pick users/products, so 20%
  of users generate 80% of orders (uniform data hides index problems)
- Spread `created_at` over 3 years with recent bias
- Wrap batches in `transaction.atomic()`
- Scale flags: `--scale small` (100k orders, for dev) / `--scale full` (5M)

Verify: `SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 2 DESC;`

## Step 3 — Write the SLOW endpoints first (1 day)

These are your "before" snapshots — commit them and benchmark them:

```python
# views_slow.py  (each one is a classic real-world mistake)

def user_orders(request, user_id):          # missing composite index
    orders = Order.objects.filter(user_id=user_id).order_by("-created_at")[:50]
    ...

def review_feed(request):                   # N+1 explosion
    reviews = Review.objects.order_by("-created_at")[:100]
    data = [{
        "user": r.user.username,            # +1 query each
        "product": r.product.name,          # +1 query each
        "category": r.product.category.name # +1 query each
    } for r in reviews]

def search(request):                        # unindexable pattern
    q = request.GET["q"]
    products = Product.objects.filter(description__icontains=q)[:20]

def page(request):                          # deep OFFSET pagination
    n = int(request.GET.get("page", 45000))
    return Order.objects.order_by("id")[n*20:(n+1)*20]

def top_customers(request):                 # 5M-row aggregation per request
    return (Order.objects.filter(created_at__gte=month_start)
            .values("user__username").annotate(s=Sum("total")).order_by("-s")[:10])
```

## Step 4 — Measure the "before" (1 day)

For every endpoint capture three artifacts:
1. **Latency:** `python benchmarks/bench.py` (simple `time.perf_counter()` loop, 50
   runs, report p50/p95) — commit JSON results
2. **Query plan:** `EXPLAIN (ANALYZE, BUFFERS)` in psql / `EXPLAIN ANALYZE` in MySQL —
   save the raw output to `sql/before/`
3. **Query count:** Django Debug Toolbar screenshot (the N+1 one will show 300+ queries)

Also grab the global view — this is what a DBA looks at first on a client system:
```sql
SELECT calls, mean_exec_time, query FROM pg_stat_statements
ORDER BY total_exec_time DESC LIMIT 10;
```

## Step 5 — Fix, one commit per fix (2–4 days)

| Fix | What to do | Expected lesson |
|---|---|---|
| Composite index | `Index(fields=["user", "-created_at"])` on Order | plan flips Seq Scan → Index Scan; try `INCLUDE (total, status)` for index-only |
| N+1 | `select_related("user", "product__category")` | 301 queries → 1 |
| Full-text | PG: `SearchVectorField` + GIN, MySQL: `FULLTEXT` index | why `icontains` can never use a btree; compare with `pg_trgm` |
| Pagination | keyset: `filter(id__gt=last_id)[:20]` | constant-time at any depth |
| Aggregation | materialized view refreshed by cron/celery + index | when to precompute vs compute |

Commit message format (this is your marketing):
```
perf(orders): composite index on (user_id, created_at DESC)

before: p95 8,400ms, Seq Scan on orders (cost=0..112,340)
after:  p95 45ms,   Index Scan using idx_orders_user_created
5M rows, PostgreSQL 16. Full analysis: docs/case-studies/01-composite-indexes.md
```

## Step 6 — Case studies + screenshots (2 days)

Each `docs/case-studies/NN-*.md`: the symptom → how you diagnosed it
(`pg_stat_statements` → `EXPLAIN`) → the fix → the numbers → when NOT to use this fix
(indexes cost writes and RAM; mention it — it signals seniority).

Screenshots to take for Upwork portfolio:
- Debug Toolbar: 301 queries vs 3 queries side by side
- `EXPLAIN ANALYZE` before/after
- A Grafana or `pg_stat_statements` "top queries" view

## Step 7 — Publish

- Push to GitHub, fill the README results table with YOUR real numbers
- Pin the repo on your GitHub profile
- Create the Upwork portfolio item: title with the biggest % improvement, best
  screenshot, 4-sentence story, repo link

---

## Doing it on a real VPS instead of Docker (optional, +$6/mo)

A 2GB DigitalOcean/Hetzner box makes it more production-like: install PostgreSQL and
MySQL from official repos, tune `shared_buffers`/`innodb_buffer_pool_size` yourself,
set up UFW + fail2ban, and mention "deployed and tuned on a live Linux server" in the
portfolio item. Everything above works identically.
