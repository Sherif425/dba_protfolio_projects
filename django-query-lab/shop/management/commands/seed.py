"""
seed.py — Django management command
Place at: app/shop/management/commands/seed.py
(create empty __init__.py files in management/ and management/commands/)

Seeds the shop database with realistically SKEWED data. Uniform random data hides
index problems; real traffic follows the 80/20 rule, so we use a Pareto distribution
to pick users and products.

Usage:
    python manage.py seed --scale small            # ~150k rows, quick dev runs
    python manage.py seed --scale medium           # ~1.5M rows
    python manage.py seed --scale full             # ~16M rows total, 20-40 min
    python manage.py seed --scale full --database mysql

Deterministic (seeded RNG) so benchmark runs are reproducible.
"""

import random
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.utils import timezone
from faker import Faker

from shop.models import Category, Order, OrderItem, Product, Review

SCALES = {
    #            users   products   orders     reviews
    "tiny":   (    200,      500,     2_000,       500),  # smoke test
    "small":  (  5_000,   20_000,   100_000,    40_000),
    "medium": ( 30_000,  200_000, 1_000_000,   400_000),
    "full":   (100_000, 1_000_000, 5_000_000, 2_000_000),
}

BATCH = 10_000
STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]
# weights: most orders complete, few cancel — again, skew on purpose
STATUS_WEIGHTS = [5, 15, 15, 55, 7, 3]


def pareto_index(n: int, alpha: float = 1.16) -> int:
    """Pick an index 0..n-1 with 80/20 skew (alpha=1.16 ≈ classic Pareto)."""
    # paretovariate returns [1, inf); map its tail onto the id range
    v = random.paretovariate(alpha)
    idx = int((v - 1.0) * n / 20.0)  # /20 squeezes most mass into low indices
    return min(idx, n - 1)


def skewed_datetime(days_back: int = 1095):
    """Random datetime in the last `days_back` days, biased toward recent."""
    # squaring a uniform sample biases toward 0 (= now)
    ago = random.random() ** 2 * days_back
    return timezone.now() - timedelta(
        days=ago, seconds=random.randint(0, 86_400)
    )


class Command(BaseCommand):
    help = "Seed the database with skewed, realistic e-commerce data."

    def add_arguments(self, parser):
        parser.add_argument("--scale", choices=SCALES, default="small")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **opts):
        random.seed(42)
        Faker.seed(42)
        fake = Faker()
        db = opts["database"]
        n_users, n_products, n_orders, n_reviews = SCALES[opts["scale"]]
        t0 = time.perf_counter()
        User = get_user_model()

        self.stdout.write(f"Seeding scale={opts['scale']} into db={db}")

        # ---------- categories ----------
        cats = [Category(name=f"{fake.word().title()} & {fake.word().title()}")
                for _ in range(50)]
        Category.objects.using(db).bulk_create(cats)
        cat_ids = list(Category.objects.using(db).values_list("id", flat=True))
        self._log("categories", 50, t0)

        # ---------- users ----------
        done = 0
        while done < n_users:
            n = min(BATCH, n_users - done)
            users = [
                User(username=f"user_{done + i}",
                     email=f"user_{done + i}@example.com",
                     password="!")  # unusable password, fine for a lab
                for i in range(n)
            ]
            User.objects.using(db).bulk_create(users)
            done += n
            self._log("users", done, t0)
        user_ids = list(User.objects.using(db).values_list("id", flat=True))

        # ---------- products ----------
        done = 0
        while done < n_products:
            n = min(BATCH, n_products - done)
            with transaction.atomic(using=db):
                Product.objects.using(db).bulk_create([
                    Product(
                        category_id=random.choice(cat_ids),
                        name=fake.catch_phrase()[:200],
                        description=fake.paragraph(nb_sentences=8),
                        price=round(random.uniform(3, 900), 2),
                    ) for _ in range(n)
                ])
            done += n
            if done % 100_000 == 0 or done == n_products:
                self._log("products", done, t0)
        product_ids = list(Product.objects.using(db).values_list("id", flat=True))

        # ---------- orders (skewed users, skewed time) ----------
        done = 0
        while done < n_orders:
            n = min(BATCH, n_orders - done)
            with transaction.atomic(using=db):
                Order.objects.using(db).bulk_create([
                    Order(
                        user_id=user_ids[pareto_index(len(user_ids))],
                        status=random.choices(STATUSES, STATUS_WEIGHTS)[0],
                        total=0,  # fixed by SQL after items exist
                        created_at=skewed_datetime(),
                    ) for _ in range(n)
                ])
            done += n
            if done % 100_000 == 0 or done == n_orders:
                self._log("orders", done, t0)

        # ---------- order items (1-4 per order, skewed products) ----------
        # Second pass over order ids: works on MySQL too, where bulk_create
        # doesn't return primary keys.
        items, made = [], 0
        qs = Order.objects.using(db).values_list("id", flat=True).iterator(
            chunk_size=BATCH)
        for oid in qs:
            for _ in range(random.choices([1, 2, 3, 4], [55, 25, 13, 7])[0]):
                items.append(OrderItem(
                    order_id=oid,
                    product_id=product_ids[pareto_index(len(product_ids))],
                    quantity=random.choices([1, 2, 3], [80, 15, 5])[0],
                    unit_price=round(random.uniform(3, 900), 2),
                ))
            if len(items) >= BATCH:
                OrderItem.objects.using(db).bulk_create(items)
                made += len(items)
                items = []
                if made % 200_000 < BATCH:
                    self._log("order_items", made, t0)
        if items:
            OrderItem.objects.using(db).bulk_create(items)
            made += len(items)
        self._log("order_items", made, t0)

        # ---------- fix order totals with ONE set-based UPDATE ----------
        # (Doing this row-by-row in Python would take hours. This is the kind of
        #  set-based thinking the whole lab is about.)
        self.stdout.write("Updating order totals via SQL ...")
        vendor = connections[db].vendor
        with connections[db].cursor() as cur:
            if vendor == "postgresql":
                cur.execute("""
                    UPDATE shop_order o SET total = s.t
                    FROM (SELECT order_id, SUM(quantity * unit_price) AS t
                          FROM shop_orderitem GROUP BY order_id) s
                    WHERE s.order_id = o.id
                """)
            elif vendor == "mysql":
                cur.execute("""
                    UPDATE shop_order o
                    JOIN (SELECT order_id, SUM(quantity * unit_price) AS t
                          FROM shop_orderitem GROUP BY order_id) s
                      ON s.order_id = o.id
                    SET o.total = s.t
                """)
            else:  # sqlite (smoke tests) — correlated subquery, portable but slower
                cur.execute("""
                    UPDATE shop_order SET total = COALESCE(
                        (SELECT SUM(quantity * unit_price) FROM shop_orderitem
                         WHERE shop_orderitem.order_id = shop_order.id), 0)
                """)
        self._log("totals updated", n_orders, t0)

        # ---------- reviews ----------
        done = 0
        while done < n_reviews:
            n = min(BATCH, n_reviews - done)
            with transaction.atomic(using=db):
                Review.objects.using(db).bulk_create([
                    Review(
                        product_id=product_ids[pareto_index(len(product_ids))],
                        user_id=user_ids[pareto_index(len(user_ids))],
                        rating=random.choices([1, 2, 3, 4, 5],
                                              [5, 7, 15, 33, 40])[0],
                        body=fake.paragraph(nb_sentences=4),
                        created_at=skewed_datetime(),
                    ) for _ in range(n)
                ])
            done += n
            if done % 200_000 == 0 or done == n_reviews:
                self._log("reviews", done, t0)

        mins = (time.perf_counter() - t0) / 60
        self.stdout.write(self.style.SUCCESS(f"Done in {mins:.1f} min."))
        self.stdout.write(
            "Verify skew:  SELECT user_id, COUNT(*) FROM shop_order "
            "GROUP BY user_id ORDER BY 2 DESC LIMIT 10;"
        )

    def _log(self, what, n, t0):
        self.stdout.write(f"  {what:<14} {n:>10,}   "
                          f"({time.perf_counter() - t0:6.0f}s elapsed)")
